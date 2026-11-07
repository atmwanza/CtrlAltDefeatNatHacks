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

const MIN_POINTS_TO_ANALYZE = 150;
const ANALYZE_ENDPOINT = '/analyze'; // swap to teammates' real backend URL once /analyze is live; mock_server.py answers this today

let points = [];          // {x, y, t, p, s} — all strokes, CSS-pixel coords relative to canvas
let strokeIndex = 0;
let isDrawing = false;
let activePenPointerId = null;
let spiralGeometry = null; // {cx, cy, b} set by drawSpiralTemplate(), reused by the heatmap
let lastInputLabel = 'S Pen';
let lastPointerType = 'pen'; // what actually gets reported to the backend — never hardcode this in the payload

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

const RISK_BAND_LOW_MAX = 34;
const RISK_BAND_MOD_MAX = 67;

// ---------- canvas setup ----------

function initCanvas() {
  const rect = canvas.getBoundingClientRect();
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
  const turns = 2;
  const thetaMax = turns * 2 * Math.PI;
  const b = maxR / thetaMax;
  spiralGeometry = { cx, cy, b };

  ctx.save();
  ctx.strokeStyle = '#e0e3ef';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let theta = 0; theta <= thetaMax; theta += 0.05) {
    const r = b * theta;
    const x = cx + r * Math.cos(theta - Math.PI / 2);
    const y = cy + r * Math.sin(theta - Math.PI / 2);
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
  const endX = cx + maxR * Math.cos(thetaMax - Math.PI / 2);
  const endY = cy + maxR * Math.sin(thetaMax - Math.PI / 2);
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
  canvas.setPointerCapture(e.pointerId);
  activePenPointerId = e.pointerId;
  lastPointerType = e.pointerType;
  lastInputLabel = e.pointerType === 'pen' ? penLabel() : 'Mouse';
  isDrawing = true;
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
  analyzeBtn.disabled = points.length < MIN_POINTS_TO_ANALYZE;
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
  points = [];
  strokeIndex = 0;
  isDrawing = false;
  activePenPointerId = null;
  analyzeBtn.disabled = true;
  telemetryStrip.textContent = `Waiting for ${penLabel()}…`;
  redrawCanvas();
}

drawAgainBtn.addEventListener('click', () => {
  resultsPanel.classList.add('hidden');
  canvasContainer.style.display = 'block'; // must be visible BEFORE initCanvas() or getBoundingClientRect() returns 0x0
  initCanvas();
  resetCanvasState();
});

// ---------- submit + analyze ----------

analyzeBtn.addEventListener('click', () => submitDrawing('live'));

async function submitDrawing(source) {
  const rect = canvas.getBoundingClientRect();
  const payload = {
    x: points.map(p => p.x),
    y: points.map(p => p.y),
    t: points.map(p => p.t),
    p: points.map(p => p.p),
    s: points.map(p => p.s),
    canvas_width: rect.width,
    canvas_height: rect.height,
    device_pixel_ratio: window.devicePixelRatio || 1,
    pointer_type: lastPointerType, // real captured type — never hardcode; mouse data has no real pressure signal
    num_strokes: new Set(points.map(p => p.s)).size,
    device_platform: currentPlatform()
  };

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = 'Analyzing…';
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
    analyzeBtn.textContent = 'Analyze Spiral';
    analyzeBtn.disabled = points.length < MIN_POINTS_TO_ANALYZE;
  }
}

// ---------- results rendering ----------

function riskBand(score) {
  if (score < RISK_BAND_LOW_MAX) {
    return { cls: 'band-low', label: 'Within normal reference range' };
  }
  if (score < RISK_BAND_MOD_MAX) {
    return { cls: 'band-moderate', label: 'Borderline kinematic deviation' };
  }
  return { cls: 'band-high', label: 'Elevated kinematic deviation' };
}

function pctBand(pct) {
  if (pct < RISK_BAND_LOW_MAX) return 'pct-low';
  if (pct < RISK_BAND_MOD_MAX) return 'pct-moderate';
  return 'pct-high';
}

