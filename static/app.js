// DrawDx frontend — spiral capture, telemetry, demo presets, results rendering.

const canvasContainer = document.getElementById('canvas-container');
const canvas = document.getElementById('spiral-canvas');
const ctx = canvas.getContext('2d');

const telemetryStrip = document.getElementById('telemetry-strip');
const clearBtn = document.getElementById('clear-btn');
const analyzeBtn = document.getElementById('analyze-btn');
const demoHealthyBtn = document.getElementById('demo-healthy-btn');
const demoPdBtn = document.getElementById('demo-pd-btn');
const drawAgainBtn = document.getElementById('draw-again-btn');
const beginDrawingBtn = document.getElementById('begin-drawing-btn');
const instructionsOverlay = document.getElementById('instructions-overlay');
const resultsPanel = document.getElementById('results-panel');
const drawWarning = document.getElementById('draw-warning');

const mainEl = document.querySelector('main');
const MIN_POINTS_TO_ANALYZE = 150;
const ANALYZE_ENDPOINT = '/analyze'; // served by 01/app.py (spiral scoring)

let points = [];          // {x, y, t, p, s} — all strokes, CSS-pixel coords relative to canvas
let strokeIndex = 0;
let isDrawing = false;
let activePenPointerId = null;
let spiralGeometry = null; // {cx, cy, b} set by drawSpiralTemplate(), reused by the heatmap
let lastInputLabel = 'S Pen';
let lastPointerType = 'pen'; // what actually gets reported to the backend — never hardcode this in the payload
let demoRunning = false;  // true while a demo recording is animating onto the canvas
let replayToken = 0;      // bumped on every reset; a replay stops once its token is stale

// ---------- device mode (Android S Pen vs iPad Apple Pencil) ----------

const deviceSelect = document.getElementById('device-select');

function detectPlatform() {
  const ua = navigator.userAgent;
  // iPadOS Safari reports itself as a Mac, so check for a touchscreen too
  const isIpad = /iPad|iPhone/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 0);
  return isIpad ? 'ios' : 'android';
}

function loadDeviceChoice() {
  try { return localStorage.getItem('drawdx-device') || 'auto'; } catch (_) { return 'auto'; }
}

function saveDeviceChoice(value) {
  try { localStorage.setItem('drawdx-device', value); } catch (_) { /* storage unavailable */ }
}

function currentPlatform() {
  return deviceSelect.value === 'auto' ? detectPlatform() : deviceSelect.value;
}

function penLabel() {
  return currentPlatform() === 'ios' ? 'Apple Pencil' : 'S Pen';
}

function applyDeviceMode() {
  document.querySelectorAll('.pen-name').forEach(el => { el.textContent = penLabel(); });
  if (points.length === 0) telemetryStrip.textContent = `Waiting for ${penLabel()}…`;
  if (lastPointerType === 'pen') lastInputLabel = penLabel();
}

deviceSelect.value = loadDeviceChoice();
deviceSelect.addEventListener('change', () => {
  saveDeviceChoice(deviceSelect.value);
  applyDeviceMode();
});

// iOS Safari ignores user-scalable=no; block pinch-zoom gestures directly
document.addEventListener('gesturestart', (e) => e.preventDefault());

// While the drawing view is up, block touch-scroll on the drawing area only (the Apple
// Pencil also fires touch events in Safari). Buttons are left alone so taps register.
document.addEventListener('touchmove', (e) => {
  if (mainEl.classList.contains('drawing-locked') && canvasContainer.contains(e.target)) {
    e.preventDefault();
  }
}, { passive: false });

const RISK_BAND_LOW_MAX = 34;
const RISK_BAND_MOD_MAX = 67;

// Match the UCI static spiral test the reference data was recorded on: ~3
// turns, clockwise from the center. The backend's deviation feature scores a
// perfectly drawn 2-turn spiral worse than the average healthy UCI subject
// (fewer turns biases its center estimate), so a 2-turn template made healthy
// people look PD-like before they'd drawn anything wrong.
const SPIRAL_TURNS = 3;
function spiralAngle(theta) {
  return -theta - Math.PI / 2; // starts pointing up, winds clockwise like the UCI files
}

