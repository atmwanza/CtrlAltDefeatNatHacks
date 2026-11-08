"""
sway_features.py - postural-sway measurements from camera pose landmarks.

One trial = one standing recording (e.g. a 30-60 s Romberg stage, eyes open
"EO" or eyes closed "EC"). Landmarks come from a pose tracker such as MediaPipe.

Input CSV (header required), one row per video frame. Only the horizontal
image coordinate of each landmark is needed:
    time_ms,left_hip_x,right_hip_x,left_ear_x,right_ear_x,...
Optional <name>_vis columns (tracker visibility 0-1) are used for quality checks.
Landmark names: left_/right_ + ear, shoulder, elbow, wrist, hip, knee, ankle,
and (optional) foot_index, index, pinky.

CAMERA VIEW MATTERS:
  front camera -> horizontal x is medio-lateral (ML, side-to-side) sway
  side camera  -> horizontal x is antero-posterior (AP, front-to-back) sway
A single front camera MISSES most front-to-back sway (see the review).

CENTRE OF MASS MODELS (--com):
  hip           midpoint of the hips (defensible minimal model)
  hip94_ear6    94% hips + 6% ears (the review's minimal weighted model)
  full          16-segment-style weighted sum using de Leva (1996) parameters
                (2D approximation with MediaPipe landmarks)
  ear_hip_5050  50/50 ear+hip average. KNOWN BIASED (about 30 cm too high,
                inflates sway ~1.3x). Only here for comparison - don't use it.
  auto          full if all landmarks exist, else hip

Usage examples:
  python sway_features.py --front trial.csv --mm-per-px 1.4 --condition EO
  python sway_features.py --front f.csv --side s.csv --mm-per-px 1.4
  python sway_features.py --front mannequin.csv --mm-per-px 1.4 --noise
"""
import argparse
import csv
import json
import sys
import numpy as np

RESAMPLE_HZ = 30.0
CUTOFF_HZ = 2.0            # low-pass cutoff for sway (tunable; lower = smoother)
MIN_DURATION_S = 25.0
MAX_MISSING = 0.05
MIN_VISIBILITY = 0.5
MIN_SNR = 5.0           # tunable: set it from your own still-mannequin noise test
LARGE_EXCURSION_MM = 150.0

# de Leva (1996) adjusted Zatsiorsky-Seluyanov parameters, from the HAS-motion wiki page.
# mass: fraction of body mass; com: centre of mass as a fraction of segment length from the proximal end.
DELEVA = {
    "male": {
        "mass": dict(head=0.0694, trunk=0.4346, upper_arm=0.0271, forearm=0.0162,
                     hand=0.0061, thigh=0.1416, shank=0.0433, foot=0.0137),
        "com": dict(head=0.5002, trunk=0.5138, upper_arm=0.5772, forearm=0.4574,
                    hand=0.7900, thigh=0.4095, shank=0.4395, foot=0.4415),
    },
    "female": {
        "mass": dict(head=0.0668, trunk=0.4257, upper_arm=0.0255, forearm=0.0138,
                     hand=0.0056, thigh=0.1478, shank=0.0481, foot=0.0129),
        "com": dict(head=0.4841, trunk=0.4964, upper_arm=0.5754, forearm=0.4559,
                    hand=0.7474, thigh=0.3612, shank=0.4352, foot=0.4014),
    },
}
FULL_REQUIRED = [s + j for j in ("ear", "shoulder", "elbow", "wrist", "hip", "knee", "ankle")
                 for s in ("left_", "right_")]
OPTIONAL = [s + j for j in ("foot_index", "index", "pinky") for s in ("left_", "right_")]

DEFINITIONS = {
    "path_len": "Sway path length: total distance the centre of mass travels (sum of frame-to-frame moves).",
    "mean_vel": "Mean sway velocity = path length / duration.",
    "rms_ml / rms_ap": "RMS sway: standard deviation of the centre-of-mass position about its mean, side-to-side / front-to-back.",
    "area95": "95% confidence-ellipse area of the (ML, AP) sway path (needs both camera views).",
    "ec_eo_ratio": "Eyes-closed value divided by eyes-open value for the same measure.",
}


