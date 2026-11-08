"""Build the finger-tapping reference from Kasemsap et al. 2025 (PLOS ONE).

    python tools/build_tapping_reference.py        -> writes 01/tapping_reference.json

Data: "Parkinson_data.xlsx", figshare 10.6084/m9.figshare.28883489, CC BY 4.0.
100 people (47 healthy controls, 53 people with Parkinson's diagnosed by a neurologist
using MDS criteria), 10-s smartphone videos at 30 fps, MediaPipe. Per hand: tap count,
mean peak amplitude and its SD (amplitude = thumb-index distance as % of that hand's
maximum in the video), and the drop from tap 1 to tap 5/7/10 (percentage points).
When a hand made fewer than N taps, the published diffN is tap 1 minus 0 (checked on all
9 such hands); tapping_analysis.kasemsap_features() does the same.

The spreadsheet is in the repo at data/kasemsap_2025/ (CC BY 4.0, unchanged, with a
README crediting the authors); if it's missing, it's downloaded from figshare.

Score (per hand): L2-regularised logistic regression on one hand's 4 features: tap count
(speed), mean amplitude, amplitude SD and the tap 1->10 drop. Each hand of each person is a
sample labelled with that person's diagnosis; a person's score is their WORSE hand, as
Parkinson's usually starts on one side and MDS-UPDRS rates each hand separately.
Validated with leave-one-person-out (both of a person's hands held out together).

History: the first version used only the 3 amplitude features (tap count left out, on the
worry that it depends on age and setup). Our team check on the Pi camera (7 healthy
people, 13 recordings) showed that score followed tapping speed (r = 0.74): fast tappers
make smaller, less even taps. Our team's tap counts matched the reference's healthy group
(23.9 vs 24.4 taps, worse hand), so the worry was unfounded; adding speed raised held-out
AUC from 0.818 to 0.912. Two speed-aware designs (worse hand per feature, and per-hand
scores) were compared on this data only and tied at 0.912; the per-hand design was
chosen, as fixed beforehand for a tie, because it never mixes measures from two hands.

Bands (from held-out scores of the reference's healthy people, not from our testers):
typical below the model's decision point (50); elevated from the score 90% of held-out
healthy people fall below (rounded up to a multiple of 5).
"""
import io
import json
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

URL = 'https://ndownloader.figshare.com/files/54255155'
ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / 'data' / 'kasemsap_2025' / 'Parkinson_data.xlsx'
OUT = ROOT / '01' / 'tapping_reference.json'

SCORE_FEATURES = ['count', 'mean', 'std', 'diff10']   # one hand's features
L2 = 1.0          # ridge strength on standardised features (fixed before validation)
THRESHOLD = 0.5   # model decision point


def load_raw():
    if LOCAL.exists():
        return LOCAL.read_bytes()
    return urllib.request.urlopen(URL, timeout=60).read()


def read_xlsx(raw):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        shared = [''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', ns)]
    rows = []
    for r in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).iter('{%s}row' % ns['m']):
        vals = {}
        for c in r.findall('m:c', ns):
            col = re.match(r'[A-Z]+', c.get('r')).group()
            v = c.find('m:v', ns)
            if v is not None:
                vals[col] = shared[int(v.text)] if c.get('t') == 's' else v.text
        rows.append(vals)
    header = rows[0]
    return [{header[c]: float(r[c]) for c in header if c in r} for r in rows[1:]]


def fit_logistic(X, y, l2=L2, iters=50):
    """Newton/IRLS with an L2 penalty (intercept unpenalised). X already standardised."""
    Xb = np.c_[np.ones(len(X)), X]
    w = np.zeros(Xb.shape[1])
    pen = np.eye(Xb.shape[1]) * l2
    pen[0, 0] = 0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        grad = Xb.T @ (p - y) + pen @ w
        hess = Xb.T @ (Xb * (p * (1 - p))[:, None]) + pen
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def predict(w, X):
    return 1 / (1 + np.exp(-(w[0] + X @ w[1:])))


def auc(scores, y):
    pos, neg = scores[y == 1], scores[y == 0]
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg]))


def hand_matrix(rows):
    """Both hands of every person: X (2n x 4), person id (2n)."""
    X = np.array([[r[f'rp_{k}'] for k in SCORE_FEATURES] for r in rows] +
                 [[r[f'lp_{k}'] for k in SCORE_FEATURES] for r in rows])
    pid = np.r_[np.arange(len(rows)), np.arange(len(rows))]
    return X, pid


