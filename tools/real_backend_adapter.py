"""
Temporary bridge until Adam's branch has a real /analyze route. Serves Joel's
frontend and answers /analyze (contract.json shape) using Adam's own
feature-extraction and scoring code, imported unmodified, against the real UCI
data. It's also the reference implementation for the tablet preprocessing and
calibration described in contract.json (write_uci_file, resample,
TABLET_CALIBRATION). Delete it once /analyze exists in the backend.

Run:  python tools/real_backend_adapter.py
Needs Adam's branch checked out; set ADAM_BACKEND_DIR to its 01/ folder if it
isn't at ../adam-backend/01 next to this repo.

Only 3 features exist in Adam's branch today (pressure_cv, tremor, deviation).
percentile_pd is a linear interpolation between the control and PD means,
clamped 0-100, not an official percentile ranking.
"""
import math
import os
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

REPO_DIR = Path(__file__).resolve().parent.parent
ADAM_DIR = Path(os.environ.get("ADAM_BACKEND_DIR", REPO_DIR.parent / "adam-backend" / "01"))
sys.path.insert(0, str(ADAM_DIR))

from normalizer import load_spiral  # noqa: E402  (Adam's code, unmodified)
from spiral_features import extract_features    # noqa: E402
from scoring import build_group_stats, score    # noqa: E402

app = Flask(
    __name__,
    template_folder=str(REPO_DIR / "templates"),
    static_folder=str(REPO_DIR / "static"),
)

FEATURE_NAME_MAP = {
    "pressure_cv": "p_cv",
    "tremor": "tremor_pct",
    "deviation": "dev_norm",
}


def build_reference():
    """Identical to Adam's app.py build_reference() — reproduced here because
    importing his app.py directly would also try to boot a FastAPI app."""
    files = [(p, 0) for p in (ADAM_DIR / "hw_dataset" / "control").glob("*.txt")]
    files += [(p, 1) for p in (ADAM_DIR / "hw_dataset" / "parkinson").glob("*.txt")]
    files += [(p, 1) for p in (ADAM_DIR / "new_dataset" / "parkinson").glob("*.txt")]

    healthy, pd = [], []
    for path, label in files:
        data = load_spiral(path)
        if not data["x"]:
            continue
        (pd if label == 1 else healthy).append(extract_features(data))

    print(f"[real_backend_adapter] reference built: {len(healthy)} healthy, {len(pd)} Parkinson's (real UCI data)")
    return build_group_stats(healthy, pd)


print("[real_backend_adapter] loading real UCI dataset and building reference stats (Adam's code)...")
REF = build_reference()
print("[real_backend_adapter] ready.")


DRAWINGS_DIR = REPO_DIR / "tablet_drawings"
DRAWINGS_DIR.mkdir(exist_ok=True)

UCI_SPIRAL_SPAN = 370      # UCI spirals span roughly 370 digitizer units in X and Y
TEMPLATE_RADIUS_FRAC = 0.42  # matches drawSpiralTemplate() in app.js