// ---------- canvas setup ----------

// Canvas size the drawing was made on. Read from here at submit time: once
// results are showing the canvas is hidden and measures 0x0, and the backend
// scales coordinates by this size (a 0 size blew coordinates up ~580x).
let drawingCanvasSize = { width: 0, height: 0 };

function initCanvas() {
  const rect = canvas.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) {
    drawingCanvasSize = { width: rect.width, height: rect.height };
  }
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  // setTransform REPLACES the matrix — ctx.scale() would compound on every resize/reset call
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  redrawCanvas();
}

function redrawCanvas() {
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  drawSpiralTemplate();
  drawStrokes();
}

function drawSpiralTemplate() {
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  const cx = w / 2, cy = h / 2;
  const maxR = Math.min(w, h) * 0.42;
  const thetaMax = SPIRAL_TURNS * 2 * Math.PI;
  const b = maxR / thetaMax;
  spiralGeometry = { cx, cy, b };

  ctx.save();
  // Medium slate: the old #e0e3ef was ~1.3:1 contrast on white, too faint for older eyes
  ctx.strokeStyle = '#94a3b8';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let theta = 0; theta <= thetaMax; theta += 0.05) {
    const r = b * theta;
    const x = cx + r * Math.cos(spiralAngle(theta));
    const y = cy + r * Math.sin(spiralAngle(theta));
    if (theta === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // start zone: concentric circles, large target for tremoring hands
  ctx.fillStyle = '#3d5a99';
  [28, 16, 7].forEach((radius, i) => {
    ctx.globalAlpha = i === 2 ? 1 : 0.12;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
    ctx.fill();
  });
  ctx.globalAlpha = 1;

  // finish zone: green ring at outer endpoint
  const endX = cx + maxR * Math.cos(spiralAngle(thetaMax));
  const endY = cy + maxR * Math.sin(spiralAngle(thetaMax));
  ctx.strokeStyle = '#2e7d52';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.arc(endX, endY, 14, 0, 2 * Math.PI);
  ctx.stroke();

  ctx.fillStyle = '#6b7290';
  ctx.font = '12px -apple-system, Segoe UI, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('START', cx, cy + 46);
  ctx.fillText('FINISH', endX, endY + 28);
  ctx.restore();
}

function drawStrokes() {
  if (points.length < 2) return;
  ctx.save();
  ctx.strokeStyle = '#1c2333';
  ctx.lineWidth = 2.2;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  let started = false;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1], cur = points[i];
    if (prev.s !== cur.s) { started = false; continue; }
    if (!started) { ctx.beginPath(); ctx.moveTo(prev.x, prev.y); started = true; }
    ctx.lineTo(cur.x, cur.y);
  }
  ctx.stroke();
  ctx.restore();
}

// ---------- pointer capture ----------

canvas.addEventListener('contextmenu', (e) => e.preventDefault());

canvas.addEventListener('pointerdown', (e) => {
  if (e.pointerType === 'touch') return; // reject palm; 'pen' and 'mouse' (laptop testing) are allowed
  if (demoRunning) return; // don't mix live ink into a demo replay
  canvas.setPointerCapture(e.pointerId);
  activePenPointerId = e.pointerId;
  lastPointerType = e.pointerType;
  lastInputLabel = e.pointerType === 'pen' ? penLabel() : 'Mouse';
  isDrawing = true;
  hideDrawWarning();
  addPoint(e);
  dismissOverlayIfNeeded();
});

canvas.addEventListener('pointermove', (e) => {
  if (!isDrawing || e.pointerId !== activePenPointerId) return;
  if (e.buttons !== 1) return; // tip not touching (hover) or button released
  const coalesced = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
  const rect = canvas.getBoundingClientRect();
  for (const ce of coalesced) {
    const point = toPoint(ce, rect);
    points.push(point);
    paintSegment(point);
  }
  updateTelemetry();
  maybeEnableAnalyze();
});

canvas.addEventListener('pointerup', (e) => {
  if (e.pointerId !== activePenPointerId) return;
  isDrawing = false;
  strokeIndex += 1;
  showLiftedTelemetry();
});

