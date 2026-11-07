# DrawDx — Claude Code Handoff Document
**natHacks 2026 | Healthcare & Accessibility Track | 64-hour hackathon**
**Author: Joel Oluwafenwa Abifarin (fenwaabifarin44@gmail.com)**
**Generated from previous Claude session to continue work seamlessly.**

---

## 1. What DrawDx Is

DrawDx is an **in-browser Parkinson's Disease triage tool** that runs on a Samsung Galaxy Tab S10 FE with S Pen. The patient draws an Archimedean spiral on the tablet screen. The app captures the drawing via the PointerEvent API (at 240Hz), extracts 6 clinical signal features, compares them against a real reference dataset of 25 confirmed PD patients + 7 healthy controls (UCI Parkinson's dataset ID 395), and returns a 0–100 risk score with individual feature breakdowns.

**Core value proposition:** Runs in a browser with no native app install. Uses real digitizer data (pressure, velocity, tremor frequency) rather than just visual spiral shape. Reference dataset is embedded in the backend — this is not a black-box model, it's explainable feature comparison.

---

## 2. Getting Started — GitHub + Environment Setup

### How to give Claude Code GitHub access
Run these in the terminal in the DrawDx project directory:

```bash
# Option A: If gh CLI is installed
gh auth login
gh repo clone <teammate's repo URL>
cd drawdx   # or whatever the repo folder is named

# Option B: Standard git
git clone https://github.com/<org-or-teammate>/<repo-name>.git
cd <repo-name>

# Then start Claude Code in that directory:
claude
```

Once inside Claude Code, it can read all files directly. This handoff doc gives it the context it can't get from reading the files alone (design decisions, UCI data, API contract rationale, bug fixes).

### Python dependencies (teammates' requirements.txt handles this)
```bash
pip install -r requirements.txt
# Key packages: flask, numpy, scipy, pandas
```

### Run the backend for local testing
```bash
# Option A: Teammates' real Flask server
flask run --host=0.0.0.0 --port=5000
# or: python app.py

# Option B: Joel's personal mock server (always works, no analysis)
python mock_server.py
```

---

## 3. File Ownership + Responsibilities — CRITICAL

### Joel's work (frontend + integration)
**What Joel is responsible for building:**
- The entire in-browser drawing experience — spiral canvas, S Pen capture, palm rejection, real-time telemetry
- UI/UX — instructions overlay, results panel, feature cards, tremor heatmap, gauge bars, demo presets
- Sending the drawing data to the backend (`POST /analyze`) and rendering whatever comes back
- USB debugging setup (adb reverse) and network architecture
- The API contract document that both sides agree to build against

**Joel owns these files. All work goes here:**
- `templates/index.html` — full app HTML
- `static/app.js` — all frontend logic
- `static/style.css` — all styles
- `mock_server.py` — personal test server (not for production)
- `ADB_SETUP.md` — USB debugging setup guide
- `contract.json` — API contract (for teammate coordination)
- `CLAUDE_CODE_HANDOFF.md` — this file

---

### Teammates' work (backend + ML)
**What teammates are responsible for building:**
- Receiving the drawing data from Joel's frontend
- Feature extraction from the raw x/y/t/p arrays — computing all 6 clinical features (dev_norm, vel_cv, dom_freq, tremor_pct, p_norm, p_cv)
- Comparing patient features against the UCI Parkinson's reference dataset (25 PD + 7 control files)
- Computing the 0–100 risk score and per-feature percentile_pd values
- Returning the JSON response that Joel's frontend displays
- Loading and preprocessing the UCI dataset into `references.json`

**Teammates own these files. DO NOT edit them:**
- `app.py` — Flask server + `/analyze` route
- `analysis.py` — feature extraction + scoring logic
- `references.json` — precomputed UCI reference statistics (means, stds, percentiles)
- `requirements.txt` — Python dependencies

If a bug is found in teammate files, flag it in a comment or tell Joel — do not silently fix it, as teammates are actively working on them.

---

## 4. Current State of All Files (as of session handoff)

### `templates/index.html` — COMPLETE (v2)
Full app HTML with:
- Topbar (68px height): DrawDx brand, live status strip, demo preset buttons (▶ Healthy / ▶ PD), Clear button, Analyze Spiral button
- Canvas container: `#spiral-canvas` for drawing, `#instructions-overlay` modal shown on first load
- Results panel (hidden until analysis): `#risk-score-block` with side-by-side risk number + tremor heatmap canvas, `#features-grid` for 6 feature cards (filled by JS), `#interpretation-block`, `#disclaimer-block`

