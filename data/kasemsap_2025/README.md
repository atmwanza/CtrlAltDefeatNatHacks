# Finger-tapping reference data: Kasemsap et al. 2025

`Parkinson_data.xlsx` is the reference group for DrawDx's finger-tapping module. We redistribute it unchanged under its CC BY 4.0 licence.

## Source and credit
- **Dataset:** Kasemsap N. *Parkinson_data.xlsx*, figshare, version 3, published May 7, 2025.
  - DOI: [10.6084/m9.figshare.28883489.v3](https://doi.org/10.6084/m9.figshare.28883489.v3)
  - Page: <https://figshare.com/articles/dataset/Parkinson_data_csv/28883489>
  - Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
  - MD5 `d1a9fd5eb88b5b937570ccb9ca32f7bc` (matches figshare's checksum)
- **Paper:** Kasemsap N. et al. *Screening for Parkinson's disease using "computer vision"*. PLOS ONE 20(8): e0330373 (2025). <https://doi.org/10.1371/journal.pone.0330373>

## What's in it
100 people, one row each: **47 healthy controls** (`bradykinesia1 = 0`) and **53 people with Parkinson's disease** (`bradykinesia1 = 1`), diagnosed by a neurologist using the Movement Disorder Society criteria.

Recording protocol:
- smartphone, 30 fps, 10 s per hand, camera about 0.5–1 m from the hand
- instruction: "as quickly and wide open as possible"
- thumb and index fingertips tracked with MediaPipe
- ages: controls 59.5 ± 11.7, Parkinson's 60.6 ± 10.0

| Column | Meaning |
|---|---|
| `rp_count`, `lp_count` | taps in the 10-s window (right / left hand) |
| `rp_mean`, `lp_mean` | mean tap peak amplitude, % of that hand's maximum thumb–index distance |
| `rp_std`, `lp_std` | SD of the tap peak amplitudes, % of maximum |
| `rp_diff5/7/10`, `lp_diff5/7/10` | peak amplitude of tap 1 minus tap 5 / 7 / 10, in percentage points (positive = taps shrinking) |
| `tap_diff` | \|right − left\| tap count |

## How DrawDx uses it
`tools/build_tapping_reference.py` reads this file and writes `01/tapping_reference.json`:
- **group averages** for the tablet's comparison bars
- **a score:** L2 logistic regression on the worse hand's amplitude mean, amplitude SD and tap 1→10 drop

On held-out people (leave-one-person-out) the score reaches AUC 0.818, sensitivity 0.81, specificity 0.72.

**Tap counts are shown but never scored,** because they depend on age and recording setup.

DrawDx's own tapping features are computed the same way as the paper's (see `kasemsap_features()` in `01/tapping_analysis.py`). The result is a screening comparison, not a diagnosis.