canvas.addEventListener('pointercancel', (e) => {
  if (e.pointerType !== 'pen') return;
  if (e.pointerId !== activePenPointerId) return;
  isDrawing = false;
  strokeIndex += 1; // a cancelled contact is still a pen lift; reusing its s would join two contacts into one stroke
  showLiftedTelemetry();
});

function toPoint(e, rect) {
  return {
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
    t: e.timeStamp,
    p: e.pointerType === 'mouse' ? 0.5 : e.pressure,
    s: strokeIndex,
  };
}

function addPoint(e) {
  const rect = canvas.getBoundingClientRect();
  const point = toPoint(e, rect);
  points.push(point);
  paintSegment(point);
}

function paintSegment(point) {
  const prev = points.length >= 2 ? points[points.length - 2] : null;
  if (!prev || prev.s !== point.s) return;
  ctx.save();
  ctx.strokeStyle = '#1c2333';
  ctx.lineWidth = 2.2;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  ctx.moveTo(prev.x, prev.y);
  ctx.lineTo(point.x, point.y);
  ctx.stroke();
  ctx.restore();
}

function dismissOverlayIfNeeded() {
  if (!instructionsOverlay.classList.contains('hidden')) {
    instructionsOverlay.classList.add('hidden');
  }
}

// ---------- telemetry ----------

function updateTelemetry() {
  const sample = points.slice(-30);
  if (sample.length < 2) return;
  const dtMs = sample[sample.length - 1].t - sample[0].t;
  const hz = dtMs > 0 ? Math.round((sample.length - 1) / (dtMs / 1000)) : 0;
  const avgPressure = sample.reduce((sum, p) => sum + p.p, 0) / sample.length;
  const isMouse = lastPointerType === 'mouse';
  telemetryStrip.textContent = isMouse
    ? `⚠️ Mouse mode — pressure data is simulated, not real  |  ${hz} Hz  |  ${points.length} pts`
    : `✓ ${lastInputLabel}  ⚡ ${hz} Hz  |  Pressure: ${Math.round(avgPressure * 100)}%  |  ${points.length} pts`;
  telemetryStrip.classList.toggle('telemetry-warning', isMouse);
}

function maybeEnableAnalyze() {
  // Off while results are showing: re-tapping would re-send the same drawing as a new result.
  // Also off during a demo replay, which submits itself when it finishes.
  const resultsShowing = !resultsPanel.classList.contains('hidden');
  analyzeBtn.disabled = resultsShowing || demoRunning || points.length < MIN_POINTS_TO_ANALYZE;
}

function showLiftedTelemetry() {
  // Pressure while hovering/lifted isn't meaningful (and pointermove is gated
  // on e.buttons === 1 so no more points get recorded) — reflect "not
  // touching" explicitly instead of leaving the last pre-lift reading on
  // screen, which trails off to a few % rather than snapping to 0.
  if (lastPointerType === 'mouse') return; // mouse mode already shows its own message
  telemetryStrip.textContent =
    `✓ ${lastInputLabel} lifted  ⚡ Pressure: 0%  |  ${points.length} pts`;
  telemetryStrip.classList.remove('telemetry-warning');
}

// ---------- clear / reset ----------

clearBtn.addEventListener('click', resetCanvasState);

function resetCanvasState() {
  replayToken += 1; // stops any demo replay still animating
  demoRunning = false;
  points = [];
  strokeIndex = 0;
  isDrawing = false;
  activePenPointerId = null;
  hideDrawWarning();
  analyzeBtn.disabled = true;
  telemetryStrip.textContent = `Waiting for ${penLabel()}…`;
  telemetryStrip.classList.remove('telemetry-warning');
  redrawCanvas();
}

// Results are scrollable, the drawing view is not. Without resetting, Safari keeps the
// results' scroll position and snaps it back mid-drawing, shifting the canvas under the pen.
function showDrawingView() {
  resultsPanel.classList.add('hidden');
  mainEl.scrollTop = 0;
  window.scrollTo(0, 0);
  mainEl.classList.add('drawing-locked');
  canvasContainer.style.display = 'block';
}