### `static/app.js` — COMPLETE (v2, all bugs fixed)
~290 lines. All 6 Gemini-identified bugs fixed, 4 features added. See Section 6 for full bug list.

### `static/style.css` — COMPLETE (v2)
All CSS classes referenced by v2 app.js and index.html are defined. Topbar 68px, buttons min-height 48px (WCAG AAA for tremoring hands — deliberate, this is a PD tool).

### `mock_server.py` — COMPLETE
Personal test server. Returns hardcoded mock analysis response. Logs received data (point count, stroke count, avg pressure, canvas dims) for debugging. Runs on `0.0.0.0:5000` so it works with both adb reverse (localhost) and WiFi fallback.

### `contract.json` — COMPLETE
Full API contract document. Must be shared with teammates in Hour 1 of hackathon (or already has been). Contains request payload spec, response schema, and backend normalization notes.

### `ADB_SETUP.md` — COMPLETE
Step-by-step USB debugging + adb reverse setup guide. Covers Windows/Mac/Linux ADB install, enabling Developer Options on Galaxy Tab S10 FE, Chrome DevTools remote debugging instructions, phone hotspot fallback, troubleshooting table.

---

## 5. Network Architecture

### Primary: adb reverse over USB (preferred)
```bash
# On laptop terminal, once tablet is connected via USB-C:
adb reverse tcp:5000 tcp:5000
# Then on tablet in Chrome: http://localhost:5000
```
Why this beats WiFi:
- University/hackathon WiFi enforces AP client isolation (devices can't reach each other's IPs)
- `localhost` = Secure Context; `http://192.168.x.x` is not (matters for PointerEvent API)
- Zero WiFi dependency during judging
- Keeps tablet charged over USB
- <2ms latency

**Joel is getting a USB-C cable in ~40–45 minutes from when this doc was written.**

### Fallback A: Phone hotspot
Any team member's phone. Create hotspot, connect both laptop and tablet to it. Phone hotspot has no client isolation. Use `http://[laptop-ip]:5000`. Find laptop IP: `ipconfig | findstr IPv4` (Windows).

### Fallback B: ngrok
```bash
ngrok http 5000
# Copy the https://xxxx.ngrok.io URL → open on tablet
```
Gives a public HTTPS URL — Secure Context, works from anywhere.

### Chrome DevTools Remote Debugging (huge hackathon advantage)
While tablet is connected via USB:
1. Laptop Chrome → `chrome://inspect/#devices`
2. See Galaxy Tab S10 FE listed with its open tabs
3. Click "inspect" next to DrawDx tab
4. Full DevTools on laptop screen, connected to tablet browser
5. Console.log from app.js shows here; can set breakpoints; can inspect PointerEvent data live

---

## 6. PointerEvent API — Key Technical Facts

These are non-obvious and critical for the app to work correctly on the Galaxy Tab S10 FE with S Pen.

### Events used
```javascript
e.pointerType       // "pen" | "touch" | "mouse" — primary filter
e.pressure          // 0.0–1.0, REAL values from S Pen (not constant 0.5)
e.buttons === 1     // pen tip touching screen (gate for hover, where pressure=0)
e.getCoalescedEvents()  // exposes FULL 240Hz digitizer queue — MUST use this
canvas.setPointerCapture(e.pointerId)  // locks routing even outside canvas
```

### Critical: getCoalescedEvents()
Chrome dispatches `pointermove` at 60–90Hz display rate but **buffers all 240Hz S Pen samples** between frames. `e.getCoalescedEvents()` returns those buffered intermediate samples (3–4 per frame typically). **Must iterate ALL of them** for accurate FFT / tremor frequency analysis. Using only the main event loses ~70% of samples.

```javascript
const coalesced = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
for (const ce of coalesced) {
    // process ce.clientX, ce.clientY, ce.pressure, ce.timeStamp
}
```

### Pressure normalization — DO NOT multiply by 1023
Samsung One UI applies a non-linear sigmoid transfer curve to the S Pen's raw 4096 levels before the browser sees 0.0–1.0. UCI Parkinson's dataset was recorded on a Wacom Intuos digitizer (also 0–1023 raw, but linear). Multiplying `e.pressure * 1023` **will NOT** match UCI reference values.

