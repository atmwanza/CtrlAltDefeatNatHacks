"""
score.py - compares one spiral's features with a BASELINE group and produces
the JSON the results page shows.

IMPORTANT: this is NOT a diagnosis and NOT a probability of having Parkinson's.
It measures how far a drawing deviates from a baseline group, in the direction
that the literature associates with slower, less smooth, more hesitant,
less accurate drawing. The baseline is whatever group you build it from
(teammates for the demo, or features from a public dataset).

Usage:
  python score.py baseline healthy1.csv healthy2.csv ... > baseline.json
  python score.py score user.csv baseline.json [template_turns template_rmax]
"""
import json
import sys
import numpy as np
from features import features_from_csv

# +1: higher value = more "PD-associated" direction;  -1: lower value is.
# These directions are assumptions from the papers - have Aayan verify them.
DIRECTION = {
    "mean_angular_velocity": -1,   # slower drawing
    "normalized_jerk": +1,         # less smooth
    "pause_fraction": +1,          # more hesitation
    "error_distance_norm": +1,     # further from ideal spiral
    "expansion_dev": +1,           # |expansion_ratio - 1|
    "hypometria_deficit": +1,      # 1 - drawn/template size (micrographia-like)
    "tremor_band_fraction": +1,    # more 4-12 Hz wobble (exploratory)
}
# Smallest believable spread, so a tiny baseline SD can't create huge z-scores.
MIN_SD = {
    "mean_angular_velocity": 0.15, "normalized_jerk": 5.0, "pause_fraction": 0.03,
    "error_distance_norm": 0.01, "expansion_dev": 0.05, "hypometria_deficit": 0.05,
    "tremor_band_fraction": 0.05,
}
DISCLAIMER = ("Screening feasibility prototype. Not a diagnosis and not a probability "
              "of having Parkinson's disease. Compared only with a small baseline group "
              "recorded on different hardware. Please discuss any concerns with a clinician.")


def scoring_features(f):
    """Pick/derive the features that go into the score."""
    out = {
        "mean_angular_velocity": f["mean_angular_velocity"],
        "normalized_jerk": f["normalized_jerk"],
        "pause_fraction": f["pause_fraction"],
        "error_distance_norm": f["error_distance_norm"],
        "expansion_dev": abs(f["expansion_ratio"] - 1.0),
    }
    if f.get("hypometria_ratio") is not None:
        out["hypometria_deficit"] = max(0.0, 1.0 - f["hypometria_ratio"])
    if f.get("tremor_band_fraction") is not None:
        out["tremor_band_fraction"] = f["tremor_band_fraction"]
    return out


def build_baseline(feature_dicts):
    rows = [scoring_features(f) for f in feature_dicts]
    base = {}
    for name in rows[0]:
        vals = np.array([r[name] for r in rows if name in r])
        base[name] = {"mean": float(vals.mean()), "sd": float(vals.std(ddof=1)), "n": int(len(vals))}
    return base


def score(f, baseline):
    feats = scoring_features(f)
    zs = {}
    for name, value in feats.items():
        if name not in baseline:
            continue
        sd = max(baseline[name]["sd"], MIN_SD[name])
        z = (value - baseline[name]["mean"]) / sd
        zs[name] = float(np.clip(DIRECTION[name] * z, -3, 3))   # + = worse than baseline

    def index(names):
        m = np.mean([zs[n] for n in names])
        return float(np.clip(m / 3.0, 0.0, 1.0))                # 0 = at/better than baseline, 1 = >=3 SD worse

    names = list(zs)
    idx = index(names)
    loo = [index([n for n in names if n != drop]) for drop in names] if len(names) > 1 else [idx]
    if idx < 0.15:
        label = "Within the range of the baseline group"
    elif idx < 0.4:
        label = "Somewhat different from the baseline group"
    else:
        label = "Clearly different from the baseline group"
    ranked = sorted(zs.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "deviation_index": round(idx, 3),
        "range": [round(min(loo), 3), round(max(loo), 3)],
        "label": label,
        "top_features": [{"feature": n, "z": round(z, 2)} for n, z in ranked[:3]],
        "flags": [{"feature": n, "z": round(z, 2)} for n, z in ranked if z >= 2],
        "all_z": {n: round(z, 2) for n, z in zs.items()},
        "quality": f["quality"],
        "disclaimer": DISCLAIMER,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    if sys.argv[1] == "baseline":
        print(json.dumps(build_baseline([features_from_csv(p) for p in sys.argv[2:]]), indent=2))
    elif sys.argv[1] == "score":
        base = json.load(open(sys.argv[3]))
        tt = float(sys.argv[4]) if len(sys.argv) > 5 else None
        tr = float(sys.argv[5]) if len(sys.argv) > 5 else None
        print(json.dumps(score(features_from_csv(sys.argv[2], tt, tr), base), indent=2))
    else:
        sys.exit(__doc__)