def deleva_params(sex):
    if sex in DELEVA:
        return DELEVA[sex]["mass"], DELEVA[sex]["com"]
    m, c = DELEVA["male"], DELEVA["female"]
    return ({k: (m["mass"][k] + c["mass"][k]) / 2 for k in m["mass"]},
            {k: (m["com"][k] + c["com"][k]) / 2 for k in m["com"]})


def load_landmarks(path):
    """Return (t_seconds, {name: x array}, {name: visibility array})."""
    t, xs, vis = [], {}, {}
    with open(path, newline="") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames or []
        names = [c[:-2] for c in cols if c.endswith("_x")]
        for n in names:
            xs[n] = []
            if n + "_vis" in cols:
                vis[n] = []
        for row in rd:
            t.append(float(row["time_ms"]) / 1000.0)
            for n in names:
                v = row[n + "_x"]
                xs[n].append(float(v) if v not in ("", None) else np.nan)
                if n in vis:
                    vv = row[n + "_vis"]
                    vis[n].append(float(vv) if vv not in ("", None) else 0.0)
    t = np.array(t)
    order = np.argsort(t)
    t = t[order]
    return (t, {n: np.array(a)[order] for n, a in xs.items()},
            {n: np.array(a)[order] for n, a in vis.items()})


def fill_nans(a):
    bad = np.isnan(a)
    if bad.all():
        raise ValueError("A landmark has no valid samples.")
    if bad.any():
        idx = np.arange(len(a))
        a = a.copy()
        a[bad] = np.interp(idx[bad], idx[~bad], a[~bad])
    return a


def choose_model(lm, com):
    has_full = all(n in lm for n in FULL_REQUIRED)
    has_hip = "left_hip" in lm and "right_hip" in lm
    has_ear = "left_ear" in lm and "right_ear" in lm
    if com == "auto":
        com = "full" if has_full else "hip"
    need = {"hip": has_hip, "hip94_ear6": has_hip and has_ear,
            "ear_hip_5050": has_hip and has_ear, "full": has_full}
    if com not in need:
        raise ValueError("Unknown com model: %s" % com)
    if not need[com]:
        raise ValueError("Landmarks for com model '%s' are missing from the CSV." % com)
    return com


def com_series(lm, com, sex):
    """Horizontal centre-of-mass position (pixels) for every frame."""
    g = lambda n: lm[n]
    mid = lambda a, b: 0.5 * (g(a) + g(b))
    if com == "hip":
        return mid("left_hip", "right_hip")
    if com == "hip94_ear6":
        return 0.94 * mid("left_hip", "right_hip") + 0.06 * mid("left_ear", "right_ear")
    if com == "ear_hip_5050":
        return 0.5 * (mid("left_hip", "right_hip") + mid("left_ear", "right_ear"))
    m, f = deleva_params(sex)
    head = mid("left_ear", "right_ear")                       # approximation: head CoM ~ mid-ear
    ms, mh = mid("left_shoulder", "right_shoulder"), mid("left_hip", "right_hip")
    total = m["head"] * head + m["trunk"] * (ms + f["trunk"] * (mh - ms))
    for s in ("left_", "right_"):
        sh, el, wr = g(s + "shoulder"), g(s + "elbow"), g(s + "wrist")
        hp, kn, an = g(s + "hip"), g(s + "knee"), g(s + "ankle")
        hand_end = 0.5 * (g(s + "index") + g(s + "pinky")) if (s + "index") in lm and (s + "pinky") in lm else wr
        toe = g(s + "foot_index") if (s + "foot_index") in lm else an
        total = (total
                 + m["upper_arm"] * (sh + f["upper_arm"] * (el - sh))
                 + m["forearm"] * (el + f["forearm"] * (wr - el))
                 + m["hand"] * (wr + f["hand"] * (hand_end - wr))
                 + m["thigh"] * (hp + f["thigh"] * (kn - hp))
                 + m["shank"] * (kn + f["shank"] * (an - kn))
                 + m["foot"] * (an + f["foot"] * (toe - an)))
    return total