**Use dimensionless ratios instead** — they cancel hardware-curve differences:
- `p_cv = std(p) / mean(p)` — coefficient of variation
- Zero-crossing rate of `dp/dt`
- Normalized pressure drop rate

### Palm rejection (4 layers)
1. `if (e.pointerType !== 'pen') return` — primary filter (Wacom EMR handles hardware-level rejection at ~1.5cm hover proximity; this filter alone is sufficient)
2. `touch-action: none` CSS — prevents browser intercepting events for scroll/zoom
3. `canvas.addEventListener('contextmenu', e => e.preventDefault())` — S Pen 400ms hold fires contextmenu + cancels pointer stream if not suppressed
4. `pointercancel` checks `e.pointerId === activePenPointerId` before wiping data

---

## 7. UCI Dataset — Reference Values

**Path on disk:** `/tmp/parkinson_data/hw_dataset/` (control/ and parkinson/ subdirectories)
**Format:** `X ; Y ; Z ; Pressure ; GripAngle ; Timestamp ; TestID` (semicolon-delimited)
**25 PD files** (all usable), **7 clean control files** (C_0002–C_0007, C_0009 — 8 of 15 control files have wrapped/corrupted timestamps, skip them)
**Pressure scale:** 0–1023 raw Wacom digitizer values
**Sampling rate:** ~111 Hz (PD group), ~143 Hz (control group)

### Feature Discrimination (Cohen's d from real UCI data)

| Feature | Control mean | PD mean | Cohen's d | p-value |
|---------|-------------|---------|-----------|---------|
| `dev_norm` (spiral deviation) | 0.414 | 0.629 | **2.54 VERY LARGE** | p<0.001 |
| `p_norm` (pressure normalized) | 0.848 | 0.569 | **2.19 VERY LARGE** | p<0.001 |
| `p_cv` (pressure variability) | 0.131 | 0.396 | **2.01 VERY LARGE** | p<0.001 |
| `tremor_pct` | 0.044 | 0.119 | **1.38 VERY LARGE** | p<0.05 |
| `dom_freq` | 7.6 Hz | 4.4 Hz | **1.07 LARGE** | p<0.01 |
| `vel_cv` (velocity variability) | 0.850 | 1.094 | **0.80 LARGE** | marginal |

These are the 6 features that `analysis.py` should compute and that `app.js` displays in the feature cards.

---

## 8. API Contract (exact format)

This is the agreed interface between Joel's frontend and teammates' backend. Full version in `contract.json`.

### POST /analyze

**Request body (parallel 1D arrays — ~85KB vs 240KB for array-of-objects):**
```json
{
  "x": [312.4, 314.1, 316.8],
  "y": [204.0, 206.3, 208.1],
  "t": [0.0, 4.2, 8.5],
  "p": [0.72, 0.74, 0.73],
  "s": [0, 0, 0],
  "canvas_width": 820,
  "canvas_height": 980,
  "device_pixel_ratio": 2.0,
  "pointer_type": "pen",
  "num_strokes": 1
}
```

Fields:
- `x`, `y` — CSS pixel coordinates (NOT physical pixels)
- `t` — DOMHighResTimeStamp in ms (use as-is for FFT interpolation)
- `p` — S Pen pressure 0.0–1.0 (real values)
- `s` — stroke index (increments on pen lift; 0-indexed)
- `canvas_width/height` — CSS pixel dimensions of canvas element
- `device_pixel_ratio` — typically 2.0 on Galaxy Tab S10 FE
- `pointer_type` — "pen" or "mouse" (backend should skip pressure features if "mouse")
- `num_strokes` — computed as `new Set(points.map(p => p.s)).size`

**Response:**
```json
{
  "risk_score": 71,
  "features": {
    "dev_norm":   {"value": 0.63, "ctrl_mean": 0.41, "pd_mean": 0.63, "percentile_pd": 68},
    "vel_cv":     {"value": 1.12, "ctrl_mean": 0.85, "pd_mean": 1.09, "percentile_pd": 55},
    "dom_freq":   {"value": 4.3,  "ctrl_mean": 7.6,  "pd_mean": 4.4,  "percentile_pd": 72},
    "tremor_pct": {"value": 0.11, "ctrl_mean": 0.04, "pd_mean": 0.12, "percentile_pd": 65},
    "p_norm":     {"value": 0.61, "ctrl_mean": 0.85, "pd_mean": 0.57, "percentile_pd": 55},
    "p_cv":       {"value": 0.38, "ctrl_mean": 0.13, "pd_mean": 0.40, "percentile_pd": 60}
  },
  "interpretation": "string — clinical narrative",
  "disclaimer": "Screening tool only. Not a clinical diagnosis."
}
```