def write_uci_file(xs, ys, ts, ps, canvas_width, canvas_height):
    """Write one tablet drawing in the UCI hw_dataset format so it can be loaded
    with Adam's load_spiral() and run through his main.py unchanged:
        X;Y;Z;Pressure;GripAngle;Timestamp;TestID   (all integers)
    Coordinates are scaled so the on-screen template spiral spans the same
    ~370 units a UCI spiral does; pressure 0-1 is mapped to UCI's 0-1023;
    timestamps are integer ms starting from 0. Z and GripAngle don't exist on
    the S Pen / PointerEvent API, so they're written as 0 (neither is used by
    extract_features). TestID is 0, the static spiral test."""
    template_diameter = 2 * TEMPLATE_RADIUS_FRAC * min(canvas_width or 1, canvas_height or 1)
    scale = UCI_SPIRAL_SPAN / template_diameter
    xs, ys, ts, ps = resample(xs, ys, ts, ps, UCI_SAMPLE_MS)
    t0 = ts[0]

    name = time.strftime("tablet_%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}.txt"
    path = DRAWINGS_DIR / name
    with open(path, "w", newline="") as f:
        for x, y, t, p in zip(xs, ys, ts, ps):
            f.write(
                f"{round(x * scale)};{round(y * scale)};0;"
                f"{round(max(0.0, min(1.0, p)) * 1023)};0;{round(t - t0)};0\n"
            )
    return path


UCI_SAMPLE_MS = 7  # UCI files are recorded every 7ms (~143Hz)

# Galaxy Tab S10 FE + S Pen -> UCI (Wacom Cintiq 12WX) scale factors, from 20
# healthy drawings (4 people x 5). Each factor = UCI healthy mean / tablet
# healthy mean, using per-person averages. Leave-one-person-out: healthy
# drawings flagged went 15/20 -> 1/20 (the one left is a 13%-pressure drawing).
# Factor range across folds: pressure_cv 0.56-0.72, deviation 0.65-0.76.
# Tremor is deliberately not calibrated (adding it changed nothing).
# Assumes PD patients shift by the same factor on this device — untested,
# since no one with PD has drawn on it.
TABLET_CALIBRATION = {"pressure_cv": 0.62, "deviation": 0.71}


def resample(xs, ys, ts, ps, step_ms):
    """Linear-interpolate onto an even step_ms grid. The S Pen reports every
    ~2ms; at that rate integer UCI coordinates move 0 or 1 unit per sample,
    and that staircase reads as extra tremor-band power (measured: tremor
    0.111 at 2ms vs 0.084 at 7ms on the same drawing)."""
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    xs, ys, ts, ps = ([xs[i] for i in order], [ys[i] for i in order],
                      [ts[i] for i in order], [ps[i] for i in order])
    out_x, out_y, out_t, out_p = [], [], [], []
    j = 0
    g = ts[0]
    while g <= ts[-1]:
        while j < len(ts) - 2 and ts[j + 1] < g:
            j += 1
        t_a, t_b = ts[j], ts[j + 1]
        w = 0.0 if t_b == t_a else (g - t_a) / (t_b - t_a)
        out_x.append(xs[j] + (xs[j + 1] - xs[j]) * w)
        out_y.append(ys[j] + (ys[j + 1] - ys[j]) * w)
        out_p.append(ps[j] + (ps[j + 1] - ps[j]) * w)
        out_t.append(g)
        g += step_ms
    return out_x, out_y, out_t, out_p


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    payload = request.get_json(force=True) or {}
    xs, ys, ts, ps = payload.get("x", []), payload.get("y", []), payload.get("t", []), payload.get("p", [])
    ss = payload.get("s", [0] * len(xs))

    if len(xs) < 50:
        return jsonify({"error": f"Only {len(xs)} points received; need at least 50."}), 400
    if not (payload.get("canvas_width") or 0) > 0 or not (payload.get("canvas_height") or 0) > 0:
        # Coordinates are scaled by canvas size; a 0 size (canvas hidden at
        # submit time) inflated them ~580x and changed the tremor value.
        return jsonify({"error": "canvas_width and canvas_height must be greater than 0."}), 400

    # extract_features() treats its whole input as ONE continuous recording,
    # same as the UCI files it was validated on (single unbroken pass, no pen
    # lifts). The frontend sends every stroke concatenated with an 's' index;
    # without filtering by it, a pen lift/re-touch mid-drawing gets fed in as
    # if it were continuous motion, which reads as a spurious velocity/pressure
    # spike right at the lift point and inflates tremor/deviation/pressure-CV
    # for reasons that have nothing to do with how the person actually drew.
    # Use only the longest single stroke, matching what the reference data is.
    num_strokes = len(set(ss))
    if num_strokes > 1:
        from collections import Counter
        longest_stroke = Counter(ss).most_common(1)[0][0]
        idx = [i for i, s in enumerate(ss) if s == longest_stroke]
        xs, ys, ts, ps = ([xs[i] for i in idx], [ys[i] for i in idx],
                           [ts[i] for i in idx], [ps[i] for i in idx])
    print(
        f"[real_backend_adapter] {num_strokes} stroke(s) submitted, "
        f"using longest ({len(xs)} of {len(payload.get('x', []))} points)",
        flush=True,
    )

    uci_path = write_uci_file(xs, ys, ts, ps, payload.get("canvas_width"), payload.get("canvas_height"))
    print(f"[real_backend_adapter] saved UCI-format file: {uci_path}", flush=True)

    # Score the saved file exactly the way Adam's main.py scores a UCI file.
    data = load_spiral(uci_path)

    try:
        raw_feats = extract_features(data)
    except (ZeroDivisionError, ValueError) as e:
        return jsonify({"error": f"Could not analyze drawing: {e}"}), 400

    calibrate = payload.get("pointer_type") == "pen"
    feats = {k: v * (TABLET_CALIBRATION.get(k, 1.0) if calibrate else 1.0) for k, v in raw_feats.items()}

    level, probability = score(feats, REF)

    features_out = {}
    for adam_key, value in feats.items():
        stats = REF[adam_key]
        ctrl_mean, pd_mean = stats["h_mean"], stats["p_mean"]
        span = pd_mean - ctrl_mean
        pct = 50.0 if abs(span) < 1e-9 else (value - ctrl_mean) / span * 100
        features_out[FEATURE_NAME_MAP.get(adam_key, adam_key)] = {
            "value": round(value, 4),
            "raw_value": round(raw_feats[adam_key], 4),
            "ctrl_mean": round(ctrl_mean, 4),
            "pd_mean": round(pd_mean, 4),
            "percentile_pd": int(max(0, min(100, round(pct)))),
            "scored": True,
        }

    warnings = quality_warnings(data, payload.get("pointer_type"))

    print(
        f"[real_backend_adapter] {len(xs)} points -> level {level}/5, "
        f"probability {probability:.2f}, features={list(features_out.keys())}",
        flush=True,
    )
    for name, f in features_out.items():
        print(
            f"[real_backend_adapter]   {name:12s} value={f['value']:.4f} (raw {f['raw_value']:.4f})  "
            f"ctrl_mean={f['ctrl_mean']:.4f}  pd_mean={f['pd_mean']:.4f}",
            flush=True,
        )

    return jsonify({
        "risk_score": round(probability * 100),
        "level": int(level),
        "features": features_out,
        "warnings": warnings,
        "interpretation": (
            f"Real-backend comparison (Adam's model, {len(feats)} features) against the live UCI "
            f"reference set. Scored level {level}/5 on his classifier."
        ),
        "disclaimer": "Screening tool only. Not a clinical diagnosis. Please discuss any concerns with a clinician.",
        "backend_label": f"LIVE — Adam's model, {len(feats)} features, real UCI data",
    })


def quality_warnings(data, pointer_type):
    """Non-blocking notes returned with the score. The frontend already refuses
    drawings under 10 s or under 30% pressure; these cover what gets through."""
    x, y, t = data["x"], data["y"], data["timestamp"]
    out = []
    seconds = (t[-1] - t[0]) / 1000 if t else 0
    if seconds < 10:
        out.append(f"Short drawing ({seconds:.0f} s). The reference recordings took 14-48 s.")
    if len(x) < 500:
        out.append(f"Few samples ({len(x)}). Results are less reliable.")
    turns = spiral_turns(x, y)
    if turns < 1:
        out.append(f"Less than one full turn ({turns:.1f}).")
    elif turns < 2.5:
        out.append(f"Only {turns:.1f} of the template's 3 turns were drawn.")
    if pointer_type == "mouse":
        out.append("Drawn with a mouse: pressure is a fixed 0.5, so pressure features are not meaningful.")
    return out


def spiral_turns(x, y):
    if len(x) < 2:
        return 0.0
    cx, cy = sum(x) / len(x), sum(y) / len(y)
    total, prev = 0.0, math.atan2(y[0] - cy, x[0] - cx)
    for xi, yi in zip(x[1:], y[1:]):
        cur = math.atan2(yi - cy, xi - cx)
        step = cur - prev
        while step > math.pi:
            step -= 2 * math.pi
        while step < -math.pi:
            step += 2 * math.pi
        total += step
        prev = cur
    return abs(total) / (2 * math.pi)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