function displayResults(data) {
  canvasContainer.style.display = 'none';
  resultsPanel.classList.remove('hidden');

  const scoreEl = document.getElementById('risk-score-number');
  const bandEl = document.getElementById('risk-band-label');
  scoreEl.textContent = Math.round(data.risk_score);
  const band = riskBand(data.risk_score);
  scoreEl.className = band.cls;
  bandEl.textContent = band.label;
  bandEl.className = band.cls;

  const grid = document.getElementById('features-grid');
  grid.innerHTML = '';
  for (const [key, f] of Object.entries(data.features)) {
    const card = document.createElement('div');
    const band2 = pctBand(f.percentile_pd);
    card.className = `feature-card ${band2}`;
    const pinLeft = Math.min(96, Math.max(4, f.percentile_pd));
    card.innerHTML = `
      <div class="feature-name">${featureLabel(key)}</div>
      <div class="feature-value">${f.value}</div>
      <div class="gauge-track"><div class="gauge-pin" style="left:${pinLeft}%"></div></div>
      <div class="feature-refs"><span>ctrl ${f.ctrl_mean}</span><span>PD ${f.pd_mean}</span></div>
    `;
    grid.appendChild(card);
  }

  document.getElementById('interpretation-block').textContent = data.interpretation || '';
  document.getElementById('disclaimer-block').textContent =
    data.disclaimer || 'Screening tool only. Not a clinical diagnosis.';

  const mockBadge = document.getElementById('mock-badge');
  if (data.is_mock) {
    mockBadge.textContent = 'MOCK DATA';
    mockBadge.classList.remove('badge-live');
    mockBadge.classList.remove('hidden');
  } else if (data.backend_label) {
    mockBadge.textContent = data.backend_label;
    mockBadge.classList.add('badge-live');
    mockBadge.classList.remove('hidden');
  } else {
    mockBadge.classList.add('hidden');
  }

  drawTremorHeatmap();
}

function featureLabel(key) {
  const labels = {
    dev_norm: 'Spiral Deviation',
    vel_cv: 'Velocity Variability',
    dom_freq: 'Dominant Frequency',
    tremor_pct: 'Tremor Share',
    p_norm: 'Pressure Level',
    p_cv: 'Pressure Variability',
  };
  return labels[key] || key;
}

function drawTremorHeatmap() {
  const hm = document.getElementById('heatmap-canvas');
  const hctx = hm.getContext('2d');
  const rect = hm.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  hm.width = rect.width * dpr;
  hm.height = rect.height * dpr;
  hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  hctx.clearRect(0, 0, rect.width, rect.height);

  if (points.length < 2) return;

  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
  const scale = Math.min((rect.width - 20) / spanX, (rect.height - 20) / spanY);
  const offX = (rect.width - spanX * scale) / 2 - minX * scale;
  const offY = (rect.height - spanY * scale) / 2 - minY * scale;

  const velocities = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (a.s !== b.s) { velocities.push(0); continue; }
    const dt = Math.max(b.t - a.t, 1);
    velocities.push(Math.hypot(b.x - a.x, b.y - a.y) / dt);
  }
  const sorted = [...velocities].sort((a, b) => a - b);
  const p5 = sorted[Math.floor(sorted.length * 0.05)] || 0;
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || 1;
  const range = Math.max(p95 - p5, 1e-6);

  hctx.lineWidth = 2.4;
  hctx.lineCap = 'round';
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (a.s !== b.s) continue;
    const norm = Math.min(1, Math.max(0, (velocities[i - 1] - p5) / range));
    hctx.strokeStyle = norm < 0.33 ? '#2e7d52' : norm < 0.67 ? '#b07a1a' : '#c0392b';
    hctx.beginPath();
    hctx.moveTo(a.x * scale + offX, a.y * scale + offY);
    hctx.lineTo(b.x * scale + offX, b.y * scale + offY);
    hctx.stroke();
  }
}