drawAgainBtn.addEventListener('click', () => {
  showDrawingView(); // must be visible BEFORE initCanvas() or getBoundingClientRect() returns 0x0
  initCanvas();
  resetCanvasState();
});

// ---------- submit + analyze ----------

analyzeBtn.addEventListener('click', () => {
  const problem = drawingProblem();
  if (problem) {
    showDrawWarning(problem);
    return;
  }
  submitDrawing('live');
});

// The reference data (UCI static spiral test) was drawn over 14-48 s at firm
// pressure. On the tablet, drawings under ~10 s or at very light pressure
// produced healthy people's highest scores (calibration set: a 13%-pressure
// drawing still scored 100 after calibration), so those get redrawn instead
// of scored.
const MIN_DRAW_SECONDS = 10;
const MIN_MEDIAN_PRESSURE = 0.30;

function drawingProblem() {
  const counts = {};
  points.forEach(p => { counts[p.s] = (counts[p.s] || 0) + 1; });
  const longest = Number(Object.keys(counts).reduce((a, b) => (counts[a] >= counts[b] ? a : b)));
  const stroke = points.filter(p => p.s === longest);
  const seconds = (stroke[stroke.length - 1].t - stroke[0].t) / 1000;
  if (seconds < MIN_DRAW_SECONDS) {
    return `That took ${seconds.toFixed(0)} seconds. Tap Clear and redraw more slowly, at a steady pace for about 15–30 seconds.`;
  }
  if (lastPointerType === 'pen') {
    const sorted = stroke.map(p => p.p).sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];
    if (median < MIN_MEDIAN_PRESSURE) {
      return `The pen pressure was very light (${Math.round(median * 100)}%). Tap Clear and redraw, pressing firmly from the very start, as if writing with a pen.`;
    }
  }
  return null;
}

function showDrawWarning(text) {
  drawWarning.textContent = text;
  drawWarning.classList.remove('hidden');
}

function hideDrawWarning() {
  drawWarning.classList.add('hidden');
}

