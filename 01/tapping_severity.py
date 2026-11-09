"""Finger-tapping severity band, benchmarked against Islam et al. 2023.

Islam MS, Rahman W, Abdelkader A, et al. Using AI to measure Parkinson's disease severity
at home. npj Digital Medicine 6, 156 (2023). https://doi.org/10.1038/s41746-023-00905-9
Data and code: https://github.com/ROC-HCI/finger-tapping-severity (MIT licence).

489 home-webcam videos (295 people), each rated by neurologists on MDS-UPDRS 3.4
(finger tapping, 0-4). Their signal is the angle at the wrist between the thumb tip and
the index fingertip, in degrees. This module ports their feature code (feature_extraction.py:
denoise -> longest valid run, custom_peaks/peak_detection, speed and amplitude statistics)
so our clips give the same numbers, then applies the model in tapping_severity.json
(built by tools/build_tapping_severity.py): "Normal-slight (0-1)" vs "Mild or worse (2+)".

Differences from their pipeline, on purpose:
- Their videos are ~10 taps ("tap 10 times"); ours run 10 s (~25 taps). We use the
  stretch up to the 11th tap peak, so fatigue later in our longer trial isn't counted.
- Their frame rate was the webcam's (~30 fps); we resample our real timestamps to 30 Hz,
  because their speed is a frame-to-frame difference and depends on the frame rate.
"""
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

FS = 30.0                 # Hz, their webcams' rate
MIN_PERIOD_S = 0.15       # their peak_detection: minimum time between peaks
BOTTOM_MAX_DEG = 10.0     # their peak_detection: fingers must close below 10 degrees between taps
TASK_TAPS = 10            # MDS-UPDRS 3.4: "tap 10 times"
MAX_GAP_MS = 100          # bridge detection dropouts up to this long (as our other features)

_MODEL_PATH = Path(__file__).parent / 'tapping_severity.json'
MODEL = json.loads(_MODEL_PATH.read_text()) if _MODEL_PATH.exists() else None


def wrist_angle(wrist, thumb, index):
    """Angle at the wrist between thumb tip and index tip, degrees (their formula, pixel x/y)."""
    wt, wi = thumb - wrist, index - wrist
    n = np.linalg.norm(wt) * np.linalg.norm(wi)
    if n <= 0:
        return np.nan
    return math.degrees(math.acos(min(float(np.dot(wt, wi) / n), 1.0)))


def _longest_valid_run(t_ms, theta):
    """Bridge short gaps, then keep the longest stretch with a hand (their
    interpolation_and_denoise)."""
    theta = np.asarray(theta, float).copy()
    t_ms = np.asarray(t_ms, float)
    ok = ~np.isnan(theta)
    i, n = 0, len(theta)
    while i < n:                                   # bridge short NaN runs
        if ok[i]:
            i += 1
            continue
        j = i
        while j < n and not ok[j]:
            j += 1
        if 0 < i and j < n and t_ms[j] - t_ms[i - 1] <= MAX_GAP_MS:
            theta[i:j] = np.interp(t_ms[i:j], [t_ms[i - 1], t_ms[j]], [theta[i - 1], theta[j]])
        i = j
    ok = ~np.isnan(theta)
    best, start = (0, 0), None
    for k in range(n + 1):
        if k < n and ok[k]:
            start = k if start is None else start
        elif start is not None:
            if k - start > best[1] - best[0]:
                best = (start, k)
            start = None
    return t_ms[best[0]:best[1]], theta[best[0]:best[1]]


def _custom_peaks(D, distance):
    """Their custom_peaks: peaks at least `distance` frames apart and at least half as high as
    the 80th percentile of the middle half of the first-pass peaks."""
    peaks, _ = find_peaks(D, distance=int(distance))
    n = len(peaks)
    if n == 0:
        return peaks
    middle = D[peaks[int(np.floor((n - 1) / 4)):int(np.floor(3 * (n - 1) / 4))]]
    if len(middle) == 0:
        middle = D[peaks]
    height = np.floor(np.percentile(middle, 80) / 2)
    peaks, _ = find_peaks(D, distance=int(distance), height=int(height))
    return peaks


def _peak_detection(D):
    """Their peak_detection: keep a peak only if the fingers closed (below 10 degrees)
    since the previous candidate peak."""
    peaks = _custom_peaks(D, distance=int(MIN_PERIOD_S * FS))
    if len(peaks) == 0:
        return np.array([], int)
    kept = [peaks[0]]
    for a, b in zip(peaks[:-1], peaks[1:]):
        if D[a:b].min() < BOTTOM_MAX_DEG:
            kept.append(b)
    return np.array(kept, int)


def islam_features(t_ms, theta):
    """Speed median and IQR (deg/s) and amplitude median (deg) over the first 10 taps.
    Returns None if there's no usable signal."""
    t, th = _longest_valid_run(t_ms, theta)
    if len(t) < 20 or (t[-1] - t[0]) < 1000:
        return None
    grid = np.arange(t[0], t[-1], 1000.0 / FS)
    D = np.interp(grid, t, th)
    peaks = _peak_detection(D)
    if len(peaks) < 2:
        return None
    if len(peaks) > TASK_TAPS:                      # like their ~10-tap videos
        D = D[:peaks[TASK_TAPS] + 1]
        peaks = peaks[:TASK_TAPS + 1]
    speed = np.abs(np.diff(D)) * FS                 # deg per frame -> deg per second
    q75, q25 = np.percentile(speed, [75, 25])
    return {
        'speed_median_denoised': round(float(np.median(speed)), 2),
        'speed_quartile_range_denoised': round(float(q75 - q25), 2),
        'amplitude_median_denoised': round(float(np.median(D[peaks])), 2),
        'n_taps_used': int(len(peaks)),
        'seconds_used': round(len(D) / FS, 2),
    }


def estimate(t_ms, theta):
    """-> {'band', 'label', 'probability', 'features', 'validation', 'source'} or None."""
    if MODEL is None:
        return None
    f = islam_features(t_ms, theta)
    if f is None:
        return None
    m = MODEL['model']
    z = [(f[k] - mu) / sd for k, mu, sd in zip(m['inputs'], m['mean'], m['sd'])]
    p = 1 / (1 + math.exp(-(m['intercept'] + sum(c * zi for c, zi in zip(m['coef'], z)))))
    mild = p >= m['threshold']
    return {
        'band': '2+' if mild else '0-1',
        'label': 'Mild or worse (2+)' if mild else 'Normal to slight (0-1)',
        'probability': round(p, 3),
        'features': f,
        'validation': m['validation'],
        'source': MODEL['source']['short'],
    }
