"""Build the finger-tapping reference from Kasemsap et al. 2025 (PLOS ONE).

    python tools/build_tapping_reference.py        -> writes 01/tapping_reference.json

Data: "Parkinson_data.xlsx", figshare 10.6084/m9.figshare.28883489, CC BY 4.0.
100 people (47 healthy controls, 53 people with Parkinson's diagnosed by a neurologist
using MDS criteria), 10-s smartphone videos at 30 fps, MediaPipe. Per hand: tap count,
mean peak amplitude and its SD (amplitude = thumb-index distance as % of that hand's
maximum in the video), and the drop from tap 1 to tap 5/7/10 (percentage points).

The spreadsheet is in the repo at data/kasemsap_2025/ (CC BY 4.0, unchanged, with a
README crediting the authors); if it's missing, it's downloaded from figshare.

Score: L2-regularised logistic regression on the 3 self-normalised features, each taken
from the person's WORSE hand (smaller mean amplitude, larger amplitude SD, larger
tap 1->10 drop). Parkinson's usually starts on one side, and this keeps every weight
interpretable (with right and left as 6 separate inputs, AUC was 0.829 but the two
hands' collinearity gave some weights the wrong sign; averaging the hands gave 0.812).
Tap count is left out on purpose: it depends on age and on the recording setup (our
young healthy testers tap ~4 Hz vs 2.5 Hz for the reference's ~60-year-old controls).
Validated with leave-one-person-out on the 100 people.
"""
import io
import json
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


def load_raw():
    if LOCAL.exists():
        return LOCAL.read_bytes()
    return urllib.request.urlopen(URL, timeout=60).read()
# worse hand per feature: (name, right column, left column, which is worse)
SCORE_FEATURES = [('worse_mean', 'rp_mean', 'lp_mean', 'min'),
                  ('worse_std', 'rp_std', 'lp_std', 'max'),
                  ('worse_diff10', 'rp_diff10', 'lp_diff10', 'max')]
L2 = 1.0          # ridge strength on standardised features (fixed before validation)


def worse_hand(right, left):
    """The score inputs from one person's right/left values: {'mean':..,'std':..,'diff10':..}."""
    pick = {'min': min, 'max': max}
    return [pick[how](right[r[3:]], left[l[3:]]) for _, r, l, how in SCORE_FEATURES]


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

    # leave-one-person-out validation of the score
    X = np.array([worse_hand({'mean': r['rp_mean'], 'std': r['rp_std'], 'diff10': r['rp_diff10']},
                             {'mean': r['lp_mean'], 'std': r['lp_std'], 'diff10': r['lp_diff10']}) for r in rows])
    held_out = np.zeros(len(y))
    for i in range(len(y)):
        m = np.ones(len(y), bool)
        m[i] = False
        mu, sd = X[m].mean(0), X[m].std(0)
        w = fit_logistic((X[m] - mu) / sd, y[m])
        held_out[i] = predict(w, ((X[i] - mu) / sd)[None])[0]
    pred = held_out >= 0.5
    validation = {
        'method': 'leave-one-person-out',
        'auc': round(auc(held_out, y), 3),
        'sensitivity': round(float(pred[y == 1].mean()), 3),
        'specificity': round(float((~pred[y == 0]).mean()), 3),
        'threshold': 0.5,
    }

    # final model on everyone
    mu, sd = X.mean(0), X.std(0)
    w = fit_logistic((X - mu) / sd, y)

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
                'diffN': 'peak amplitude of tap 1 minus tap N, percentage points (positive = shrinking)',
                'tap_diff': '|right - left| tap count',
            },
        },
        'features': features,
        'score': {
            'model': 'L2 logistic regression (lambda=%.1f) on standardised features, worse hand per feature' % L2,
            'inputs': [name for name, *_ in SCORE_FEATURES],
            'input_definitions': {name: f'{how}({r}, {l})' for name, r, l, how in SCORE_FEATURES},
            'mean': [round(float(v), 6) for v in mu],
            'sd': [round(float(v), 6) for v in sd],
            'intercept': round(float(w[0]), 6),
            'coef': [round(float(v), 6) for v in w[1:]],
            'validation': validation,
            'not_scored': ['rp_count', 'lp_count', 'tap_diff'],
            'why_not_scored': 'tap counts depend on age and recording setup',
        },
    }
    OUT.write_text(json.dumps(ref, indent=1))
    print(f'wrote {OUT}')
    print(f'healthy {n_hc} / Parkinson\'s {n_pd}; held-out AUC {validation["auc"]}, '
          f'sensitivity {validation["sensitivity"]}, specificity {validation["specificity"]}')
    for k, s in features.items():
        print(f'  {k:10s} healthy {s["hc_mean"]:6.1f}  PD {s["pd_mean"]:6.1f}  single-feature AUC {s["auc_single"]:.2f}')


if __name__ == '__main__':
    main()
