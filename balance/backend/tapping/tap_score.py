"""
tap_score.py - compares tapping trials: to a baseline group, between hands,
between repeat attempts, and to a person's own history.

NOT a diagnosis. Abnormal tapping has many causes (fatigue, medication,
keyboard, learning effects). Parkinson's diagnosis needs a clinical exam.

Usage:
  python tap_score.py baseline trial1.csv trial2.csv ... > tap_baseline.json
  python tap_score.py score    trial.csv tap_baseline.json
  python tap_score.py hands    left.csv right.csv [dominant: left|right]
  python tap_score.py retest   attempt1.csv attempt2.csv
  python tap_score.py self     current.csv previous1.csv [previous2.csv ...]
"""
import json
import sys
import numpy as np
from tap_features import features_from_csv, DEFINITIONS

# +1: higher = slower/less consistent direction; -1: lower is.  (Assumptions - verify.)
DIRECTION = {"ks20": -1, "at20_ms": +1, "log_is20": +1, "slowing_pct": -1}
MIN_SD = {"ks20": 5.0, "at20_ms": 10.0, "log_is20": 0.25, "slowing_pct": 5.0}
RETEST_FLAG_PCT = 15.0   # tunable data-quality heuristic
DISCLAIMER = ("Research prototype, not a diagnosis. Tapping speed and rhythm change with "
              "fatigue, medication, practice and equipment. Parkinson's disease is diagnosed "
              "by a clinician's examination, not by a tapping test. Compared with a small "
              "baseline group only.")


def scoring_features(f):
    out = {"ks20": f["ks20"], "at20_ms": f["at20_ms"]}
    if f.get("is20_ms2"):
        out["log_is20"] = float(np.log(f["is20_ms2"]))
    if f.get("slowing_pct") is not None:
        out["slowing_pct"] = f["slowing_pct"]
    return out


def build_baseline(trials):
    rows = [scoring_features(f) for f in trials if f["valid"]]
    if len(rows) < 3:
        raise ValueError("Need at least 3 VALID baseline trials (got %d)." % len(rows))
    base = {}
    for name in rows[0]:
        vals = np.array([r[name] for r in rows if name in r])
        base[name] = {"mean": float(vals.mean()), "sd": float(vals.std(ddof=1)), "n": int(len(vals))}
    return base


def score(f, baseline):
    if not f["valid"]:       # invalid recording is NOT the same as an unusual pattern
        return {"status": "invalid_trial", "reasons": f["reasons"],
                "message": "This recording failed quality checks, so it was not scored. Please repeat it.",
                "disclaimer": DISCLAIMER}
    zs = {}
    for name, value in scoring_features(f).items():
        if name in baseline:
            sd = max(baseline[name]["sd"], MIN_SD[name])
            z = (value - baseline[name]["mean"]) / sd
            zs[name] = float(np.clip(DIRECTION[name] * z, -3, 3))      # + = worse than baseline

    def index(names):
        return float(np.clip(np.mean([zs[n] for n in names]) / 3.0, 0.0, 1.0))

    names = list(zs)
    idx = index(names)
    loo = [index([n for n in names if n != d]) for d in names] if len(names) > 1 else [idx]
    label = ("Within the range of the baseline group" if idx < 0.15 else
             "Somewhat different from the baseline group" if idx < 0.4 else
             "Clearly different from the baseline group")
    ranked = sorted(zs.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "status": "scored",
        "deviation_index": round(idx, 3),
        "range": [round(min(loo), 3), round(max(loo), 3)],
        "label": label,
        "top_features": [{"feature": n, "z": round(z, 2)} for n, z in ranked[:3]],
        "flags": [{"feature": n, "z": round(z, 2)} for n, z in ranked if z >= 2],
        "measurements": {k: f[k] for k in ("ks20", "at20_ms", "is20_ms2", "slowing_pct")},
        "definitions": DEFINITIONS,
        "warnings": f["warnings"],
        "disclaimer": DISCLAIMER,
    }


def pct_diff(a, b):
    return abs(a - b) / ((a + b) / 2.0) * 100.0 if (a + b) else 0.0


def hands(left, right, dominant=None):
    out = {"dominant_hand": dominant, "note": "A slower non-dominant hand alone is not evidence of Parkinson's."}
    for k in ("ks20", "at20_ms"):
        out[k] = {"left": left[k], "right": right[k], "asymmetry_pct": round(pct_diff(left[k], right[k]), 1)}
    return out


def retest(a, b):
    out = {}
    for k in ("ks20", "at20_ms"):
        d = pct_diff(a[k], b[k])
        out[k] = {"attempt1": a[k], "attempt2": b[k], "diff_pct": round(d, 1), "consistent": d <= RETEST_FLAG_PCT}
    out["note"] = ("Large differences can be natural variability, learning, fatigue, or a technical "
                   "problem - check the data quality before reading anything into them.")
    return out


def self_compare(cur, prev_list):
    out = {}
    for k in ("ks20", "at20_ms"):
        ref = float(np.median([p[k] for p in prev_list]))
        out[k] = {"now": cur[k], "personal_median": ref, "change_pct": round((cur[k] - ref) / ref * 100.0, 1)}
    out["n_previous_sessions"] = len(prev_list)
    out["note"] = "Change relative to this person's own history, not to a population norm."
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    mode, args = sys.argv[1], sys.argv[2:]
    if mode == "baseline":
        print(json.dumps(build_baseline([features_from_csv(p) for p in args]), indent=2))
    elif mode == "score":
        print(json.dumps(score(features_from_csv(args[0]), json.load(open(args[1]))), indent=2))
    elif mode == "hands":
        print(json.dumps(hands(features_from_csv(args[0]), features_from_csv(args[1]),
                               args[2] if len(args) > 2 else None), indent=2))
    elif mode == "retest":
        print(json.dumps(retest(features_from_csv(args[0]), features_from_csv(args[1])), indent=2))
    elif mode == "self":
        print(json.dumps(self_compare(features_from_csv(args[0]),
                                      [features_from_csv(p) for p in args[1:]]), indent=2))
    else:
        sys.exit(__doc__)