def lowpass(x, fs, cutoff):
    """Zero-phase FFT low-pass with mirrored edges."""
    pad = int(2 * fs)
    xp = np.pad(x, pad, mode="reflect")
    spec = np.fft.rfft(xp - np.mean(xp))
    f = np.fft.rfftfreq(len(xp), 1.0 / fs)
    spec[f > cutoff] = 0
    return (np.fft.irfft(spec, n=len(xp)) + np.mean(xp))[pad:-pad]


def load_view(path, com, sex, mm_per_px):
    """Load one camera file -> (t, com_mm, info)."""
    t, lm, vis = load_landmarks(path)
    model = choose_model(lm, com)
    needed = {"hip": ["left_hip", "right_hip"],
              "hip94_ear6": ["left_hip", "right_hip", "left_ear", "right_ear"],
              "ear_hip_5050": ["left_hip", "right_hip", "left_ear", "right_ear"],
              "full": FULL_REQUIRED}[model]
    missing_frac = float(np.mean(np.any([np.isnan(lm[n]) for n in needed], axis=0)))
    vis_vals = [vis[n] for n in needed if n in vis]
    mean_vis = float(np.mean(vis_vals)) if vis_vals else None
    lm = {n: fill_nans(a) for n, a in lm.items()}
    x = com_series(lm, model, sex) * (mm_per_px if mm_per_px else 1.0)
    return t, x, {"com_model": model, "missing_fraction": missing_frac, "mean_visibility": mean_vis}


def axis_metrics(x, fs):
    xs = lowpass(x, fs, CUTOFF_HZ)
    resid = x - xs
    jitter = float(np.std(resid))
    inband_noise = jitter * np.sqrt(CUTOFF_HZ / (fs / 2.0))   # assumes white tracking noise
    xs = xs - np.mean(xs)
    return xs, {
        "rms": float(np.std(xs)),
        "range": float(np.ptp(xs)),
        "jitter_rms": jitter,
        "inband_noise": float(inband_noise),
    }


