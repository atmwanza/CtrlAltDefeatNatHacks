"""Build the finger-tapping severity model from Islam et al. 2023 (npj Digital Medicine).

    python tools/build_tapping_severity.py        -> writes 01/tapping_severity.json

Data: features of 489 home-webcam finger-tapping videos (295 people), each rated by
neurologists on MDS-UPDRS 3.4 (0-4; 'Rating' = expert consensus), from
https://github.com/ROC-HCI/finger-tapping-severity (MIT licence). The columns we use are
kept in data/islam_2023/ (with the licence); if missing, they're downloaded again.

Model: L2 logistic regression (lambda=1, same as the tapping reference), rating 2+ ("mild
or worse") vs 0-1, on the speed interquartile range (deg/s) and amplitude median (deg) of
the wrist angle between thumb tip and index tip. Three features were chosen before
validation (ROLE_ADAM.md, task A4); speed median was dropped because it overlaps with the
speed range (r = 0.76) and got a wrong-sign weight. Without it, held-out AUC is unchanged
(0.787 -> 0.788) and both weights point the clinical way (faster, wider = milder). Validated leaving one person out (a person's
left- and right-hand videos are held out together). 01/tapping_severity.py computes the
same features from our clips.

Their diagnosis labels may be self-reported and don't separate Parkinson's from controls
(AUC ~0.5), so this estimates the severity rating, never a diagnosis.
"""
import csv
import io
import json
import re
import urllib.request
from pathlib import Path

import numpy as np

from build_tapping_reference import auc, fit_logistic, predict

URL = ('https://raw.githubusercontent.com/ROC-HCI/finger-tapping-severity/main/'
       'fingertapping_features_severity_diagnosis_June13_2023.csv')
ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / 'data' / 'islam_2023' / 'islam_2023_features.csv'
OUT = ROOT / '01' / 'tapping_severity.json'

INPUTS = ['speed_quartile_range_denoised', 'amplitude_median_denoised']
KEEP = ['filename', 'hand', 'Rating', 'diagnosed', 'age', 'speed_median_denoised', 'speed_quartile_range_denoised',
        'amplitude_median_denoised', 'frequency_median_denoised', 'num_peaks_denoised']
THRESHOLD = 0.5


def load_rows():
    if not LOCAL.exists():
        text = urllib.request.urlopen(URL, timeout=60).read().decode('utf-8', 'replace')
        rows = list(csv.DictReader(io.StringIO(text)))
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=KEEP)
            w.writeheader()
            w.writerows({k: r[k] for k in KEEP} for r in rows)
    return list(csv.DictReader(LOCAL.open(newline='')))


def main():
    rows = load_rows()
    X = np.array([[float(r[k]) for k in INPUTS] for r in rows])
    rating = np.array([float(r['Rating']) for r in rows])
    y = (rating >= 2).astype(float)
    person = np.array([re.sub(r'-task2-(left|right).*', '', r['filename']) for r in rows])
    assert len(rows) == 489 and len(set(person)) == 295, (len(rows), len(set(person)))

    held = np.zeros(len(y))
    for p in np.unique(person):
        m = person != p
        mu, sd = X[m].mean(0), X[m].std(0)
        w = fit_logistic((X[m] - mu) / sd, y[m])
        held[~m] = predict(w, (X[~m] - mu) / sd)
    pred = held >= THRESHOLD
    validation = {
        'method': 'leave-one-person-out (both hands held out)',
        'target': 'MDS-UPDRS 3.4 rating 2+ vs 0-1 (neurologist consensus)',
        'auc': round(auc(held, y), 3),
        'sensitivity': round(float(pred[y == 1].mean()), 3),
        'specificity': round(float((~pred[y == 0]).mean()), 3),
        'threshold': THRESHOLD,
        'n_videos': len(rows), 'n_people': int(len(set(person))),
        'n_rating_2plus': int(y.sum()),
    }
    mu, sd = X.mean(0), X.std(0)
    w = fit_logistic((X - mu) / sd, y)
    by_rating = {str(int(k)): {f: round(float(np.median(X[rating == k, i])), 1) for i, f in enumerate(INPUTS)}
                 | {'n': int((rating == k).sum())} for k in np.unique(rating)}
    out = {
        'source': {
            'citation': 'Islam MS, Rahman W, Abdelkader A, et al. Using AI to measure Parkinson\'s disease '
                        'severity at home. npj Digital Medicine 6, 156 (2023)',
            'doi': 'https://doi.org/10.1038/s41746-023-00905-9',
            'data': 'https://github.com/ROC-HCI/finger-tapping-severity (MIT licence)',
            'short': 'benchmarked against 489 neurologist-rated home videos (Islam et al. 2023)',
        },
        'model': {
            'type': 'L2 logistic regression (lambda=1) on standardised features',
            'inputs': INPUTS,
            'units': {'speed_quartile_range_denoised': 'deg/s', 'amplitude_median_denoised': 'deg'},
            'mean': [round(float(v), 6) for v in mu],
            'sd': [round(float(v), 6) for v in sd],
            'intercept': round(float(w[0]), 6),
            'coef': [round(float(v), 6) for v in w[1:]],
            'threshold': THRESHOLD,
            'validation': validation,
        },
        'median_by_rating': by_rating,
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(f'wrote {OUT}')
    print(f"{len(rows)} videos / {len(set(person))} people; rating 2+: {int(y.sum())}; held-out AUC "
          f"{validation['auc']}, sensitivity {validation['sensitivity']}, specificity {validation['specificity']}")
    print('coefficients', dict(zip(INPUTS, np.round(w[1:], 3))))
    for k, v in by_rating.items():
        print(f'  rating {k}: {v}')


if __name__ == '__main__':
    main()
