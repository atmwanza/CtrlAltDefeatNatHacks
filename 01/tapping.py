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
import asyncio
import json
import os
import re
import threading
import time
import uuid

import cv2
import httpx
import numpy as np
import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from tapping_analysis import analyze_clip, ensure_model

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


# ---------- live preview: MJPEG stream relayed from the capture device ----------
# The tablet can only reach this laptop (adb reverse), so the laptop relays the capture
# device's /stream.mjpg. Before a recording it also draws the MediaPipe hand skeleton and
# the thumb-index line on each frame, so you can see the tracking live; during a recording
# frames pass through untouched (the recording itself is taken on the capture device and
# is not affected either way). At most MAX_VIEWERS streams stay open (oldest closed
# first), so stale connections can't pile up in Chrome.

OVERLAY = os.environ.get('TAP_PREVIEW_OVERLAY', '1') != '0'
HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
                    (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
                    (18, 19), (19, 20), (0, 17)]
MAX_VIEWERS = 3     # e.g. tablet + laptop screen; older streams beyond this are closed
_stream = {'next': 0, 'active': []}
_overlay = {'landmarker': None, 'ts': 0, 'lock': threading.Lock()}


def _recording_now():
    with _jobs_lock:
        return any(j.get('state') == 'recording' for j in _jobs.values())


def _annotate(jpeg):
    """Draw the hand skeleton on one preview frame (runs in a worker thread)."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    with _overlay['lock']:
        if _overlay['landmarker'] is None:
            _overlay['landmarker'] = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=mpt.BaseOptions(model_asset_path=str(ensure_model())),
                running_mode=vision.RunningMode.VIDEO, num_hands=1))
        bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return jpeg
        ts = max(int(time.monotonic() * 1000), _overlay['ts'] + 1)   # strictly increasing
        _overlay['ts'] = ts
        res = _overlay['landmarker'].detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), ts)
    if res.hand_landmarks:
        h, w = bgr.shape[:2]
        pts = [(int(p.x * w), int(p.y * h)) for p in res.hand_landmarks[0]]
        for a, b in HAND_CONNECTIONS:
            cv2.line(bgr, pts[a], pts[b], (255, 255, 255), 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(bgr, p, 3, (153, 90, 61), -1, cv2.LINE_AA)
        cv2.line(bgr, pts[4], pts[8], (0, 200, 255), 3, cv2.LINE_AA)     # the measured opening
        for k in (4, 8):
            cv2.circle(bgr, pts[k], 7, (0, 200, 255), -1, cv2.LINE_AA)
    ok, enc = cv2.imencode('.jpg', bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return enc.tobytes() if ok else jpeg


def _part(jpeg):
    return (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
            + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')


_HEADER_END = b'\r\n\r\n'
_LENGTH = re.compile(rb'Content-Length:\s*(\d+)', re.I)


@router.get('/tapping/stream.mjpg')
async def tapping_stream(request: Request):
    if not _capture_ready():
        raise HTTPException(503, 'Camera not connected.')
    _stream['next'] += 1
    token = _stream['next']
    _stream['active'].append(token)
    del _stream['active'][:-MAX_VIEWERS]      # close the oldest if there are too many
    url = f"{_capture['url']}/stream.mjpg"

    async def frames():
        buf = b''
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
                async with client.stream('GET', url) as upstream:
                    async for chunk in upstream.aiter_bytes():
                        if token not in _stream['active'] or await request.is_disconnected():
                            break
                        buf += chunk
                        while True:          # cut complete JPEG parts out of the multipart stream
                            end = buf.find(_HEADER_END)
                            if end < 0:
                                break
                            m = _LENGTH.search(buf, 0, end)
                            start = end + len(_HEADER_END)
                            if not m:
                                buf = buf[start:]
                                continue
                            n = int(m.group(1))
                            if len(buf) < start + n:
                                break
                            jpeg, buf = buf[start:start + n], buf[start + n:]
                            if OVERLAY and not _recording_now():
                                try:
                                    jpeg = await asyncio.to_thread(_annotate, jpeg)
                                except Exception as e:   # never let the overlay kill the preview
                                    print(f'[tapping] preview overlay error: {e}')
                            yield _part(jpeg)
        except httpx.HTTPError:      # capture device went away; the tablet reconnects
            return
        finally:
            if token in _stream['active']:
                _stream['active'].remove(token)

    return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame',
                             headers={'Cache-Control': 'no-store, no-cache', 'X-Accel-Buffering': 'no'})


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
