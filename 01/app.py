import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from normalizer import load_spiral
from spiral_features import extract_features
from scoring import build_group_stats, score

HERE = Path(__file__).parent
LEVEL_TEXT = ["Very unlikely", "Unlikely", "Uncertain, leaning no",
              "Possible", "Likely", "Very likely"]

app = FastAPI(title="Parkinson's Spiral Screener")
results = []  # newest last, kept in memory while the server runs


# ---------- build the reference once at startup ----------

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


# ---------- shared scoring ----------

def analyse(data, source):
    if len(data['x']) < 50:
        raise HTTPException(400, f"Only {len(data['x'])} static-spiral points received; need at least 50.")
    try:
        feats = extract_features(data)
    except (ZeroDivisionError, ValueError) as e:
        raise HTTPException(400, f"Could not analyse drawing: {e}")

    level, prob = score(feats, REF)
    result = {
        'level': int(level),
        'label': LEVEL_TEXT[level],
        'probability': round(prob, 3),
        'features': {k: round(v, 4) for k, v in feats.items()},
        'points': len(data['x']),
        'source': source,
        'time': datetime.now().strftime('%H:%M:%S'),
    }
    results.append(result)
    return result


# ---------- input option 1: JSON ----------

class Spiral(BaseModel):
    x: list[float]
    y: list[float]
    pressure: list[float]
    grip_angle: list[float]
    timestamp: list[float]  # milliseconds


@app.post("/spiral")
def submit_json(spiral: Spiral):
    data = spiral.model_dump()
    lengths = {len(v) for v in data.values()}
    if len(lengths) != 1:
        raise HTTPException(400, "All lists must be the same length.")
    return analyse(data, 'json')


# ---------- input option 2: raw CSV text (UCI format) ----------

@app.post("/spiral/csv")
async def submit_csv(request: Request):
    text = (await request.body()).decode('utf-8')
    data = {'x': [], 'y': [], 'pressure': [], 'grip_angle': [], 'timestamp': []}
    for row in csv.reader(io.StringIO(text), delimiter=';'):
        if len(row) < 7 or row[6].strip() != '0':
            continue  # skip blank, malformed or non-static rows
        try:
            values = [float(row[i]) for i in (0, 1, 3, 4, 5)]
        except ValueError:
            continue
        for key, v in zip(('x', 'y', 'pressure', 'grip_angle', 'timestamp'), values):
            data[key].append(v)
    return analyse(data, 'csv')


# ---------- results ----------

@app.get("/latest")
def latest():
    if not results:
        raise HTTPException(404, "No drawings yet.")
    return results[-1]


@app.get("/", response_class=HTMLResponse)
def dashboard():
    if results:
        r = results[-1]
        bar = "".join(
            f'<div class="seg{" on" if i <= r["level"] else ""}">{i}</div>' for i in range(6))
        feats = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in r['features'].items())
        body = f"""
        <div class="level">{r['level']}<span>/5</span></div>
        <div class="label">{r['label']}</div>
        <div class="bar">{bar}</div>
        <p class="prob">Probability: {r['probability']:.0%} &middot; {r['points']} points &middot; {r['time']}</p>
        <table>{feats}</table>"""
    else:
        body = '<p class="label">Waiting for a drawing&hellip;</p>'

    history = "".join(
        f"<tr><td>{r['time']}</td><td>{r['level']}/5</td><td>{r['probability']:.0%}</td></tr>"
        for r in reversed(results[-10:]))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<title>Spiral Screener</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 520px; margin: 40px auto; padding: 0 16px; color: #222; }}
  h1 {{ font-size: 20px; }}
  .level {{ font-size: 96px; font-weight: 700; line-height: 1; }}
  .level span {{ font-size: 32px; color: #888; }}
  .label {{ font-size: 22px; margin: 8px 0 16px; }}
  .bar {{ display: flex; gap: 4px; }}
  .seg {{ flex: 1; text-align: center; padding: 8px 0; background: #eee; border-radius: 4px; color: #999; }}
  .seg.on {{ background: #c0392b; color: white; }}
  .prob {{ color: #555; }}
  table {{ border-collapse: collapse; margin-top: 12px; width: 100%; }}
  td {{ padding: 4px 8px; border-bottom: 1px solid #eee; }}
  .note {{ font-size: 12px; color: #888; margin-top: 24px; }}
</style></head>
<body>
  <h1>Spiral Test Result</h1>
  {body}
  <h1 style="margin-top:32px">Recent</h1>
  <table>{history}</table>
  <p class="note">Screening indicator only, not a diagnosis.</p>
</body></html>"""