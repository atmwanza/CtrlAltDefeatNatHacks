"""Finger-tapping prototype routes (laptop side). Kept apart from app.py, so the
validated spiral backend is untouched; server.py adds these routes to it.

Flow: tablet -> POST /tapping/start -> laptop -> capture device POST /record ->
device records, then POST /tapping/upload (ZIP of JPEG frames + timestamps) ->
laptop analyses in the background -> tablet polls GET /tapping/status/{id}.

The capture device (Raspberry Pi, laptop webcam or synthetic source; all run
pi/pi_capture.py) announces itself every few seconds with POST /pi/hello, so its IP
never has to be typed in. Nothing is written to disk: frames live in memory until the
landmarks are extracted.
"""
import json
import threading
import time
import uuid

import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from tapping_analysis import analyze_clip

router = APIRouter()

CAPTURE_STALE_S = 12      # no hello for this long -> camera considered offline
UPLOAD_GRACE_S = 45       # recording + upload must finish within duration + this
MAX_JOBS = 30

_capture = {'url': None, 'seen': 0.0, 'source': None, 'camera': None}
_jobs = {}
_jobs_lock = threading.Lock()
_analysis_lock = threading.Lock()   # one analysis at a time keeps the laptop responsive


def _capture_ready():
    return _capture['url'] is not None and time.time() - _capture['seen'] < CAPTURE_STALE_S


def _set_job(sid, **fields):
    with _jobs_lock:
        _jobs.setdefault(sid, {}).update(fields)
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs, key=lambda k: _jobs[k].get('created', 0))[:len(_jobs) - MAX_JOBS]:
                _jobs.pop(old, None)


@router.get('/health')
def health():
    age = time.time() - _capture['seen'] if _capture['seen'] else None
    return {'ok': True, 'capture_ready': _capture_ready(), 'capture_url': _capture['url'],
            'capture_source': _capture['source'], 'camera': _capture['camera'],
            'capture_age_s': round(age, 1) if age is not None else None}


@router.post('/pi/hello')
def capture_hello(info: dict, request: Request):
    # The address we see the device at is the one we can reach it on (works for the Pi on
    # the hotspot, the Ethernet fallback, and a local webcam process alike).
    host = request.client.host
    _capture.update(url=f"http://{host}:{int(info.get('port', 8000))}", seen=time.time(),
                    source=info.get('source'), camera=info.get('camera'))
    return {'ok': True}


@router.post('/tapping/start')
def tapping_start(body: dict):
    hand = body.get('hand')
    if hand not in ('right', 'left'):
        raise HTTPException(400, "hand must be 'right' or 'left'")
    if not _capture_ready():
        raise HTTPException(503, 'Camera not connected. Is the Pi (or webcam capture) running?')
    duration = float(body.get('duration_s', 10))
    sid = uuid.uuid4().hex[:8]
    _set_job(sid, state='recording', hand=hand, created=time.time(), duration_s=duration)
    try:
        r = requests.post(f"{_capture['url']}/record",
                          json={'session_id': sid, 'hand': hand, 'duration_s': duration}, timeout=3)
        if r.status_code == 409:
            raise RuntimeError('camera is busy with another recording')
        r.raise_for_status()
    except Exception as e:
        _set_job(sid, state='error', error=f'Could not start the camera: {e}')
        raise HTTPException(502, f'Could not start the camera: {e}')
    return {'session_id': sid, 'duration_s': duration}


@router.post('/tapping/upload')
async def tapping_upload(clip: UploadFile = File(...), meta: str = Form(...)):
    m = json.loads(meta)
    sid = m.get('session_id') or uuid.uuid4().hex[:8]
    data = await clip.read()
    with _jobs_lock:
        known = sid in _jobs
    if not known:   # e.g. a manual recording started on the capture device itself
        _set_job(sid, hand=m.get('hand'), created=time.time(), duration_s=m.get('duration_s', 10))
    _set_job(sid, state='analyzing', capture=m)
    threading.Thread(target=_analyze, args=(sid, data, m), daemon=True).start()
    return {'ok': True, 'session_id': sid}


def _analyze(sid, data, meta):
    try:
        with _analysis_lock:
            result = analyze_clip(data, meta)
        _set_job(sid, state='done', result=result)
        print(f"[tapping] {sid} {meta.get('hand')}: valid={result.get('valid')} "
              f"taps={result.get('n_taps')} rate={result.get('rate_hz')} "
              f"decrement={result.get('decrement_pct_per_tap')} detect={result.get('detect_pct')}% "
              f"({result.get('analysis_s')} s)")
    except Exception as e:
        _set_job(sid, state='error', error=f'Analysis failed: {e}')
        print(f"[tapping] {sid} analysis failed: {e}")
    finally:
        del data   # frames are never stored


@router.get('/tapping/status/{sid}')
def tapping_status(sid: str):
    with _jobs_lock:
        job = dict(_jobs.get(sid, {'state': 'unknown'}))
    if job.get('state') == 'recording' and time.time() - job['created'] > job['duration_s'] + UPLOAD_GRACE_S:
        _set_job(sid, state='error', error='No recording arrived from the camera.')
        job.update(state='error', error='No recording arrived from the camera.')
    job.pop('capture', None)
    return job


@router.get('/tapping/latest')
def tapping_latest():
    with _jobs_lock:
        done = [dict(j, session_id=k) for k, j in _jobs.items() if j.get('state') == 'done']
    if not done:
        raise HTTPException(404, 'No tapping results yet.')
    return max(done, key=lambda j: j['created'])


@router.get('/tapping/preview.jpg')
def tapping_preview():
    if not _capture_ready():
        raise HTTPException(503, 'Camera not connected.')
    try:
        r = requests.get(f"{_capture['url']}/snapshot.jpg", timeout=2)
    except requests.RequestException as e:
        raise HTTPException(503, f'Camera not reachable: {e}')
    if r.status_code != 200:
        raise HTTPException(r.status_code, 'Camera busy.')
    return Response(r.content, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