async function submitDrawing(source) {
  const payload = {
    x: points.map(p => p.x),
    y: points.map(p => p.y),
    t: points.map(p => p.t),
    p: points.map(p => p.p),
    s: points.map(p => p.s),
    canvas_width: drawingCanvasSize.width,
    canvas_height: drawingCanvasSize.height,
    device_pixel_ratio: window.devicePixelRatio || 1,
    pointer_type: lastPointerType, // real captured type — never hardcode; mouse data has no real pressure signal
    num_strokes: new Set(points.map(p => p.s)).size,
    // The backend picks its tablet calibration by this and saves every drawing under
    // it. Demo spirals are synthetic, so they must never be calibrated or end up in
    // a calibration set.
    device_platform: source === 'live' ? currentPlatform() : 'demo',
  };

  analyzeBtn.disabled = true;
  analyzeBtn.innerHTML = `${(window.tiIcon ? tiIcon('activity') : '')}Analyzing…`;
  try {
    const res = await fetch(ANALYZE_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    displayResults(data);
  } catch (err) {
    alert(`Analysis failed: ${err.message}`);
  } finally {
    analyzeBtn.innerHTML = `${(window.tiIcon ? tiIcon('activity') : '')}Analyze Spiral`;
    maybeEnableAnalyze();
  }
}

// ---------- results rendering ----------

function riskBand(score) {
  if (score < RISK_BAND_LOW_MAX) {
    return { cls: 'band-low', label: 'Within typical range' };
  }
  if (score < RISK_BAND_MOD_MAX) {
    return { cls: 'band-moderate', label: 'Borderline: consider a retest' };
  }
  return { cls: 'band-high', label: 'Elevated: consider a clinical review' };
}

// Band look shared with the tapping result: a Tabler tint, an icon and a word, never colour alone.
const BAND_UI = {
  'band-low': { word: 'Typical', icon: 'circle-check', bg: 'bg-green-lt' },
  'band-moderate': { word: 'Borderline', icon: 'alert-triangle', bg: 'bg-yellow-lt' },
  'band-high': { word: 'Elevated', icon: 'alert-octagon', bg: 'bg-red-lt' },
};
function bandUi(cls) { return BAND_UI[cls] || BAND_UI['band-low']; }
function bandHtml(cls, label) {
  const ui = bandUi(cls);
  let detail = String(label || '');
  if (detail.includes(':')) detail = detail.slice(detail.indexOf(':') + 1).trim();
  detail = detail.charAt(0).toUpperCase() + detail.slice(1);
  const icon = window.tiIcon ? tiIcon(ui.icon) : '';
  return `<span class="dx-band-word">${icon}${ui.word}</span>`
    + (detail ? `<span class="dx-band-detail">${escapeHtml(detail)}</span>` : '');
}

function pctBand(pct) {
  if (pct < RISK_BAND_LOW_MAX) return 'pct-low';
  if (pct < RISK_BAND_MOD_MAX) return 'pct-moderate';
  return 'pct-high';
}

function displayResults(data) {
  canvasContainer.style.display = 'none';
  mainEl.classList.remove('drawing-locked');
  mainEl.scrollTop = 0;
  resultsPanel.classList.remove('hidden');

  const scoreEl = document.getElementById('risk-score-number');
  const bandEl = document.getElementById('risk-band-label');
  countUp(scoreEl, Math.round(data.risk_score));
  const band = riskBand(data.risk_score);
  scoreEl.className = band.cls;
  bandEl.innerHTML = bandHtml(band.cls, band.label);
  bandEl.className = `dx-band ${band.cls}`;
  document.getElementById('risk-score-side').className = `card dx-banner ${bandUi(band.cls).bg}`;

  const grid = document.getElementById('features-grid');
  grid.innerHTML = '';

  const more = document.getElementById('spiral-more');
  if (more) more.open = false;   // each new result starts with the measurements folded away

  for (const [key, f] of Object.entries(data.features)) {
    const card = document.createElement('div');
    const band2 = f.scored === false ? 'pct-unscored' : pctBand(f.percentile_pd);
    card.className = `feature-card card ${band2}`;
    const pinLeft = gaugePosition(f);
    const fmt = v => escapeHtml(formatFeatureValue(key, v));
    const tag = f.scored === false ? '<span class="feature-tag">not in score</span>' : '';
    card.innerHTML = `<div class="card-body">
      <div class="feature-name card-title">${escapeHtml(featureLabel(key))}${tag}</div>
      <div class="feature-sub">${escapeHtml(featureDescription(key))}</div>
      <div class="feature-value">${fmt(f.value)}</div>
      <div class="gauge-track">
        <div class="gauge-tick" style="left:${GAUGE_HEALTHY}%"></div>
        <div class="gauge-tick" style="left:${GAUGE_PD}%"></div>
        <div class="gauge-pin" style="left:${pinLeft}%"></div>
      </div>
      <div class="feature-refs">
        <span style="left:${GAUGE_HEALTHY}%">Healthy avg ${fmt(f.ctrl_mean)}</span>
        <span style="left:${GAUGE_PD}%">PD avg ${fmt(f.pd_mean)}</span>
      </div>
    </div>`;
    grid.appendChild(card);
  }

  const warningsBlock = document.getElementById('warnings-block');
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  warningsBlock.replaceChildren(...warnings.map(w => {
    const li = document.createElement('li');
    li.textContent = w;
    return li;
  }));
  warningsBlock.classList.toggle('hidden', warnings.length === 0);

  // The backend also appends the warnings to the interpretation (" Note: <w1> <w2>"); they
  // already have their own list above, so drop that exact suffix rather than show them twice.
  let interpretation = data.interpretation || '';
  const noteSuffix = ' Note: ' + warnings.join(' ');
  if (warnings.length && interpretation.endsWith(noteSuffix)) {
    interpretation = interpretation.slice(0, -noteSuffix.length);
  }
  // Say what it was compared against, so the cohort size answers the first judge question.
  const tablet = { android: 'Galaxy Tab', ios: 'iPad' }[data.calibrated_for];
  const method = "Reference: 76 clinical recordings (15 healthy, 61 with Parkinson's)"
    + (tablet ? `, with a correction for how the ${tablet} reads pen input.` : '.');
  document.getElementById('interpretation-block').textContent = `${interpretation} ${method}`.trim();
  document.getElementById('disclaimer-block').textContent =
    data.disclaimer || 'Screening tool only. Not a clinical diagnosis.';

  const mockBadge = document.getElementById('mock-badge');
  if (data.is_mock) {
    mockBadge.textContent = 'MOCK DATA';
    mockBadge.classList.remove('badge-live');
    mockBadge.classList.remove('hidden');
  } else {
    mockBadge.textContent = 'LIVE · UCI reference (n=76)' + (tablet ? ' · tablet-calibrated' : '');
    mockBadge.classList.add('badge-live');
    mockBadge.classList.remove('hidden');
  }

  drawSteadinessHeatmap();
}

// Result numbers count up from 0 (about half a second), so the eye lands on them.
function countUp(el, target, ms = 550) {
  if (!el) return;
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce || !Number.isFinite(target)) { el.textContent = Math.round(target); return; }
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / ms);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(step);
  };
  el.textContent = '0';
  requestAnimationFrame(step);
  // animation frames pause while the page is hidden: never leave the number stuck part-way
  setTimeout(() => { el.textContent = Math.round(target); }, ms + 100);
}

