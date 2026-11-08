"""Finger-tapping analysis: a digitised MDS-UPDRS 3.4 (prototype, not scored).

A clip is a ZIP of JPEG frames plus timestamps.csv (frame, sensor_ts_ns), sent by
pi/pi_capture.py (Raspberry Pi camera, laptop webcam or synthetic source).

Pipeline:
  1. MediaPipe Hand Landmarker (VIDEO mode) on every frame, using the real capture
     timestamps.
  2. Aperture d(t) = |thumb tip - index tip| / |wrist - middle-finger MCP|. Dividing by
     palm length cancels camera distance and hand size, so d is in "palm lengths".
  3. Fill detection gaps up to 100 ms, resample to an even 100 Hz grid (same rate as the
     spiral pipeline), zero-phase 4th-order Butterworth low-pass at 8 Hz.
  4. Peak/trough detection: each tap is an opening peak between two closures.
  5. Per-hand features: tap rate, opening size, its variability, opening speed, rhythm
     variability, decrement (size change across taps), last/first ratio, hesitations.

Nothing here is compared with a Parkinson's reference: there isn't one for this setup yet.
"""
import csv
import io
import time
import urllib.request
import zipfile
from pathlib import Path

import cv2
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

MODEL_PATH = Path(__file__).parent / 'models' / 'hand_landmarker.task'
MODEL_URL = ('https://storage.googleapis.com/mediapipe-models/hand_landmarker/'
             'hand_landmarker/float16/latest/hand_landmarker.task')

FS = 100               # Hz, analysis grid (matches the spiral pipeline)
LOWPASS_HZ = 8.0       # keeps tapping (1-7 Hz) and drops landmark jitter
MAX_GAP_MS = 100       # bridge detection dropouts up to this long
MIN_DETECT = 0.90      # share of frames with a hand needed for a valid trial
MIN_TAPS = 5
MIN_TAP_GAP_S = 0.08   # no human taps faster than ~12 Hz
HESITATION_FACTOR = 2  # an interval > 2x the median interval counts as a hesitation

THUMB_TIP, INDEX_TIP, WRIST, MIDDLE_MCP = 4, 8, 0, 9


def ensure_model():
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


def load_clip(zip_bytes):
    """-> (list of JPEG bytes, timestamps in ms relative to the first frame)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        rows = list(csv.DictReader(io.StringIO(z.read('timestamps.csv').decode())))
        frames = [z.read(f"{int(r['frame']):05d}.jpg") for r in rows]
    ts_ns = np.array([int(r['sensor_ts_ns']) for r in rows], dtype=np.int64)
    return frames, (ts_ns - ts_ns[0]) / 1e6


def extract_aperture(frames, t_ms):
    """Run the hand landmarker over the clip. Returns d(t) (NaN where no hand) and the
    most common handedness label."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    options = vision.HandLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(ensure_model())),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    d = np.full(len(frames), np.nan)
    labels = {}
    last_ts = -1
    with vision.HandLandmarker.create_from_options(options) as landmarker:
        for i, jpeg in enumerate(frames):
            bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            h, w = bgr.shape[:2]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            ts = max(int(round(t_ms[i])), last_ts + 1)   # VIDEO mode needs strictly increasing ms
            last_ts = ts
            res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            if not res.hand_landmarks:
                continue
            p = res.hand_landmarks[0]
            xy = lambda k: np.array([p[k].x * w, p[k].y * h])   # pixels, so x and y share a scale
            palm = np.linalg.norm(xy(WRIST) - xy(MIDDLE_MCP))
            if palm > 1:
                d[i] = np.linalg.norm(xy(THUMB_TIP) - xy(INDEX_TIP)) / palm
            if res.handedness:
                lab = res.handedness[0][0].category_name
                labels[lab] = labels.get(lab, 0) + 1
    detected_hand = max(labels, key=labels.get) if labels else None
    return d, detected_hand


def fill_short_gaps(t_ms, d, max_gap_ms=MAX_GAP_MS):
    """Linearly bridge NaN runs no longer than max_gap_ms; longer runs stay NaN."""
    d = d.copy()
    ok = ~np.isnan(d)
    if ok.sum() < 2:
        return d
    i = 0
    n = len(d)
    while i < n:
        if ok[i]:
            i += 1
            continue
        j = i
        while j < n and not ok[j]:
            j += 1
        if 0 < i and j < n and (t_ms[j] - t_ms[i - 1]) <= max_gap_ms:
            d[i:j] = np.interp(t_ms[i:j], [t_ms[i - 1], t_ms[j]], [d[i - 1], d[j]])
        i = j
    return d


