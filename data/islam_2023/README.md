# Finger-tapping severity data: Islam et al. 2023

`islam_2023_features.csv` is the reference for DrawDx's finger-tapping **severity band**. It's a subset of the columns of the authors' feature file, redistributed under its MIT licence (see `LICENSE`, copyright 2025 ROC-HCI).

## Source and credit
- **Paper:** Islam MS, Rahman W, Abdelkader A, et al. *Using AI to measure Parkinson's disease severity at home.* npj Digital Medicine 6, 156 (2023). <https://doi.org/10.1038/s41746-023-00905-9>
- **Data and code:** <https://github.com/ROC-HCI/finger-tapping-severity>
  - file: `fingertapping_features_severity_diagnosis_June13_2023.csv`
  - licence: MIT

## What's in it
**489 finger-tapping videos from 295 people,** recorded at home on a webcam. Each video was rated by neurologists on MDS-UPDRS 3.4 (finger tapping, 0–4). `Rating` is the expert consensus:

| Rating | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| Videos | 108 | 181 | 141 | 54 | 5 |

| Column | Meaning |
|---|---|
| `filename` | video name; the person is the part before `-task2-left/right` |
| `hand`, `age`, `diagnosed` | as published; `diagnosed` may be self-reported |
| `Rating` | MDS-UPDRS 3.4 expert consensus, 0–4 |
| `speed_median_denoised`, `speed_quartile_range_denoised` | median and IQR of how fast the wrist angle changes, deg/s |
| `amplitude_median_denoised` | median wrist angle at tap peaks, deg |
| `frequency_median_denoised`, `num_peaks_denoised` | for context; not used |

The wrist angle is the angle at the wrist between the thumb tip and the index fingertip.

## How DrawDx uses it
`tools/build_tapping_severity.py` fits a logistic regression for **rating 2+ ("mild or worse") vs 0–1**, using the speed IQR and the amplitude median. It writes `01/tapping_severity.json`.

**Validation:** leaving one person out (both hands held out together), AUC **0.788**, sensitivity 0.64, specificity 0.79.

`01/tapping_severity.py` ports the authors' feature code, so our clips give the same measurements:
- their peak detection and the "fingers must close below 10°" rule
- their speed, a frame-to-frame difference at 30 Hz
- only the first 10 taps of our 10-second trial, because their videos are about 10 taps long

**Limits:**
- These features **don't separate Parkinson's from controls** in this data (AUC about 0.5). They track how a neurologist would rate the tapping, so DrawDx shows a **severity band, never a diagnosis**.
- Their videos are home webcams filmed from many angles; ours come from a fixed camera.