// Feature bars: healthy average at 20%, Parkinson's average at 80%. Works for features
// where Parkinson's is lower too (dominant frequency): left is always healthy-like.
const GAUGE_HEALTHY = 20;
const GAUGE_PD = 80;

function gaugePosition(f) {
  const v = Number(f.value), h = Number(f.ctrl_mean), p = Number(f.pd_mean);
  if (![v, h, p].every(Number.isFinite) || p === h) return 50;
  const pos = GAUGE_HEALTHY + (GAUGE_PD - GAUGE_HEALTHY) * (v - h) / (p - h);
  return Math.min(97, Math.max(3, pos));
}

function featureDescription(key) {
  const text = {
    dev_norm: 'How far the line strayed from a smooth spiral',
    tremor_pct: 'Share of movement in the 4–6 Hz Parkinson\'s tremor rhythm',
    vel_cv: 'How much the pen speed varied',
    p_cv: 'How much the pen pressure varied',
    dom_freq: 'Main rhythm of the hand\'s shake',
  };
  return text[key] || '';
}

function featureLabel(key) {
  const labels = {
    dev_norm: 'Spiral Deviation',
    vel_cv: 'Speed Variability',
    dom_freq: 'Dominant Frequency',
    tremor_pct: 'Tremor Share',
    p_cv: 'Pressure Variability',
  };
  return labels[key] || key;
}