**Backend normalization note:** Coordinate normalization before comparing to UCI:
```python
x_norm = (x - canvas_width/2) / (canvas_height/2)
y_norm = (y - canvas_height/2) / (canvas_height/2)
```
UCI uses digitizer pixel coordinates; normalize to same range before computing `dev_norm`.

---

## 9. All Bug Fixes Applied to app.js (v2)

All 6 bugs identified by Gemini review. **These are already fixed in the current app.js** — do not revert them.

### Bug #1 — Ink offset by 56–68px (critical)
- **Cause:** Raw `clientX/Y` measures from browser viewport top; canvas has `margin-top` for topbar height; ink renders shifted down from actual S Pen nib
- **Fix:** `const canvasRect = canvas.getBoundingClientRect(); const x = ce.clientX - canvasRect.left; const y = ce.clientY - canvasRect.top;`

### Bug #2 — Rendering gaps on fast strokes
- **Cause:** `getCoalescedEvents()` batches 3–4 points per frame; rendering was done AFTER the loop using only the last point, skipping all intermediate coalesced segments
- **Fix:** Move `ctx.beginPath()...ctx.stroke()` INSIDE the `for (const ce of coalesced)` loop

### Bug #3 — ctx.scale() compounds on resize
- **Cause:** Every `initCanvas()` call ran `ctx.scale(dpr, dpr)`, which multiplies the existing transform matrix — after 3 resizes: scale = dpr³
- **Fix:** `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)` — resets the matrix completely

### Bug #4 — num_strokes off-by-one
- **Cause:** `strokeIndex` variable could be wrong if edge cases occurred
- **Fix:** `new Set(points.map(pt => pt.s)).size` — computes directly from actual data, always correct

### Bug #5 — S Pen long-press fires contextmenu
- **Cause:** Holding S Pen still for 400ms triggers Android Chrome's context menu (Save Image/Share), which cancels the PointerEvent stream and kills the drawing
- **Fix:** `canvas.addEventListener('contextmenu', e => e.preventDefault())`

### Bug #6 — resetTest() resize race condition
- **Cause:** `initCanvas()` was called while `#canvas-container` was `display:none` → `getBoundingClientRect()` returned 0×0 → canvas initialized with zero dimensions
- **Fix:** Set `canvas-container` to `display: block` FIRST, then call `initCanvas()`

### Earlier bug (from previous session) — pointercancel wiped drawings
- **Cause:** `pointercancel` handler called `points.length = 0` on ANY cancel event; on Android, palm-to-pen transition fires `pointercancel` on the PALM's touch pointer ID
- **Fix:** `if (e.pointerType !== 'pen') return; if (e.pointerId !== activePenPointerId) return;` guards before any destructive action

---

## 10. Features Added to app.js (v2)

### Feature 1 — Live 240Hz telemetry strip
Status bar shows real-time sampling rate + pressure% + point count while drawing.
```
✓ S Pen  ⚡ 237 Hz  |  Pressure: 74%  |  1842 pts
```
Computed from last 30 points' timestamps. Proves S Pen is working to judges.

### Feature 2 — Tremor heatmap
On results screen, `#heatmap-canvas` shows the patient's actual drawing colored by smoothness:
- Green = smooth motion (<0.33 normalized velocity)
- Amber = moderate tremor (<0.67)
- Red = high tremor (≥0.67)
Velocities normalized to p5–p95 range (outlier-robust). Computed by `drawTremorHeatmap()` function called in `displayResults()`.

### Feature 3 — Range bars in feature cards
Each of the 6 feature cards has a green→amber→red gradient bar with a white dot showing where the patient's value falls between healthy and PD reference distributions. Computed from `percentile_pd` value returned by backend.

### Feature 4 — Demo presets (animated)
`loadDemo('pd')` and `loadDemo('control')` generate synthetic spiral data with clinically-accurate noise profiles:
- PD: 4–6 Hz tremor, high p_cv (~0.40), irregular pressure
- Control: 8–10 Hz baseline, low p_cv (~0.13), steady pressure