// ---------- demo presets ----------

demoHealthyBtn.addEventListener('click', () => loadDemo('control'));
demoPdBtn.addEventListener('click', () => loadDemo('pd'));

function loadDemo(kind) {
  dismissOverlayIfNeeded();
  resultsPanel.classList.add('hidden');
  canvasContainer.style.display = 'block';
  initCanvas();
  resetCanvasState();
  lastInputLabel = 'Demo';
  lastPointerType = 'pen'; // synthetic data is generated to be pen-like (full pressure range), so report it as such

  const synthetic = generateSyntheticSpiral(kind);
  let i = 0;
  const pointsPerFrame = 25;

  function step() {
    const end = Math.min(i + pointsPerFrame, synthetic.length);
    for (; i < end; i++) {
      points.push(synthetic[i]);
      paintSegment(synthetic[i]);
    }
    updateTelemetry();
    maybeEnableAnalyze();
    if (i < synthetic.length) {
      requestAnimationFrame(step);
    } else {
      strokeIndex = 1;
      submitDrawing(kind);
    }
  }
  requestAnimationFrame(step);
}

function generateSyntheticSpiral(kind) {
  const rect = canvas.getBoundingClientRect();
  const cx = rect.width / 2, cy = rect.height / 2;
  const maxR = Math.min(rect.width, rect.height) * 0.42;
  const turns = 2;
  const thetaMax = turns * 2 * Math.PI;
  const b = maxR / thetaMax;

  const isPd = kind === 'pd';
  const durationMs = isPd ? 9000 : 6000;
  const hz = 200;
  const n = Math.round((durationMs / 1000) * hz);
  // Hz here means oscillations per second of WALL-CLOCK TIME, matching what a
  // real backend's FFT measures — phase must be driven by tSec, not by spiral
  // angle, or the "4-6Hz tremor" ends up at a fraction of a Hz once drawn out
  // over several seconds (caught in review: theta-driven phase is dimensionally
  // wrong for a temporal frequency target).
  const tremorHz = isPd ? 4.3 + Math.random() * 1.5 : 8 + Math.random() * 2;
  const tremorAmpPx = isPd ? maxR * 0.028 : maxR * 0.004;
  const tremorAxis = Math.PI / 3.3; // fixed direction, not purely radial — radial-only wobble draws a symmetric gear/flower, not a hand tremor
  const pressureMean = isPd ? 0.58 : 0.84;
  const pressureAmp = isPd ? 0.33 : 0.15; // sized so std/mean lands near the target p_cv (0.40 / 0.13)

  const out = [];
  let t = performance.now();
  for (let i = 0; i < n; i++) {
    const tSec = i / hz;
    const frac = i / (n - 1);
    const theta = thetaMax * frac;
    const phase = 2 * Math.PI * tremorHz * tSec;
    const wobble = Math.sin(phase);

    const idealR = b * theta;
    const idealX = cx + idealR * Math.cos(theta - Math.PI / 2);
    const idealY = cy + idealR * Math.sin(theta - Math.PI / 2);
    const x = idealX + tremorAmpPx * wobble * Math.cos(tremorAxis);
    const y = idealY + tremorAmpPx * wobble * Math.sin(tremorAxis);

    // Pressure rides the same tremor phase instead of independent per-sample
    // noise — a hand can't modulate grip at 200Hz, so white noise there looked
    // like fuzz rather than a 4-6Hz pulse.
    const p = Math.min(1, Math.max(0.05, pressureMean + pressureAmp * Math.sin(phase + 0.6)));
    out.push({ x, y, t, p, s: 0 });
    t += 1000 / hz;
  }
  return out;
}

// ---------- boot ----------

beginDrawingBtn.addEventListener('click', () => instructionsOverlay.classList.add('hidden'));

window.addEventListener('resize', () => {
  if (canvasContainer.style.display !== 'none') initCanvas();
});

applyDeviceMode();
initCanvas();
