"""balance_api.py - balance (camera Romberg) test routes for the DrawDx site.

EXPERIMENTAL: stand still 30 s with eyes open, then 30 s with eyes closed. The posture is
tracked with MediaPipe Pose (pose.py) and measured with Brahm's sway_features / sway_score.
There is no Parkinson's reference for this setup, so it only compares with our own healthy
baseline and gives no Parkinson's score.

It reuses the tapping test's camera: the Pi (or webcam capture) registered with tapping.py
records the clip and uploads it to /tapping/upload as usual; server.py points uploads whose
"hand" starts with "balance-" at handle_upload() below. The Pi needs no changes.

Healthy baseline: each run saves its numbers (never the video) to recordings/. Copy healthy
people's files into baseline/ (3+ per stage) and restart the server.
"""
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException

import tapping                       # 01/tapping.py: the camera registry (/pi/hello)
from pose import analyze_frames, load_clip
from sway_score import build_baseline, romberg
from sway_score import score as sway_score

router = APIRouter()

HERE = Path(__file__).parent
BASELINE_DIR = HERE / 'baseline'
REC_DIR = HERE / 'recordings'
TRIAL_SECONDS = 30            # the Pi caps a recording at 30 s
UPLOAD_GRACE_S = 90           # a 30 s clip is large (~1200 frames); allow time for the upload
HAND_PREFIX = 'balance-'      # sent as the "hand" so the upload can be told apart from tapping
MAX_JOBS = 30
DISCLAIMER = ("Experimental. Compared only with our own small healthy baseline, not with "
              "people with Parkinson's. Sway changes with age, vision, footwear, fatigue and "
              "many conditions, so this is not a Parkinson's test on its own.")

_jobs = {}
_jobs_lock = threading.Lock()
_analysis_lock = threading.Lock()   # one analysis at a time keeps the laptop responsive


# ---------- baseline ----------

def load_baselines():
    trials = [json.loads(p.read_text()) for p in BASELINE_DIR.glob('*.json')] if BASELINE_DIR.exists() else []
    out = {}
    for cond in ('EO', 'EC'):
        try:
            out[cond] = build_baseline([t for t in trials if t.get('condition') == cond], cond)
            print(f"Balance baseline '{cond}': {_n_trials(out[cond])} valid trials")
        except ValueError:
            pass   # fewer than 3 valid trials: results are shown without a comparison
    if not out:
        print('Balance baseline: none yet (copy healthy recordings into balance/backend/balance/baseline/)')
    return out


def _n_trials(baseline):
    return next(iter(baseline['features'].values()))['n']


BASELINES = load_baselines()


# ---------- jobs ----------

def _set_job(sid, **fields):
    with _jobs_lock:
        _jobs.setdefault(sid, {}).update(fields)
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs, key=lambda k: _jobs[k].get('created', 0))[:len(_jobs) - MAX_JOBS]:
                _jobs.pop(old, None)


def _save_trial(feats):
    REC_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    (REC_DIR / f"{stamp}_balance_{feats.get('condition')}.json").write_text(json.dumps(feats))


def _analyze(sid, data):
    with _jobs_lock:
        job = dict(_jobs.get(sid, {}))
    try:
        frames, t_ms = load_clip(data)
        del data
        with _analysis_lock:
            feats = analyze_frames(frames, t_ms, job['condition'], job.get('height_cm'))
        _save_trial(feats)
        _set_job(sid, state='done', result=feats)
        print(f"[balance] {sid} {job['condition']}: valid={feats.get('valid')} "
              f"mean_vel={feats.get('mean_vel')} rms_ml={feats.get('rms_ml')} "
              f"detect={feats.get('detect_pct')}% ({feats.get('analysis_s')} s)")
    except Exception as e:
        _set_job(sid, state='error', error=f'Analysis failed: {e}')
        print(f'[balance] {sid} analysis failed: {e}')


def handle_upload(sid, data, meta):
    """Called by tapping.py's /tapping/upload for clips whose hand starts with 'balance-'."""
    with _jobs_lock:
        known = sid in _jobs
    if not known:
        raise HTTPException(404, 'Unknown balance recording (start it from the Balance tab).')
    _set_job(sid, state='analyzing')
    threading.Thread(target=_analyze, args=(sid, data), daemon=True).start()
    return {'ok': True, 'session_id': sid}


# ---------- routes ----------

@router.post('/balance/start')
def balance_start(body: dict):
    cond = body.get('condition')
    if cond not in ('EO', 'EC'):
        raise HTTPException(400, "condition must be 'EO' (eyes open) or 'EC' (eyes closed)")
    if not tapping._capture_ready():
        raise HTTPException(503, 'Camera not connected. Is the Pi (or webcam capture) running?')
    try:
        height = float(body.get('height_cm') or 0)
    except (TypeError, ValueError):
        height = 0
    if not 100 <= height <= 230:
        height = None
    sid = uuid.uuid4().hex[:8]
    _set_job(sid, state='recording', condition=cond, height_cm=height, created=time.time())
    payload = {'session_id': sid, 'hand': HAND_PREFIX + cond, 'duration_s': TRIAL_SECONDS}
    try:
        # Right after the eyes-open upload the Pi can still be finishing up for a moment.
        for attempt in range(10):
            r = requests.post(f"{tapping._capture['url']}/record", json=payload, timeout=3)
            if r.status_code != 409:
                break
            time.sleep(0.5)
        if r.status_code == 409:
            raise RuntimeError('camera is busy with another recording')
        r.raise_for_status()
    except Exception as e:
        _set_job(sid, state='error', error=f'Could not start the camera: {e}')
        raise HTTPException(502, f'Could not start the camera: {e}')
    return {'session_id': sid, 'duration_s': TRIAL_SECONDS}


@router.get('/balance/status/{sid}')
def balance_status(sid: str):
    with _jobs_lock:
        job = dict(_jobs.get(sid, {'state': 'unknown'}))
    if job.get('state') == 'recording' and time.time() - job['created'] > TRIAL_SECONDS + UPLOAD_GRACE_S:
        _set_job(sid, state='error', error='No recording arrived from the camera.')
        job.update(state='error', error='No recording arrived from the camera.')
    return job


@router.post('/balance/result')
def balance_result(body: dict):
    """Both stages: {"eo": session_id, "ec": session_id}."""
    trials = {}
    with _jobs_lock:
        for cond, key, name in (('EO', 'eo', 'eyes-open'), ('EC', 'ec', 'eyes-closed')):
            job = _jobs.get(body.get(key) or '', {})
            if job.get('condition') != cond or job.get('state') != 'done':
                raise HTTPException(400, f'Record the {name} stage first.')
            trials[cond] = job['result']

    stages = {}
    for cond, feats in trials.items():
        if cond in BASELINES:
            stages[cond] = sway_score(feats, BASELINES[cond])
        elif not feats.get('valid'):
            stages[cond] = {'status': 'invalid_trial', 'reasons': feats.get('reasons', []),
                            'message': 'This recording failed quality checks, so it was not scored.'}
        else:
            stages[cond] = {'status': 'no_baseline', 'units': feats.get('units'),
                            'measurements': {k: feats.get(k) for k in ('path_len', 'mean_vel', 'rms_ml')},
                            'warnings': feats.get('warnings', []),
                            'message': 'No healthy baseline recorded yet, so there is nothing to compare with.'}
    return {
        'stages': stages,
        'romberg': romberg(trials['EO'], trials['EC']),
        'baseline_trials': {c: _n_trials(b) for c, b in BASELINES.items()},
        'disclaimer': DISCLAIMER,
    }