Animates at 25 points/frame via `requestAnimationFrame`. Fully drives the analysis pipeline — hits the server and shows real results. Essential for judge demos and testing without actual PD patients.

---

## 11. Canvas HiDPI Handling

Critically important for Galaxy Tab S10 FE (`devicePixelRatio = 2.0`).

```javascript
function initCanvas() {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width  = rect.width  * dpr;  // physical pixels
    canvas.height = rect.height * dpr;
    // setTransform RESETS matrix (ctx.scale COMPOUNDS on repeated calls)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Now all coordinates stay in CSS pixel space
}
```

All coordinates stored in `points[]` are CSS pixels. Backend receives CSS pixels + `device_pixel_ratio`. Backend normalizes by `canvas_width/height` (CSS pixels), not physical pixels.

---

## 12. Data Structure

```javascript
// Each point in the points[] array:
{ x: float,       // CSS pixel X, canvas-relative (canvasRect.left subtracted)
  y: float,       // CSS pixel Y, canvas-relative (canvasRect.top subtracted)
  t: float,       // DOMHighResTimeStamp in ms
  p: float,       // S Pen pressure 0.0–1.0
  s: int          // stroke index (0-indexed, increments on pointerup)
}

// Key state variables in app.js:
let points = [];           // all collected points, all strokes
let strokeIndex = 0;       // current stroke number, increments on pen lift
let isDrawing = false;     // true while pen tip is on screen
let activePenPointerId = null;  // guards pointercancel against false triggers
```

---

## 13. Spiral Template

Drawn by `drawSpiralTemplate()` on canvas init:
- Archimedean spiral: `r = b * θ`, `θ` from 0 to 4π (2 full turns)
- `b` computed from canvas size: `maxR = Math.min(w,h) * 0.42`, `b = maxR / (4*Math.PI)`
- Spiral drawn in light gray (`#e0e3ef`), 1.5px
- **Start zone:** 3 concentric circles at center (28px, 16px, 7px radii) for accessibility — tremoring patients need a large target
- **Finish zone:** Green ring at outer spiral endpoint
- **Labels:** "START" below center dot, "FINISH" below outer ring

---

## 14. What Still Needs Doing

### Immediate (before testing on tablet):
1. **Confirm teammates' `/analyze` endpoint matches contract.json** — compare their `app.py` route handler against the request/response schema in Section 8. They may have used a slightly different field name or response structure. This is the most likely integration issue.

2. **Test full flow on laptop first** (even without tablet):
   ```bash
   python mock_server.py
   # Open localhost:5000 in laptop browser
   # Click ▶ PD demo preset → wait for animation to finish → click Analyze Spiral
   # Verify results panel renders: risk score, heatmap, 6 feature cards with gauge bars
   ```

3. **When USB-C cable arrives:** `adb reverse tcp:5000 tcp:5000` → open `http://localhost:5000` on Galaxy Tab Chrome → draw actual spiral with S Pen → check telemetry strip shows real Hz + pressure values

### Pre-judging:
4. **Verify S Pen pressure varies** — open `https://hardwaretest.org/stylus-test/` on Galaxy Tab, check that pressure goes 0→1 as you press harder. If Chrome shows constant 0.5, try Samsung Internet (usually not an issue).

5. **Test all 3 demo presets** (▶ Healthy, ▶ PD) in front of judges — they hit the full analysis pipeline and show both outcomes without needing a PD patient present.

6. **Replace mock server disclaimer** — when teammates' backend is working, `mock_server.py` is no longer needed; app.js has a comment at `submitDrawing()` showing exactly where to swap the fetch URL.

---

## 15. Testing Checklist

```
[ ] mock_server.py runs on laptop
[ ] localhost:5000 loads in laptop browser
[ ] Instructions overlay appears on first load
[ ] "Begin Drawing" button dismisses overlay
[ ] Mouse drawing works (no ink offset)
[ ] Analyze button enables after 150 points
[ ] Mock analysis response populates results panel
[ ] Risk score number shows (not "—")
[ ] All 6 feature cards render with gauge bars
[ ] ▶ PD demo preset animates spiral correctly
[ ] ▶ Healthy demo preset animates spiral correctly
[ ] "Draw Again" button returns to canvas
[ ] adb reverse works (once cable arrives)
[ ] S Pen drawing on tablet: telemetry shows ~200+ Hz
[ ] S Pen pressure: telemetry shows varying %
[ ] S Pen long-press does NOT show context menu
[ ] Palm touch does NOT affect drawing
[ ] Real backend (/analyze) returns correct feature keys
```

