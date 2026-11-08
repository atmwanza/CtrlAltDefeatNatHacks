"""Finger-tapping analysis: a digitised MDS-UPDRS 3.4, scored against a published reference (tapping_reference.py).

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

Scoring: tapping_reference.py (Kasemsap et al. 2025, Parkinson's vs healthy) and
tapping_severity.py (Islam et al. 2023, MDS-UPDRS 3.4 severity band).
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
MIN_TAPS = 3            # the published reference has Parkinson's hands with only 4 taps in 10 s:
                        # slow tapping is the finding, so it must still get a result
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
    """Run the hand landmarker over the clip. Returns d(t) = thumb-index / palm length,
    the raw 3-D thumb-index distance in pixels (for the Kasemsap features), the wrist angle
    between thumb tip and index tip in degrees (for the Islam severity band; all NaN where
    no hand), and the most common handedness label."""
    from tapping_severity import wrist_angle
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
    dist = np.full(len(frames), np.nan)
    theta = np.full(len(frames), np.nan)
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
            xyz = lambda k: np.array([p[k].x * w, p[k].y * h, p[k].z * w])   # z ~ same scale as x
            palm = np.linalg.norm(xy(WRIST) - xy(MIDDLE_MCP))
            if palm > 1:
                d[i] = np.linalg.norm(xy(THUMB_TIP) - xy(INDEX_TIP)) / palm
            dist[i] = np.linalg.norm(xyz(THUMB_TIP) - xyz(INDEX_TIP))   # Kasemsap: 3-D tip distance
            theta[i] = wrist_angle(xy(WRIST), xy(THUMB_TIP), xy(INDEX_TIP))   # Islam: angle in pixels
            if res.handedness:
                lab = res.handedness[0][0].category_name
                labels[lab] = labels.get(lab, 0) + 1
    detected_hand = max(labels, key=labels.get) if labels else None
    return d, dist, theta, detected_hand


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
    if n < 5:
        warnings.append(f'Only {n} taps in 10 s. If you paused or stopped, record this hand again.')

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


KAS_PROMINENCE = 30.0   # Kasemsap: find_peaks prominence 0.3 on the max-normalised series


def kasemsap_features(t_ms, dist, fps_measured=None):
    """The published features of Kasemsap et al. 2025 (PLOS ONE), computed the same way so
    they can be compared with that study's 47 healthy / 53 Parkinson's reference:
      amplitude = thumb-index (3-D) distance as % of its maximum in this recording,
      count  = taps in the window,  mean / std = mean and SD of the tap peak amplitudes,
      diffN  = peak amplitude of tap 1 minus tap N (percentage points; + = shrinking);
               with fewer than N taps, tap 1 minus 0, as in the published data."""
    t_ms = np.asarray(t_ms, float)
    dist = fill_short_gaps(t_ms, np.asarray(dist, float))
    ok = ~np.isnan(dist)
    if ok.sum() < 20:
        return None
    t_s = t_ms[ok] / 1000.0
    grid = np.arange(t_s[0], t_s[-1], 1 / FS)
    x = np.interp(grid, t_s, dist[ok])
    capture_fps = fps_measured or (len(t_ms) - 1) / max((t_ms[-1] - t_ms[0]) / 1000, 1e-6)
    if len(x) > 30:
        b, a = butter(4, min(LOWPASS_HZ, 0.4 * capture_fps) / (FS / 2))
        x = filtfilt(b, a, x)
    if x.max() <= 0:
        return None
    k = 100 * x / x.max()
    peaks, _ = find_peaks(k, prominence=KAS_PROMINENCE, distance=int(MIN_TAP_GAP_S * FS))
    amps = k[peaks]
    out = {'count': int(len(peaks)),
           'duration_s': round(float(grid[-1] - grid[0]), 2),
           'mean': round(float(amps.mean()), 2) if len(amps) else None,
           'std': round(float(amps.std()), 2) if len(amps) else None}
    for n in (5, 7, 10):
        # a tap that never happened counts as size 0 (the published data's convention)
        out[f'diff{n}'] = round(float(amps[0] - (amps[n - 1] if len(amps) >= n else 0.0)), 2) if len(amps) else None
    return out


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
    d, dist, theta, detected_hand = extract_aperture(frames, t_ms)
    result = tap_features(t_ms, d, meta.get('fps_measured'))
    result['kasemsap'] = kasemsap_features(t_ms, dist, meta.get('fps_measured'))
    if meta.get('hand') in ('right', 'left') and result['kasemsap']:
        from tapping_reference import hand_comparison
        result['comparison'] = hand_comparison(meta['hand'], result['kasemsap'])
    try:                                    # MDS-UPDRS 3.4 severity band (Islam et al. 2023)
        from tapping_severity import estimate
        result['severity'] = estimate(t_ms, theta) if result.get('valid') else None
    except Exception as e:                  # never lose the main result over the extra band
        print(f'[tapping] severity failed: {e!r}')
        result['severity'] = None
    result.update({
        'hand': meta.get('hand'),
        'detected_hand': detected_hand,
        'n_frames': len(frames),
        'drops': meta.get('drops'),
        'source': meta.get('camera') or meta.get('source'),
        'analysis_s': round(time.perf_counter() - started, 2),
        'status': 'scored',
    })
    if meta.get('drops'):
        result.setdefault('warnings', []).append(f"{meta['drops']} dropped camera frames.")
    return result
