"""
Personal mock server for frontend development — not for production/demo.
Returns a hardcoded /analyze response matching contract.json so the UI
(gauge bars, heatmap, risk score) can be built and tested before the real
backend's /analyze route is ready. Swap ANALYZE_ENDPOINT in app.js to the
real backend URL when it's live; nothing else in the frontend needs to change.
"""
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

MOCK_RESPONSE = {
    "risk_score": 71,
    "level": 4,
    "is_mock": True,  # frontend shows a visible badge when this is true, so the mock can't be mistaken for the real backend mid-demo
    "warnings": [],
    # Placeholder numbers in the agreed shape. dev_norm / p_cv / tremor_pct means
    # are the real UCI ones; vel_cv and dom_freq means are made up until the
    # backend computes them. dom_freq is lower in PD, so its pd_mean < ctrl_mean.
    "features": {
        "dev_norm":   {"value": 0.041, "ctrl_mean": 0.028, "pd_mean": 0.046, "percentile_pd": 72, "scored": True},
        "p_cv":       {"value": 0.160, "ctrl_mean": 0.113, "pd_mean": 0.183, "percentile_pd": 67, "scored": True},
        "tremor_pct": {"value": 0.120, "ctrl_mean": 0.084, "pd_mean": 0.177, "percentile_pd": 39, "scored": True},
        "vel_cv":     {"value": 0.62,  "ctrl_mean": 0.50,  "pd_mean": 0.70,  "percentile_pd": 60, "scored": True},
        "dom_freq":   {"value": 5.2,   "ctrl_mean": 7.6,   "pd_mean": 4.4,   "percentile_pd": 75, "scored": False},
    },
    "interpretation": (
        "This drawing shows elevated spiral deviation, reduced pen pressure, and tremor activity "
        "in the frequency range associated with Parkinsonian tremor, relative to the healthy "
        "reference group."
    ),
    "disclaimer": "Screening tool only. Not a clinical diagnosis. Please discuss any concerns with a clinician.",
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True) or {}
    x, y = data.get("x", []), data.get("y", [])
    strokes = len(set(data.get("s", [])))
    pressures = data.get("p", [])
    avg_pressure = sum(pressures) / len(pressures) if pressures else 0
    pressure_cv = _coefficient_of_variation(pressures)

    print(
        f"[mock_server] received {len(x)} points, {strokes} stroke(s), "
        f"avg pressure {avg_pressure:.2f}, canvas "
        f"{data.get('canvas_width')}x{data.get('canvas_height')} "
        f"(dpr {data.get('device_pixel_ratio')}), pointer_type={data.get('pointer_type')}"
    )

    # Not real analysis — just enough variation from the real payload so the two
    # demo presets (and a live drawing) don't all show an identical hardcoded
    # number. Blends pressure CV with radial jitter so the score still moves on
    # a mouse test (pressure CV is always 0 there, per the W3C pointer-events
    # spec) and on a firm-press, shaky-hand test (pressure CV alone understates
    # a spiral that's wobbling spatially but not in pressure).
    radial_jitter = _radial_jitter(x, y, data.get("canvas_width"), data.get("canvas_height"))
    raw = radial_jitter * 40.0 if pressure_cv < 0.01 else (pressure_cv * 125.0 + radial_jitter * 18.0)

    response = dict(MOCK_RESPONSE)
    response["risk_score"] = min(95, max(5, round(raw)))
    response["level"] = sum(response["risk_score"] >= c for c in (10, 30, 50, 70, 90))
    response["warnings"] = (
        ["Drawn with a mouse: pressure is a fixed 0.5, so pressure features are not meaningful."]
        if data.get("pointer_type") == "mouse" else []
    )
    return jsonify(response)


def _coefficient_of_variation(values):
    if len(values) < 2:
        return 0.25
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.25
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean


def _radial_jitter(x, y, canvas_width, canvas_height):
    """Std of the 2nd difference of radius from center — spatial wobble, independent of pressure."""
    if len(x) < 5 or not canvas_width or not canvas_height:
        return 0.0
    cx, cy = canvas_width / 2.0, canvas_height / 2.0
    r = [((xi - cx) ** 2 + (yi - cy) ** 2) ** 0.5 for xi, yi in zip(x, y)]
    d1 = [r[i + 1] - r[i] for i in range(len(r) - 1)]
    d2 = [d1[i + 1] - d1[i] for i in range(len(d1) - 1)]
    if not d2:
        return 0.0
    mean = sum(d2) / len(d2)
    variance = sum((v - mean) ** 2 for v in d2) / len(d2)
    # normalize against canvas size so it's comparable across devices/zoom levels
    return (variance ** 0.5) / max(canvas_width, canvas_height) * 1000


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
