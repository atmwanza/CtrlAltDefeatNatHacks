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
- **a score for each hand:** L2 logistic regression on that hand's tap count (speed), mean amplitude, amplitude SD and tap 1→10 drop. A person's result is their **worse hand**.
- **bands from the healthy group's held-out scores:** under 50 is typical (the model's decision point), 75 or more is elevated (92% of held-out healthy people score below 75)

On held-out people (leave-one-person-out, both hands held out), the score reaches **AUC 0.912, sensitivity 0.92, specificity 0.75**.

**Why speed is scored.** A first version left tap count out, on the worry that it depends on age and setup. Our team check on the Pi camera (7 healthy people, 13 recordings) showed that version's score followed tapping speed (r = 0.74). Our testers' tap counts matched this study's healthy group (23.9 vs 24.4, worse hand), so speed was added: held-out AUC went from 0.818 to 0.912.

**Fewer than N taps.** In this data, when a hand made fewer than N taps, `diffN` is tap 1 minus 0 (checked on all 9 such hands). DrawDx computes it the same way, so slow tapping still gets a result.

DrawDx's own tapping features are computed the same way as the paper's (see `kasemsap_features()` in `01/tapping_analysis.py`). The result is a screening comparison, not a diagnosis.
