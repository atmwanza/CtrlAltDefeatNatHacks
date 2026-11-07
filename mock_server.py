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
    "is_mock": True,  # frontend shows a visible badge when this is true, so the mock can't be mistaken for the real backend mid-demo
    "features": {
        "dev_norm":   {"value": 0.63, "ctrl_mean": 0.41, "pd_mean": 0.63, "percentile_pd": 68},
        "vel_cv":     {"value": 1.12, "ctrl_mean": 0.85, "pd_mean": 1.09, "percentile_pd": 55},
        "dom_freq":   {"value": 4.3,  "ctrl_mean": 7.6,  "pd_mean": 4.4,  "percentile_pd": 72},
        "tremor_pct": {"value": 0.11, "ctrl_mean": 0.04, "pd_mean": 0.12, "percentile_pd": 65},
        "p_norm":     {"value": 0.61, "ctrl_mean": 0.85, "pd_mean": 0.57, "percentile_pd": 55},
        "p_cv":       {"value": 0.38, "ctrl_mean": 0.13, "pd_mean": 0.40, "percentile_pd": 60},
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