def tap_features(t_ms, d, fps_measured=None):
    """Features from an aperture series on the original (irregular) timestamps."""
    t_ms = np.asarray(t_ms, float)
    d = np.asarray(d, float)
    detect_pct = float(np.mean(~np.isnan(d)) * 100) if len(d) else 0.0
    warnings = []

    d = fill_short_gaps(t_ms, d)
    ok = ~np.isnan(d)
    if ok.sum() < 20:
        return {'valid': False, 'detect_pct': round(detect_pct, 1),
                'warnings': ['No hand found in the video. Check the hand is in view and well lit.']}

    # even 100 Hz grid using the real timestamps (only across detected stretches)
    t_s = t_ms[ok] / 1000.0
    grid = np.arange(t_s[0], t_s[-1], 1 / FS)
    x = np.interp(grid, t_s, d[ok])

    capture_fps = fps_measured or (len(t_ms) - 1) / max((t_ms[-1] - t_ms[0]) / 1000, 1e-6)
    cutoff = min(LOWPASS_HZ, 0.4 * capture_fps)          # stay below the capture Nyquist
    if len(x) > 30:
        b, a = butter(4, cutoff / (FS / 2))
        x = filtfilt(b, a, x)

    spread = np.percentile(x, 95) - np.percentile(x, 5)
    prominence = max(0.3 * spread, 0.05)                 # 0.05 palm lengths: ignore jitter
    peaks, _ = find_peaks(x, distance=int(MIN_TAP_GAP_S * FS), prominence=prominence)
    troughs, _ = find_peaks(-x, distance=int(MIN_TAP_GAP_S * FS), prominence=prominence)

    # a tap = an opening peak with a closure before it
    taps, amps, speeds = [], [], []
    for pk in peaks:
        before = troughs[troughs < pk]
        if not len(before):
            continue
        tr = before[-1]
        after = troughs[troughs > pk]
        base = x[tr] if not len(after) else (x[tr] + x[after[0]]) / 2
        taps.append(pk)
        amps.append(x[pk] - base)
        speeds.append(np.max(np.diff(x[tr:pk + 1])) * FS if pk > tr else 0.0)

    n = len(taps)
    series = _series(grid, x, taps)
    base_result = {'detect_pct': round(detect_pct, 1), 'capture_fps': round(float(capture_fps), 1),
                   'filter_hz': round(float(cutoff), 1), 'aperture_sd': round(float(np.std(x)), 4),
                   'series': series}
    if detect_pct < MIN_DETECT * 100:
        warnings.append(f'Hand found in only {detect_pct:.0f}% of frames; results may be unreliable.')
    if n < MIN_TAPS:
        warnings.append(f'Only {n} taps detected. Tap continuously, as big and fast as possible.')
        return {**base_result, 'valid': False, 'n_taps': n, 'warnings': warnings}

    tap_t = grid[taps]
    amps = np.array(amps)
    iti = np.diff(tap_t)
    med_iti = float(np.median(iti))
    idx = np.arange(n)
    first3, last3 = amps[:3].mean(), amps[-3:].mean()
    slope = np.polyfit(idx, amps, 1)[0]

    return {
        **base_result,
        'valid': detect_pct >= MIN_DETECT * 100,
        'warnings': warnings,
        'n_taps': n,
        'duration_s': round(float(tap_t[-1] - tap_t[0]), 2),
        'rate_hz': round(float((n - 1) / (tap_t[-1] - tap_t[0])), 2),
        'amp_mean': round(float(amps.mean()), 3),          # palm lengths
        'amp_cv': round(float(amps.std() / amps.mean()), 3),
        'peak_speed': round(float(np.mean(speeds)), 2),    # palm lengths per second
        'iti_cv': round(float(iti.std() / iti.mean()), 3),
        'decrement_pct_per_tap': round(float(slope / first3 * 100), 2),
        'last3_first3': round(float(last3 / first3), 3),
        'hesitations': int(np.sum(iti > HESITATION_FACTOR * med_iti)),
        'amplitudes': [round(float(a), 3) for a in amps],
    }


def _series(grid, x, taps, rate=50):
    """Downsampled trace for plotting on the tablet."""
    step = max(1, FS // rate)
    t0 = grid[0]
    return {'t': [round(float(v - t0), 3) for v in grid[::step]],
            'd': [round(float(v), 3) for v in x[::step]],
            'tap_t': [round(float(grid[k] - t0), 3) for k in taps],
            'tap_d': [round(float(x[k]), 3) for k in taps]}


def analyze_clip(zip_bytes, meta=None):
    meta = meta or {}
    started = time.perf_counter()
    frames, t_ms = load_clip(zip_bytes)
    d, detected_hand = extract_aperture(frames, t_ms)
    result = tap_features(t_ms, d, meta.get('fps_measured'))
    result.update({
        'hand': meta.get('hand'),
        'detected_hand': detected_hand,
        'n_frames': len(frames),
        'drops': meta.get('drops'),
        'source': meta.get('camera') or meta.get('source'),
        'analysis_s': round(time.perf_counter() - started, 2),
        'status': 'prototype_not_scored',
    })
    if meta.get('drops'):
        result.setdefault('warnings', []).append(f"{meta['drops']} dropped camera frames.")
    return result
