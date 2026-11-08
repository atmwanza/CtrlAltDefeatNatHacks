"""
sway_score.py - compares balance (sway) trials to a baseline group and between
eyes-open / eyes-closed stages.

NOT a diagnosis. Balance sway depends on age, vision, footwear, fatigue,
medication and many conditions. It is not specific to Parkinson's disease.

Usage:
  python sway_score.py baseline --view front --condition EO --mm-per-px 1.4 t1.csv t2.csv ... > baseline_EO.json
  python sway_score.py score --front t.csv [--side s.csv] --condition EO --mm-per-px 1.4 --baseline baseline_EO.json
  python sway_score.py romberg --view front --mm-per-px 1.4 eyes_open.csv eyes_closed.csv
"""
import argparse
import json
import numpy as np
from sway_features import extract_sway_features, DEFINITIONS

MIN_SD = 0.10   # smallest believable spread in log units (about 10%)
DISCLAIMER = ("Research prototype, not a diagnosis. Postural sway changes with age, vision, "
              "footwear, fatigue, medication and many health conditions, and a single camera "
              "has measurement error of its own. Compared only with a small baseline group.")


def scoring_features(f):
    out = {"log_mean_vel": float(np.log(f["mean_vel"]))}
    if f.get("rms_ml"):
        out["log_rms_ml"] = float(np.log(f["rms_ml"]))
    if f.get("rms_ap"):
        out["log_rms_ap"] = float(np.log(f["rms_ap"]))
    if f.get("area95"):
        out["log_area95"] = float(np.log(f["area95"]))
    return out


def build_baseline(trials, condition):
    rows = [scoring_features(t) for t in trials if t["valid"]]
    if len(rows) < 3:
        raise ValueError("Need at least 3 VALID baseline trials (got %d)." % len(rows))
    base = {"condition": condition, "features": {}}
    for name in rows[0]:
        vals = np.array([r[name] for r in rows if name in r])
        base["features"][name] = {"mean": float(vals.mean()), "sd": float(vals.std(ddof=1)), "n": int(len(vals))}
    return base


def score(f, baseline):
    if not f["valid"]:
        return {"status": "invalid_trial", "reasons": f["reasons"],
                "message": "This recording failed quality checks, so it was not scored. Please repeat it.",
                "disclaimer": DISCLAIMER}
    if f["condition"] != baseline["condition"]:
        return {"status": "error", "message": "Trial is %s but baseline is %s." % (f["condition"], baseline["condition"])}
    zs = {}
    for name, v in scoring_features(f).items():
        b = baseline["features"].get(name)
        if b:
            zs[name] = float(np.clip((v - b["mean"]) / max(b["sd"], MIN_SD), -3, 3))   # + = more sway than baseline

    def index(names):
        return float(np.clip(np.mean([zs[n] for n in names]) / 3.0, 0.0, 1.0))

    names = list(zs)
    idx = index(names)
    loo = [index([n for n in names if n != d]) for d in names] if len(names) > 1 else [idx]
    label = ("Within the range of the baseline group" if idx < 0.15 else
             "Somewhat more sway than the baseline group" if idx < 0.4 else
             "Clearly more sway than the baseline group")
    ranked = sorted(zs.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "status": "scored", "condition": f["condition"], "units": f["units"],
        "deviation_index": round(idx, 3), "range": [round(min(loo), 3), round(max(loo), 3)],
        "label": label,
        "top_features": [{"feature": n, "z": round(z, 2)} for n, z in ranked[:3]],
        "flags": [{"feature": n, "z": round(z, 2)} for n, z in ranked if z >= 2],
        "measurements": {k: f[k] for k in ("path_len", "mean_vel", "rms_ml", "rms_ap", "area95")},
        "com_model": f["com_model"], "path_axes": f["path_axes"],
        "definitions": DEFINITIONS, "warnings": f["warnings"], "disclaimer": DISCLAIMER,
    }


def romberg(eo, ec):
    if not (eo["valid"] and ec["valid"]):
        return {"status": "invalid_trial", "reasons": eo["reasons"] + ec["reasons"],
                "message": "One or both stages failed quality checks."}
    out = {"status": "ok", "units": eo["units"]}
    for k in ("mean_vel", "path_len", "rms_ml", "rms_ap", "area95"):
        if eo.get(k) and ec.get(k):
            out[k] = {"eyes_open": eo[k], "eyes_closed": ec[k], "ec_eo_ratio": round(ec[k] / eo[k], 2)}
    out["note"] = ("Sway usually rises with eyes closed. A ratio above 1 is expected; how large is "
                   "'too large' has to come from your own baseline data, not from this tool.")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["baseline", "score", "romberg"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--view", default="front", choices=["front", "side"])
    ap.add_argument("--front"), ap.add_argument("--side")
    ap.add_argument("--condition", default="EO", choices=["EO", "EC"])
    ap.add_argument("--mm-per-px", type=float, default=None)
    ap.add_argument("--com", default="auto")
    ap.add_argument("--sex", default="average")
    ap.add_argument("--baseline")
    a = ap.parse_intermixed_args()

    def one(path, cond):
        kw = {"front": path} if a.view == "front" else {"side": path}
        return extract_sway_features(mm_per_px=a.mm_per_px, com=a.com, sex=a.sex, condition=cond, **kw)

    if a.mode == "baseline":
        print(json.dumps(build_baseline([one(p, a.condition) for p in a.files], a.condition), indent=2))
    elif a.mode == "score":
        f = extract_sway_features(a.front, a.side, a.mm_per_px, a.com, a.sex, a.condition)
        print(json.dumps(score(f, json.load(open(a.baseline))), indent=2))
    else:
        print(json.dumps(romberg(one(a.files[0], "EO"), one(a.files[1], "EC")), indent=2))