---

## 16. Known Gotchas / Don't Repeat These Mistakes

1. **Never use `ctx.scale(dpr, dpr)` in initCanvas** — use `ctx.setTransform` or the transform compounds on every resize

2. **Never use raw `e.clientX / e.clientY`** — always subtract `canvasRect.left / canvasRect.top`

3. **Never render outside the `getCoalescedEvents()` loop** — gaps appear on fast strokes

4. **Never trust `strokeIndex` for `num_strokes`** — always use `new Set(points.map(p => p.s)).size`

5. **Never compare raw `e.pressure` values to UCI Wacom pressure values** — use dimensionless ratios (p_cv, zero-crossing rate of dp/dt)

6. **Never call `initCanvas()` while canvas-container is `display:none`** — getBoundingClientRect returns 0×0

7. **Always check `e.pointerId === activePenPointerId`** in `pointercancel` before wiping — palm-to-pen transitions fire cancel on the palm's touch pointer ID

---

## 17. Hackathon Context

- **Event:** natHacks 2026, Healthcare & Accessibility track
- **Duration:** 64 hours
- **AI policy:** AI assistance is explicitly allowed (confirmed at start of hackathon); no pre-hackathon code rule doesn't apply since this was all written after the hackathon started
- **Team structure:** Joel owns frontend (HTML/CSS/JS/mock server); teammates own Flask backend (app.py, analysis.py, references.json)
- **Demo plan:** Show both ▶ Healthy and ▶ PD presets to judges to demonstrate both outcomes without needing a PD patient present. Then draw live with S Pen if time allows.
- **Key selling point to judges:** Real UCI clinical dataset with Cohen's d > 2.0 on 3 features. Explainable features (not a black box). Runs in browser. Accessible UI designed with tremoring hands in mind (48px buttons, 68px topbar, large start target).

---

## 18. Styling Notes

CSS custom properties (defined in `:root`):
```css
--bg: #f4f6fb          /* page background */
--surface: #ffffff      /* card background */
--primary: #3d5a99     /* brand blue */
--primary-dk: #2c4175  /* hover state */
--topbar-h: 68px       /* topbar height — intentionally larger for accessibility */
--low: #2e7d52         /* green (healthy range) */
--moderate: #b07a1a    /* amber */
--high: #c0392b        /* red (PD range) */
```

Risk score band classes: `.band-low`, `.band-moderate`, `.band-high`
Feature percentile classes: `.pct-low`, `.pct-moderate`, `.pct-high`
Gauge pin position: `style="left: ${pinL}%"` where `pinL = Math.min(96, Math.max(4, percentile_pd))`

---

---

## 19. How Joel Wants to Work — READ THIS FIRST

**Before implementing anything non-trivial, propose first. Do not just build.**

The workflow Joel established in the previous session:

1. **Claude proposes** the approach — what it's about to do, the key decision, the tradeoff. Not code yet.
2. **Joel runs it by Gemini Pro** for an independent second opinion.
3. If **Gemini agrees** → Claude implements.
4. If **Gemini vetoes or raises a concern** → Joel brings the response back. Claude engages with the reasoning — if Gemini is right, acknowledge it and adjust; if Gemini is wrong or missing context, explain why and push back. Don't just accept every Gemini veto blindly.
5. **Then Claude writes code.**

This applies to: architecture decisions, new features, significant refactors, anything that affects the API contract or data format.

This does NOT apply to: small bug fixes where the problem and fix are clear-cut, typos, CSS tweaks, adding a comment.

The reason this works: two AI systems catching each other's blind spots. The previous session caught 6 real bugs and 4 feature improvements this way. It's worth the extra step.

---

*This document was generated from a full Claude session (claude.ai) that designed and built all three of Joel's frontend files from scratch, including 6 bug fixes and 4 features based on a Gemini architecture + code review pass. The session covered the full PointerEvent API, UCI dataset analysis, network architecture decisions, and pressure normalization. All decisions in this doc have been validated against the actual UCI data and the Samsung Galaxy Tab S10 FE PointerEvent behavior.*