// Ratios as percentages with one decimal (no false precision), frequency in Hz.
function formatFeatureValue(key, value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return String(value ?? '');
  return key === 'dom_freq' ? `${v.toFixed(1)} Hz` : `${(v * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

// Results picture: the drawing over the faint template, each segment coloured by how much
// the line wobbled around its own smoothed path (deviation from a ±125 ms moving average,
// as a share of the drawing's size). Thresholds are absolute, not per-drawing percentiles,
// so a steady drawing stays green. Measured on real drawings: healthy UCI controls, the team
// and guests on both tablets keep 93-99% of points under 0.5%; Parkinson's recordings
// with tremor go well past it (top 1% of UCI Parkinson's points: 2.7%).
const WOBBLE_HALF_WINDOW_MS = 125;
const WOBBLE_SOME = 0.005;
const WOBBLE_STRONG = 0.01;

function wobbleByPoint() {
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const size = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1);
  const out = new Array(points.length).fill(0);
  let start = 0;
  while (start < points.length) {               // one stroke at a time
    let end = start;
    while (end + 1 < points.length && points[end + 1].s === points[start].s) end++;
    const cx = [0], cy = [0];                   // prefix sums for O(1) window means
    for (let i = start; i <= end; i++) {
      cx.push(cx[cx.length - 1] + points[i].x);
      cy.push(cy[cy.length - 1] + points[i].y);
    }
    let lo = start, hi = start;
    for (let i = start; i <= end; i++) {
      while (points[lo].t < points[i].t - WOBBLE_HALF_WINDOW_MS) lo++;
      while (hi + 1 <= end && points[hi + 1].t <= points[i].t + WOBBLE_HALF_WINDOW_MS) hi++;
      const n = hi - lo + 1;
      const mx = (cx[hi - start + 1] - cx[lo - start]) / n;
      const my = (cy[hi - start + 1] - cy[lo - start]) / n;
      out[i] = Math.hypot(points[i].x - mx, points[i].y - my) / size;
    }
    start = end + 1;
  }
  return out;
}

function drawSteadinessHeatmap() {
  const hm = document.getElementById('heatmap-canvas');
  const hctx = hm.getContext('2d');
  const rect = hm.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  hm.width = rect.width * dpr;
  hm.height = rect.height * dpr;
  hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  hctx.clearRect(0, 0, rect.width, rect.height);

  if (points.length < 2) return;

  // Fit both the drawing and the template into the box, with the same transform.
  const g = spiralGeometry;
  const thetaMax = SPIRAL_TURNS * 2 * Math.PI;
  const templateR = g ? g.b * thetaMax : 0;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (g) {
    minX = Math.min(minX, g.cx - templateR); maxX = Math.max(maxX, g.cx + templateR);
    minY = Math.min(minY, g.cy - templateR); maxY = Math.max(maxY, g.cy + templateR);
  }
  const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
  const scale = Math.min((rect.width - 20) / spanX, (rect.height - 20) / spanY);
  const offX = (rect.width - spanX * scale) / 2 - minX * scale;
  const offY = (rect.height - spanY * scale) / 2 - minY * scale;

  if (g) {
    hctx.strokeStyle = '#c3cad9';
    hctx.lineWidth = 1.5;
    hctx.beginPath();
    for (let theta = 0; theta <= thetaMax; theta += 0.05) {
      const r = g.b * theta;
      const x = (g.cx + r * Math.cos(spiralAngle(theta))) * scale + offX;
      const y = (g.cy + r * Math.sin(spiralAngle(theta))) * scale + offY;
      if (theta === 0) hctx.moveTo(x, y); else hctx.lineTo(x, y);
    }
    hctx.stroke();
  }

  const wobble = wobbleByPoint();
  hctx.lineWidth = 2.4;
  hctx.lineCap = 'round';
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (a.s !== b.s) continue;
    const w = Math.max(wobble[i - 1], wobble[i]);
    hctx.strokeStyle = w < WOBBLE_SOME ? '#2e7d52' : w < WOBBLE_STRONG ? '#b07a1a' : '#c0392b';
    hctx.beginPath();
    hctx.moveTo(a.x * scale + offX, a.y * scale + offY);
    hctx.lineTo(b.x * scale + offX, b.y * scale + offY);
    hctx.stroke();
  }
}

// ---------- demo presets ----------

// The demo buttons replay real recordings from the UCI reference dataset: a
// typical healthy control (C_0006, score 4) and a person with Parkinson's
// (H_P000-0003, score 77) whose score sits near the group's median (80) and who
// shows a classic 4.6 Hz tremor, so the steadiness picture has something real to
// show (scores with each person left out of the reference). Both run 17-19 s,
// inside the drawing-time guidance. They're sent as device_platform "demo", so no tablet calibration
// is applied — they were recorded on the UCI tablet, not this one.
demoHealthyBtn.addEventListener('click', () => loadDemo('healthy'));
demoPdBtn.addEventListener('click', () => loadDemo('pd'));

const DEMO_LABELS = { healthy: 'Real recording · healthy', pd: "Real recording · Parkinson's" };
let demoRecordings = null;

async function loadDemo(kind) {
  dismissOverlayIfNeeded();
  showDrawingView();
  initCanvas();
  resetCanvasState();
  lastInputLabel = DEMO_LABELS[kind];
  lastPointerType = 'pen';
  // Tapping a demo again, Clear or Draw Again resets the canvas, which bumps the token
  // and stops this replay, so two replays never draw into the same points[].
  const myToken = replayToken;
  demoRunning = true;
  maybeEnableAnalyze();

  try {
    demoRecordings = demoRecordings || await fetch('/static/demo_recordings.json').then(r => r.json());
  } catch (err) {
    if (myToken === replayToken) demoRunning = false;
    alert(`Could not load the demo recording: ${err.message}`);
    return;
  }
  if (myToken !== replayToken) return;
  const replay = fitRecordingToCanvas(demoRecordings[kind]);
  let i = 0;
  const pointsPerFrame = 40; // ~1-2 s of animation for a 20-30 s recording

  function step() {
    if (myToken !== replayToken) return;
    const end = Math.min(i + pointsPerFrame, replay.length);
    for (; i < end; i++) {
      points.push(replay[i]);
      paintSegment(replay[i]);
    }
    updateTelemetry();
    maybeEnableAnalyze();
    if (i < replay.length) {
      requestAnimationFrame(step);
    } else {
      strokeIndex = 1;
      demoRunning = false;
      submitDrawing(kind);
    }
  }
  requestAnimationFrame(step);
}

// Place a recording on the on-screen template: its start point on START, its
// outer radius at the template's, and its end rotated onto FINISH. Translation,
// uniform scaling and rotation don't change any of the features (all are
// size- and orientation-independent), so the score is the recording's own.
function fitRecordingToCanvas(rec) {
  const rect = canvas.getBoundingClientRect();
  const cx = rect.width / 2, cy = rect.height / 2;
  const maxR = Math.min(rect.width, rect.height) * 0.42;

  const x0 = rec.x[0], y0 = rec.y[0];
  const n = rec.x.length;
  let recMaxR = 0;
  for (let i = 0; i < n; i++) recMaxR = Math.max(recMaxR, Math.hypot(rec.x[i] - x0, rec.y[i] - y0));
  const scale = maxR / recMaxR;
  const endAngle = Math.atan2(rec.y[n - 1] - y0, rec.x[n - 1] - x0);
  const rot = spiralAngle(SPIRAL_TURNS * 2 * Math.PI) - endAngle;
  const cosR = Math.cos(rot), sinR = Math.sin(rot);

  const tStart = performance.now();
  const out = [];
  for (let i = 0; i < n; i++) {
    const dx = (rec.x[i] - x0) * scale, dy = (rec.y[i] - y0) * scale;
    out.push({
      x: cx + dx * cosR - dy * sinR,
      y: cy + dx * sinR + dy * cosR,
      t: tStart + rec.t[i],
      p: Math.min(1, Math.max(0, rec.p[i] / 1023)),
      s: 0,
    });
  }
  return out;
}

// ---------- boot ----------

beginDrawingBtn.addEventListener('click', () => {
  instructionsOverlay.classList.add('hidden');
  enterFullscreen();
});

// Hide the browser bars and the Android dock while drawing: more canvas, and a resting
// hand can't hit Home/Back. Needs a tap (this button), and some browsers refuse it, so
// failure is ignored. The ResizeObserver below re-fits the canvas when the size changes.
function enterFullscreen() {
  const el = document.documentElement;
  if (document.fullscreenElement || document.webkitFullscreenElement) return;
  try {
    const request = el.requestFullscreen || el.webkitRequestFullscreen;
    const result = request && request.call(el);
    if (result && typeof result.catch === 'function') result.catch(() => {});
  } catch (_) { /* fullscreen not allowed here */ }
}

// Resize the canvas whenever its box actually changes size (rotation, Safari toolbar).
// ResizeObserver fires after layout, unlike 'resize' on iOS Safari, which can fire
// before the new size is known and leave the canvas stretched/offset.
let lastCanvasWidth = 0, lastCanvasHeight = 0;
new ResizeObserver(() => {
  if (canvasContainer.style.display === 'none') return;
  const r = canvas.getBoundingClientRect();
  const w = Math.round(r.width), h = Math.round(r.height);
  if (w === 0 || h === 0 || (w === lastCanvasWidth && h === lastCanvasHeight)) return;
  const rotated = lastCanvasWidth !== 0 && w !== lastCanvasWidth;
  lastCanvasWidth = w;
  lastCanvasHeight = h;
  initCanvas();
  // a width change means the tablet was rotated: the spiral moved, so old strokes no longer line up
  if (rotated && points.length > 0) resetCanvasState();
}).observe(canvasContainer);

applyDeviceMode();
mainEl.classList.add('drawing-locked');
initCanvas();
