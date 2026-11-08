import csv
import io
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from normalizer import load_spiral
from spiral_features import extract_features, turns
from scoring import SCORED, build_group_stats, score, percentile_pd

HERE = Path(__file__).parent           # 01/  (backend + datasets)
FRONTEND = HERE.parent                 # repo root (templates/ + static/)

DISCLAIMER = "Screening tool only. Not a clinical diagnosis. Please discuss any concerns with a clinician."
FEATURE_TEXT = {
    'dev_norm': 'spiral deviation',
    'p_cv': 'pressure variability',
    'tremor_pct': 'tremor-band movement',
    'vel_cv': 'uneven pen speed',
    'dom_freq': 'a tremor frequency in the Parkinsonian range',
}

app = FastAPI(title="DrawDx backend")
app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")


# ---------- reference built once at startup ----------

def build_reference():
    files = [(p, 0) for p in (HERE / 'hw_dataset' / 'control').glob('*.txt')]
    files += [(p, 1) for p in (HERE / 'hw_dataset' / 'parkinson').glob('*.txt')]
    files += [(p, 1) for p in (HERE / 'new_dataset' / 'parkinson').glob('*.txt')]

    healthy, pd = [], []
    for path, label in files:
        data = load_spiral(path)
        if not data['x']:
            continue
        (pd if label == 1 else healthy).append(extract_features(data))

    print(f"Reference built: {len(healthy)} healthy, {len(pd)} Parkinson's")
    return build_group_stats(healthy, pd)


REF = build_reference()


# ---------- per-device calibration ----------
# Some features read differently on a tablet than on the UCI Wacom, even for healthy hands
# (e.g. people press more lightly on glass, which raises pressure variability). Healthy
# drawings in calibration/<platform>/ set that device's "normal"; each calibrated feature
# is scaled by (UCI healthy mean / device healthy mean). Only pen input is calibrated.

CALIBRATED = ['p_cv', 'tremor_pct']


def load_calibration_drawing(path):
    if path.suffix == '.json':                       # saved by /analyze (recordings/)
        d = json.loads(path.read_text())
        idx = range(len(d['x']))
        s = d.get('s') or []
        if len(set(s)) > 1 and len(s) == len(d['x']):   # same longest-stroke rule as /analyze
            longest = max(set(s), key=s.count)
            idx = [i for i, v in enumerate(s) if v == longest]
        return {'x': [d['x'][i] for i in idx], 'y': [d['y'][i] for i in idx],
                'timestamp': [d['t'][i] for i in idx], 'pressure': [d['p'][i] for i in idx]}
    return load_spiral(path)                         # UCI-format .txt

def build_calibration():
    factors = {}
    for folder in (HERE / 'calibration').glob('*'):
        paths = list(folder.glob('*.json')) + list(folder.glob('*.txt'))
        feats = [extract_features(load_calibration_drawing(p)) for p in paths]
        if len(feats) >= 3:
            factors[folder.name] = {k: REF[k]['h_mean'] / float(np.mean([f[k] for f in feats]))
                                    for k in CALIBRATED}
            print(f"Calibration '{folder.name}': {len(feats)} drawings, factors "
                  + ", ".join(f"{k} x{v:.2f}" for k, v in factors[folder.name].items()))
    return factors


CAL = build_calibration()


# ---------- scoring shared by every route ----------

def quality_warnings(data, n_strokes, pointer_type):
    warnings = []
    t = data['timestamp']
    duration = (t[-1] - t[0]) / 1000
    rate = (len(t) - 1) / duration if duration > 0 else 0
    if duration < 3:
        warnings.append(f"Drawing took only {duration:.1f} s; results are less reliable under 3 s.")
    if rate < 50:
        warnings.append(f"Low sample rate ({rate:.0f} Hz); tremor estimates may be unreliable.")
    if n_strokes > 3:
        warnings.append(f"Pen was lifted {n_strokes - 1} times; try to draw in one continuous stroke.")
    if pointer_type == 'mouse':
        warnings.append("Mouse input has no real pressure, so pressure was left out of the score.")
    return warnings