def main():
    rows = read_xlsx(load_raw())
    y = np.array([r['bradykinesia1'] for r in rows])          # 1 = Parkinson's, 0 = healthy
    n_pd, n_hc = int(y.sum()), int((y == 0).sum())
    assert (n_hc, n_pd) == (47, 53), f'unexpected group sizes {n_hc}/{n_pd}'

    # group statistics for every published feature (bars on the tablet)
    features = {}
    for k in ['rp_count', 'lp_count', 'rp_mean', 'lp_mean', 'rp_std', 'lp_std',
              'rp_diff5', 'lp_diff5', 'rp_diff7', 'lp_diff7', 'rp_diff10', 'lp_diff10', 'tap_diff']:
        v = np.array([r[k] for r in rows])
        hc, pd = v[y == 0], v[y == 1]
        features[k] = {'hc_mean': round(float(hc.mean()), 2), 'hc_sd': round(float(hc.std(ddof=1)), 2),
                       'pd_mean': round(float(pd.mean()), 2), 'pd_sd': round(float(pd.std(ddof=1)), 2),
                       'auc_single': round(auc(v if pd.mean() > hc.mean() else -v, y), 3)}

    # leave-one-person-out: hold out both hands, score = worse hand
    X, pid = hand_matrix(rows)
    yh = np.r_[y, y]
    held_out = np.zeros(len(y))
    for i in range(len(y)):
        m = pid != i
        mu, sd = X[m].mean(0), X[m].std(0)
        w = fit_logistic((X[m] - mu) / sd, yh[m])
        held_out[i] = predict(w, (X[pid == i] - mu) / sd).max()
    pred = held_out >= THRESHOLD
    validation = {
        'method': 'leave-one-person-out (both hands held out); score = worse hand',
        'auc': round(auc(held_out, y), 3),
        'sensitivity': round(float(pred[y == 1].mean()), 3),
        'specificity': round(float((~pred[y == 0]).mean()), 3),
        'threshold': THRESHOLD,
    }

    # bands from the held-out scores of the healthy group
    healthy = 100 * held_out[y == 0]
    pd_scores = 100 * held_out[y == 1]
    typical_below = int(round(THRESHOLD * 100))
    elevated_from = int(5 * math.ceil(np.percentile(healthy, 90) / 5))
    bands = {
        'typical_below': typical_below,
        'elevated_from': elevated_from,
        'how': 'typical: below the model decision point; elevated: the score 90% of held-out healthy '
               'people fall below (rounded up to a multiple of 5). From the reference only.',
        'healthy_typical_share': round(float(np.mean(healthy < typical_below)), 3),
        'healthy_below_elevated_share': round(float(np.mean(healthy < elevated_from)), 3),
        'pd_elevated_share': round(float(np.mean(pd_scores >= elevated_from)), 3),
    }

    # final model on everyone
    mu, sd = X.mean(0), X.std(0)
    w = fit_logistic((X - mu) / sd, yh)

    ref = {
        'source': {
            'citation': 'Kasemsap N et al. Screening for Parkinson\'s disease using "computer vision". '
                        'PLOS ONE 20(8): e0330373 (2025)',
            'data': 'figshare 10.6084/m9.figshare.28883489 (Parkinson_data.xlsx), CC BY 4.0',
            'n_healthy': n_hc, 'n_parkinsons': n_pd,
            'protocol': 'smartphone, 30 fps, 10 s per hand, "as quickly and wide open as possible", MediaPipe; '
                        'controls 59.5 +/- 11.7 y, PD 60.6 +/- 10.0 y; PD diagnosed by a neurologist (MDS criteria)',
            'definitions': {
                'count': 'taps in the 10-s window',
                'mean': 'mean peak amplitude, % of that hand\'s maximum thumb-index distance',
                'std': 'SD of peak amplitudes, % of maximum',
                'diffN': 'peak amplitude of tap 1 minus tap N, percentage points (positive = shrinking); '
                         'tap 1 minus 0 when the hand made fewer than N taps',
                'tap_diff': '|right - left| tap count',
            },
        },
        'features': features,
        'score': {
            'model': 'L2 logistic regression (lambda=%.1f) on one hand\'s standardised features; each hand '
                     'is a sample labelled with the person\'s diagnosis; a person\'s score is the worse hand' % L2,
            'per_hand': True,
            'inputs': SCORE_FEATURES,
            'mean': [round(float(v), 6) for v in mu],
            'sd': [round(float(v), 6) for v in sd],
            'intercept': round(float(w[0]), 6),
            'coef': [round(float(v), 6) for v in w[1:]],
            'validation': validation,
            'bands': bands,
            'not_scored': ['tap_diff'],
        },
    }
    OUT.write_text(json.dumps(ref, indent=1))
    print(f'wrote {OUT}')
    print(f'healthy {n_hc} / Parkinson\'s {n_pd}; held-out AUC {validation["auc"]}, '
          f'sensitivity {validation["sensitivity"]}, specificity {validation["specificity"]}')
    print(f'coefficients ({", ".join(SCORE_FEATURES)}): {np.round(w[1:], 3)}')
    print(f'bands: typical < {typical_below} ({bands["healthy_typical_share"]:.0%} of held-out healthy), '
          f'elevated >= {elevated_from} ({bands["healthy_below_elevated_share"]:.0%} of healthy below; '
          f'{bands["pd_elevated_share"]:.0%} of PD at or above)')
    for k, s in features.items():
        print(f'  {k:10s} healthy {s["hc_mean"]:6.1f}  PD {s["pd_mean"]:6.1f}  single-feature AUC {s["auc_single"]:.2f}')


if __name__ == '__main__':
    main()
