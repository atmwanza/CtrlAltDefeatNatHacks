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
  lastInputLabel = e.pointerType === 'pen' ? 'S Pen' : 'Mouse';
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
});

canvas.addEventListener('pointercancel', (e) => {
  if (e.pointerType !== 'pen') return;
  if (e.pointerId !== activePenPointerId) return;
  isDrawing = false;
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
  telemetryStrip.textContent =
    `✓ ${lastInputLabel}  ⚡ ${hz} Hz  |  Pressure: ${Math.round(avgPressure * 100)}%  |  ${points.length} pts`;
}

function maybeEnableAnalyze() {
  analyzeBtn.disabled = points.length < MIN_POINTS_TO_ANALYZE;
}

// ---------- clear / reset ----------

clearBtn.addEventListener('click', resetCanvasState);

function resetCanvasState() {
  points = [];
  strokeIndex = 0;
  isDrawing = false;
  activePenPointerId = null;
  analyzeBtn.disabled = true;
  telemetryStrip.textContent = 'Waiting for S Pen…';
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
    pointer_type: source === 'live' ? 'pen' : 'pen',
    num_strokes: new Set(points.map(p => p.s)).size,
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
  if (score < 34) return { cls: 'band-low', label: 'Low risk indicators' };
  if (score < 67) return { cls: 'band-moderate', label: 'Moderate risk indicators' };
  return { cls: 'band-high', label: 'High risk indicators' };
}

function pctBand(pct) {
  if (pct < 34) return 'pct-low';
  if (pct < 67) return 'pct-moderate';
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
  const tremorHz = isPd ? 4 + Math.random() * 2 : 8 + Math.random() * 2;
  const pressureCv = isPd ? 0.40 : 0.13;
  const pressureBase = 0.6;

  const out = [];
  let t = performance.now();
  for (let i = 0; i < n; i++) {
    const frac = i / (n - 1);
    const theta = thetaMax * frac;
    const tremor = isPd ? (Math.sin(theta * (tremorHz / 2)) * maxR * 0.02) : 0;
    const r = b * theta + tremor;
    const x = cx + r * Math.cos(theta - Math.PI / 2);
    const y = cy + r * Math.sin(theta - Math.PI / 2);
    const noise = () => (Math.random() - 0.5) * pressureCv * pressureBase * 2;
    const p = Math.min(1, Math.max(0.05, pressureBase + noise()));
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

initCanvas();