def extract_sway_features(front=None, side=None, mm_per_px=None, com="auto", sex="average",
                          condition="EO", min_duration=MIN_DURATION_S):
    if not front and not side:
        raise ValueError("Give at least one camera file (front and/or side).")
    reasons, warnings = [], []
    views = {}
    for axis, path in (("ML", front), ("AP", side)):
        if path:
            views[axis] = load_view(path, com, sex, mm_per_px)

    # common time grid
    t0 = max(v[0][0] for v in views.values())
    t1 = min(v[0][-1] for v in views.values())
    duration = float(t1 - t0)
    fs = RESAMPLE_HZ
    tg = np.arange(t0, t1, 1.0 / fs)
    sampling = min(1.0 / float(np.median(np.diff(v[0]))) for v in views.values())

    units = "mm" if mm_per_px else "px"
    if not mm_per_px:
        warnings.append("No mm-per-pixel scale given: values are in pixels and not comparable across setups.")
    if sampling < 20:
        reasons.append("Frame rate too low (%.0f Hz)." % sampling)
    if duration < min_duration:
        reasons.append("Recording too short (%.1f s; need at least %.0f s)." % (duration, min_duration))

    series, metrics, models = {}, {}, set()
    for axis, (t, x, info) in views.items():
        models.add(info["com_model"])
        if info["missing_fraction"] > MAX_MISSING:
            reasons.append("%s view: landmarks missing in %.0f%% of frames." % (axis, 100 * info["missing_fraction"]))
        if info["mean_visibility"] is not None and info["mean_visibility"] < MIN_VISIBILITY:
            reasons.append("%s view: tracker visibility low (%.2f)." % (axis, info["mean_visibility"]))
        if info["com_model"] == "ear_hip_5050":
            warnings.append("ear_hip_5050 model is known to put the CoM ~30 cm too high and inflate sway ~1.3x.")
        if len(tg) < 10:
            continue
        xs, mt = axis_metrics(np.interp(tg, t, x), fs)
        series[axis], metrics[axis] = xs, mt
        snr = mt["rms"] / max(mt["inband_noise"], 1e-9)
        mt["snr"] = float(snr)
        if snr < MIN_SNR:
            reasons.append("%s view: sway is not clearly above tracking noise (SNR %.1f)." % (axis, snr))

    if not series:
        return {"valid": False, "reasons": reasons + ["No usable data."], "warnings": warnings}

    dur = len(tg) / fs
    if "ML" in series and "AP" in series:
        dx, dy = np.diff(series["ML"]), np.diff(series["AP"])
        path = float(np.sum(np.hypot(dx, dy)))
        cov = np.cov(np.vstack([series["ML"], series["AP"]]))
        area95 = float(np.pi * 5.991 * np.sqrt(max(np.linalg.det(cov), 0.0)))
        path_axes = "2D"
    else:
        only = next(iter(series))
        path = float(np.sum(np.abs(np.diff(series[only]))))
        area95, path_axes = None, only
        warnings.append("Only the %s axis was measured%s." % (
            only, "; front-to-back sway is missed" if only == "ML" else "; side-to-side sway is missed"))
    max_range = max(m["range"] for m in metrics.values())
    if units == "mm" and max_range > LARGE_EXCURSION_MM:
        warnings.append("Large excursion (%.0f mm): possible step or loss of balance - check the video." % max_range)

    return {
        "valid": len(reasons) == 0,
        "reasons": reasons,
        "warnings": warnings,
        "condition": condition,
        "units": units,
        "com_model": sorted(models)[0] if len(models) == 1 else sorted(models),
        "path_axes": path_axes,
        "path_len": path,
        "mean_vel": path / dur,
        "rms_ml": metrics["ML"]["rms"] if "ML" in metrics else None,
        "rms_ap": metrics["AP"]["rms"] if "AP" in metrics else None,
        "area95": area95,
        "jitter_rms": {a: m["jitter_rms"] for a, m in metrics.items()},
        "snr": {a: m["snr"] for a, m in metrics.items()},
        "duration_s": float(dur),
        "sampling_hz": float(sampling),
    }


def noise_floor(front=None, side=None, mm_per_px=None, com="auto", sex="average"):
    """Run on a recording of a STILL mannequin: how much 'sway' is just tracking noise?"""
    out = {"units": "mm" if mm_per_px else "px"}
    for axis, path in (("ML", front), ("AP", side)):
        if not path:
            continue
        t, x, info = load_view(path, com, sex, mm_per_px)
        fs = RESAMPLE_HZ
        tg = np.arange(t[0], t[-1], 1.0 / fs)
        xg = np.interp(tg, t, x)
        xs, mt = axis_metrics(xg, fs)
        out[axis] = {
            "raw_rms": float(np.std(xg)),
            "in_band_rms": mt["rms"],
            "suggested_min_trustworthy_sway": 3.0 * mt["rms"],
            "com_model": info["com_model"],
        }
    out["note"] = ("A real subject's RMS sway should be well above the in-band RMS. "
                   "The 3x figure is a rule of thumb, not a validated threshold.")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--front"), ap.add_argument("--side")
    ap.add_argument("--mm-per-px", type=float, default=None)
    ap.add_argument("--com", default="auto", choices=["auto", "hip", "hip94_ear6", "full", "ear_hip_5050"])
    ap.add_argument("--sex", default="average", choices=["average", "male", "female"])
    ap.add_argument("--condition", default="EO", choices=["EO", "EC"])
    ap.add_argument("--noise", action="store_true", help="treat the file as a still-mannequin noise test")
    a = ap.parse_args()
    if a.noise:
        print(json.dumps(noise_floor(a.front, a.side, a.mm_per_px, a.com, a.sex), indent=2))
    else:
        print(json.dumps(extract_sway_features(a.front, a.side, a.mm_per_px, a.com, a.sex, a.condition), indent=2))