def analyse(data, pointer_type='pen', n_strokes=1, platform=None):
    if len(data['x']) < 150:
        raise HTTPException(400, f"Only {len(data['x'])} points received; need at least 150.")

    use_pressure = pointer_type != 'mouse'
    try:
        feats = extract_features(data, use_pressure=use_pressure)
        n_turns = turns(np.asarray(data['x'], dtype=float), np.asarray(data['y'], dtype=float))
    except (ValueError, ZeroDivisionError, IndexError) as e:
        raise HTTPException(400, f"Could not analyse drawing: {e}")

    calibration = CAL.get(platform, {}) if pointer_type == 'pen' else {}
    for name, factor in calibration.items():
        if name in feats:
            feats[name] *= factor

    warnings = quality_warnings(data, n_strokes, pointer_type)
    if n_turns < 1:
        warnings.append(f"Spiral covers only {n_turns:.1f} turns; trace the whole spiral for a reliable result.")

    level, prob = score(feats, REF)

    features = {}
    for name, value in feats.items():
        s = REF[name]
        features[name] = {
            'value': round(value, 3),
            'ctrl_mean': round(s['h_mean'], 3),
            'pd_mean': round(s['p_mean'], 3),
            'percentile_pd': percentile_pd(value, s),
            'scored': name in SCORED,
        }

    elevated = [FEATURE_TEXT[n] for n, f in features.items() if f['scored'] and f['percentile_pd'] >= 67]
    if elevated:
        listed = elevated[0] if len(elevated) == 1 else ", ".join(elevated[:-1]) + " and " + elevated[-1]
        interpretation = f"Compared with the healthy reference group, this drawing shows {listed}."
    else:
        interpretation = "This drawing falls close to the healthy reference group on every measure."
    if warnings:
        interpretation += " Note: " + " ".join(warnings)

    return {
        'risk_score': int(round(prob * 100)),
        'level': int(level),
        'features': features,
        'interpretation': interpretation,
        'disclaimer': DISCLAIMER,
        'warnings': warnings,
        'is_mock': False,
        'calibrated_for': platform if calibration else None,
        'backend_label': f'LIVE · UCI + {platform.upper()} CAL' if calibration else 'LIVE · UCI REFERENCE',
    }


# ---------- frontend ----------

@app.get("/")
def index():
    return FileResponse(FRONTEND / "templates" / "index.html")


# ---------- POST /analyze (contract.json) ----------

class Drawing(BaseModel):
    x: list[float]
    y: list[float]
    t: list[float]                 # ms
    p: list[float]                 # 0.0-1.0
    s: list[int] = []
    canvas_width: float | None = None
    canvas_height: float | None = None
    device_pixel_ratio: float | None = None
    pointer_type: str = 'pen'
    num_strokes: int | None = None
    device_platform: str | None = None


@app.post("/analyze")
def analyze(d: Drawing):
    if not (len(d.x) == len(d.y) == len(d.t) == len(d.p)):
        raise HTTPException(400, "x, y, t and p must be the same length.")
    data = {'x': d.x, 'y': d.y, 'timestamp': d.t, 'pressure': d.p}
    n_strokes = d.num_strokes or len(set(d.s)) or 1
    # use only the longest stroke: the UCI recordings are one continuous pass, and joining
    # strokes would add a fake jump at every pen lift
    if len(set(d.s)) > 1 and len(d.s) == len(d.x):
        longest = max(set(d.s), key=d.s.count)
        keep = [i for i, s in enumerate(d.s) if s == longest]
        data = {k: [v[i] for i in keep] for k, v in data.items()}
    result = analyse(data, d.pointer_type, n_strokes, d.device_platform)

    # keep every drawing so devices can be calibrated later
    rec_dir = HERE / 'recordings'
    rec_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    (rec_dir / f"{stamp}_{d.device_platform or 'unknown'}.json").write_text(d.model_dump_json())

    print(f"[analyze] {len(d.x)} pts, {n_strokes} stroke(s), {d.pointer_type}, "
          f"{d.device_platform or '?'} -> risk {result['risk_score']} | "
          + ", ".join(f"{k}={v['value']}" for k, v in result['features'].items()))
    return result


# ---------- testing: send a raw UCI file ----------

@app.post("/debug/csv")
async def debug_csv(request: Request):
    text = (await request.body()).decode('utf-8')
    data = {'x': [], 'y': [], 'pressure': [], 'timestamp': []}
    for row in csv.reader(io.StringIO(text), delimiter=';'):
        if len(row) < 7 or row[6].strip() != '0':
            continue
        try:
            x, y, p, ts = float(row[0]), float(row[1]), float(row[3]), float(row[5])
        except ValueError:
            continue
        data['x'].append(x)
        data['y'].append(y)
        data['pressure'].append(p)
        data['timestamp'].append(ts)
    return analyse(data)