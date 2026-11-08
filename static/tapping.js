// DrawDx finger-tapping prototype (MDS-UPDRS 3.4): tablet side.
// The laptop backend drives the camera (Raspberry Pi, or the laptop webcam fallback);
// this page only starts recordings, shows a preview and renders results. Loaded after
// app.js, whose globals (canvasContainer, resultsPanel, mainEl, showDrawingView,
// initCanvas, escapeHtml) it reuses for switching between the two tests.

(() => {
  const TAP_SECONDS = 10;
  const COUNTDOWN = ['3', '2', '1'];
  const PREVIEW_MS = 500;
  const HEALTH_MS = 2000;
  const STATUS_MS = 500;
  const STATUS_TIMEOUT_MS = 90000;

  const $ = id => document.getElementById(id);
  const panel = $('tapping-panel');
  const spiralTab = $('mode-spiral-btn');
  const tappingTab = $('mode-tapping-btn');
  const cameraBadge = $('tap-camera-badge');
  const preview = $('tap-preview');
  const previewEmpty = $('tap-preview-empty');
  const overlay = $('tap-overlay');
  const rightBtn = $('tap-right-btn');
  const leftBtn = $('tap-left-btn');
  const progress = $('tap-progress');
  const progressBar = $('tap-progress-bar');
  const message = $('tap-message');
  const resultsEl = $('tap-results');
  const asymEl = $('tap-asymmetry');

  let active = false;          // tapping view showing
  let cameraReady = false;
  let running = false;         // a recording/analysis is in progress
  let previewTimer = null;
  let healthTimer = null;
  let spiralResultsWereShowing = false;
  const results = { right: null, left: null };

  // ---------- switching between the spiral and tapping tests ----------

  function setTabs(tapping) {
    spiralTab.classList.toggle('active', !tapping);
    tappingTab.classList.toggle('active', tapping);
    spiralTab.setAttribute('aria-selected', String(!tapping));
    tappingTab.setAttribute('aria-selected', String(tapping));
  }

  function showTapping() {
    if (active) return;
    active = true;
    setTabs(true);
    spiralResultsWereShowing = !resultsPanel.classList.contains('hidden');
    document.body.classList.add('mode-tapping');
    canvasContainer.style.display = 'none';
    resultsPanel.classList.add('hidden');
    mainEl.classList.remove('drawing-locked');   // results below can scroll
    mainEl.scrollTop = 0;
    panel.classList.remove('hidden');
    checkHealth();
    healthTimer = setInterval(checkHealth, HEALTH_MS);
    startPreview();
  }

  function showSpiral() {
    if (!active || running) return;
    active = false;
    setTabs(false);
    stopPreview();
    clearInterval(healthTimer);
    panel.classList.add('hidden');
    document.body.classList.remove('mode-tapping');
    if (spiralResultsWereShowing) {
      resultsPanel.classList.remove('hidden');
    } else {
      showDrawingView();   // must be visible before initCanvas() measures it
      initCanvas();        // redraws the template and any ink already on the canvas
    }
  }

  spiralTab.addEventListener('click', showSpiral);
  tappingTab.addEventListener('click', showTapping);

  // ---------- camera status + preview ----------

  async function checkHealth() {
    try {
      const h = await fetch('/health', { cache: 'no-store' }).then(r => r.json());
      cameraReady = !!h.capture_ready;
      const names = { picamera: 'Pi camera', webcam: 'laptop webcam', synthetic: 'test source' };
      const label = names[h.capture_source] || 'camera';
      cameraBadge.textContent = cameraReady ? `● ${label} connected` : '● Camera not connected';
      cameraBadge.classList.toggle('ok', cameraReady);
    } catch (_) {
      cameraReady = false;
      cameraBadge.textContent = '● Server not reachable';
      cameraBadge.classList.remove('ok');
    }
    updateButtons();
    if (!running && !cameraReady) {
      setMessage('Waiting for the camera. Start the Pi, or run the webcam capture on the laptop.', 'warn');
    } else if (!running && message.dataset.kind === 'warn' && message.textContent.startsWith('Waiting')) {
      setMessage('');
    }
  }

  function startPreview() {
    stopPreview();
    const tick = () => {
      if (!active || running || !cameraReady) return;
      preview.src = `/tapping/preview.jpg?t=${Date.now()}`;
    };
    tick();
    previewTimer = setInterval(tick, PREVIEW_MS);
  }

  function stopPreview() {
    clearInterval(previewTimer);
    previewTimer = null;
  }

  preview.addEventListener('load', () => { previewEmpty.classList.add('hidden'); });
  preview.addEventListener('error', () => { if (!running) previewEmpty.classList.remove('hidden'); });

  function updateButtons() {
    const disabled = running || !cameraReady;
    rightBtn.disabled = disabled;
    leftBtn.disabled = disabled;
    spiralTab.disabled = running;
  }

  function setMessage(text, kind = '') {
    message.textContent = text;
    message.dataset.kind = kind;
    message.className = `tap-message ${kind}`;
  }

  // ---------- one recording: countdown -> record -> analyse -> show ----------

  rightBtn.addEventListener('click', () => runHand('right'));
  leftBtn.addEventListener('click', () => runHand('left'));

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  async function runHand(hand) {
    if (running || !cameraReady) return;
    running = true;
    updateButtons();
    stopPreview();
    setMessage(`${capitalise(hand)} hand: get ready…`);

    overlay.classList.remove('hidden');
    for (const n of COUNTDOWN) {
      overlay.textContent = n;
      await sleep(1000);
    }
    overlay.textContent = 'GO!';

    let sid;
    try {
      const res = await fetch('/tapping/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hand, duration_s: TAP_SECONDS }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Server returned ${res.status}`);
      sid = body.session_id;
    } catch (err) {
      return finish(`Could not start recording: ${err.message}`, 'error');
    }

    setMessage('Recording: keep tapping, as fast and as big as you can.', 'live');
    progress.classList.remove('hidden');
    const t0 = performance.now();
    // timer, not requestAnimationFrame: rAF pauses in background tabs and would stall the flow
    await new Promise(resolve => {
      const timer = setInterval(() => {
        const f = Math.min(1, (performance.now() - t0) / (TAP_SECONDS * 1000));
        progressBar.style.width = `${f * 100}%`;
        if (f > 0.1) overlay.textContent = 'Tap!';
        if (f >= 1) { clearInterval(timer); resolve(); }
      }, 100);
    });
    overlay.textContent = 'Stop';
    setMessage('Analysing…');

    const job = await pollStatus(sid);
    if (job.state !== 'done') {
      return finish(job.error || 'The recording did not come back from the camera.', 'error');
    }
    results[hand] = job.result;
    renderResults();
    const r = job.result;
    finish(r.valid
      ? `${capitalise(hand)} hand done.${results.right && results.left ? '' : ` Now the ${hand === 'right' ? 'left' : 'right'} hand.`}`
      : `${capitalise(hand)} hand: ${(r.warnings || ['measurement not reliable'])[0]} Try again.`,
      r.valid ? 'ok' : 'warn');
  }

  async function pollStatus(sid) {
    const deadline = performance.now() + STATUS_TIMEOUT_MS;
    while (performance.now() < deadline) {
      try {
        const job = await fetch(`/tapping/status/${sid}`, { cache: 'no-store' }).then(r => r.json());
        if (job.state === 'done' || job.state === 'error') return job;
        if (job.state === 'analyzing') setMessage('Analysing the video…');
      } catch (_) { /* transient: keep polling */ }
      await sleep(STATUS_MS);
    }
    return { state: 'error', error: 'Timed out waiting for the analysis.' };
  }

  function finish(text, kind) {
    running = false;
    overlay.classList.add('hidden');
    progress.classList.add('hidden');
    progressBar.style.width = '0%';
    setMessage(text, kind);
    updateButtons();
    startPreview();
  }

  const capitalise = s => s.charAt(0).toUpperCase() + s.slice(1);

  // ---------- results ----------

  const METRICS = [
    { key: 'rate_hz', label: 'Tapping speed', fmt: v => `${v.toFixed(1)} taps/s`,
      help: 'Taps per second' },
    { key: 'amp_mean', label: 'Opening size', fmt: v => `${v.toFixed(2)} palm`,
      help: 'Average finger opening, in palm lengths' },
    { key: 'decrement_pct_per_tap', label: 'Size change', fmt: v => `${v > 0 ? '+' : ''}${v.toFixed(1)}%/tap`,
      help: 'How the opening shrank (−) or grew (+) tap by tap' },
    { key: 'last3_first3', label: 'Last vs first taps', fmt: v => `${Math.round(v * 100)}%`,
      help: 'Size of the last 3 taps vs the first 3' },
    { key: 'iti_cv', label: 'Rhythm variability', fmt: v => `${(v * 100).toFixed(0)}%`,
      help: 'How uneven the time between taps was' },
    { key: 'hesitations', label: 'Hesitations', fmt: v => `${v}`,
      help: 'Pauses longer than twice the usual gap' },
  ];

  function renderResults() {
    resultsEl.innerHTML = '';
    for (const hand of ['right', 'left']) {
      const r = results[hand];
      if (!r) continue;
      resultsEl.appendChild(handCard(hand, r));
    }
    renderAsymmetry();
  }

  function handCard(hand, r) {
    const card = document.createElement('div');
    card.className = `tap-card${r.valid ? '' : ' invalid'}`;
    const metrics = METRICS.filter(m => Number.isFinite(r[m.key])).map(m => `
      <div class="tap-metric">
        <div class="tap-metric-label">${escapeHtml(m.label)}</div>
        <div class="tap-metric-value">${escapeHtml(m.fmt(r[m.key]))}</div>
        <div class="tap-metric-help">${escapeHtml(m.help)}</div>
      </div>`).join('');
    const quality = [
      r.n_taps != null ? `${r.n_taps} taps` : null,
      r.capture_fps ? `${Math.round(r.capture_fps)} fps` : null,
      r.drops != null ? `${r.drops} dropped frames` : null,
      r.detect_pct != null ? `hand found in ${Math.round(r.detect_pct)}% of frames` : null,
      r.source ? `source: ${r.source}` : null,
    ].filter(Boolean).join(' · ');
    const warnings = (r.warnings || []).map(w => `<li>${escapeHtml(w)}</li>`).join('');
    card.innerHTML = `
      <div class="tap-card-head">
        <h3>${capitalise(hand)} hand</h3>
        <span class="tap-card-state">${r.valid ? 'Measured' : 'Not reliable'}</span>
      </div>
      ${warnings ? `<ul class="tap-warnings">${warnings}</ul>` : ''}
      ${metrics ? `<div class="tap-metrics">${metrics}</div>` : ''}
      ${r.series ? `<div class="tap-charts">
        <figure><canvas class="tap-trace"></canvas><figcaption>Finger opening over 10 s · dots = detected taps</figcaption></figure>
        <figure><canvas class="tap-bars"></canvas><figcaption>Size of each tap · line = trend</figcaption></figure>
      </div>` : ''}
      <div class="tap-quality">${escapeHtml(quality)}</div>`;
    requestAnimationFrame(() => {
      drawTrace(card.querySelector('.tap-trace'), r.series);
      drawBars(card.querySelector('.tap-bars'), r.amplitudes || []);
    });
    return card;
  }

  function renderAsymmetry() {
    const R = results.right, L = results.left;
    if (!(R && L && R.valid && L.valid)) { asymEl.classList.add('hidden'); return; }
    const ratio = (a, b) => Math.round(Math.min(a, b) / Math.max(a, b) * 100);
    const slower = R.rate_hz < L.rate_hz ? 'right' : 'left';
    const smaller = R.amp_mean < L.amp_mean ? 'right' : 'left';
    asymEl.innerHTML = `
      <strong>Left vs right</strong>
      <span>Speed match: <b>${ratio(R.rate_hz, L.rate_hz)}%</b> (${slower} slower)</span>
      <span>Size match: <b>${ratio(R.amp_mean, L.amp_mean)}%</b> (${smaller} smaller)</span>
      <span class="tap-asym-note">100% = both hands identical. Parkinson's often starts on one side.</span>`;
    asymEl.classList.remove('hidden');
  }

  function prepCanvas(cv) {
    const rect = cv.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    cv.width = rect.width * dpr;
    cv.height = rect.height * dpr;
    const c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, rect.width, rect.height);
    return { c, w: rect.width, h: rect.height };
  }

  function drawTrace(cv, s) {
    if (!cv || !s || !s.t || s.t.length < 2) return;
    const { c, w, h } = prepCanvas(cv);
    const pad = 8;
    const tMax = s.t[s.t.length - 1] || 1;
    const dMin = Math.min(...s.d), dMax = Math.max(...s.d);
    const X = t => pad + (t / tMax) * (w - 2 * pad);
    const Y = d => h - pad - ((d - dMin) / Math.max(dMax - dMin, 1e-6)) * (h - 2 * pad);
    c.strokeStyle = '#3d5a99';
    c.lineWidth = 1.6;
    c.beginPath();
    s.t.forEach((t, i) => (i ? c.lineTo(X(t), Y(s.d[i])) : c.moveTo(X(t), Y(s.d[i]))));
    c.stroke();
    c.fillStyle = '#b07a1a';
    (s.tap_t || []).forEach((t, i) => {
      c.beginPath();
      c.arc(X(t), Y(s.tap_d[i]), 3, 0, 2 * Math.PI);
      c.fill();
    });
  }

  function drawBars(cv, amps) {
    if (!cv || amps.length < 2) return;
    const { c, w, h } = prepCanvas(cv);
    const pad = 8;
    const max = Math.max(...amps) * 1.1;
    const bw = (w - 2 * pad) / amps.length;
    c.fillStyle = '#9fb0d6';
    amps.forEach((a, i) => {
      const bh = (a / max) * (h - 2 * pad);
      c.fillRect(pad + i * bw + 1, h - pad - bh, Math.max(bw - 2, 1), bh);
    });
    // least-squares trend line (the decrement)
    const n = amps.length;
    const mx = (n - 1) / 2, my = amps.reduce((s, a) => s + a, 0) / n;
    let num = 0, den = 0;
    amps.forEach((a, i) => { num += (i - mx) * (a - my); den += (i - mx) ** 2; });
    const slope = den ? num / den : 0;
    const y = i => h - pad - ((my + slope * (i - mx)) / max) * (h - 2 * pad);
    c.strokeStyle = '#1c2333';
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(pad + bw / 2, y(0));
    c.lineTo(pad + (n - 0.5) * bw, y(n - 1));
    c.stroke();
  }

  updateButtons();

  // For testing from the browser console / DevTools: render a result without a camera.
  window.drawdxTapping = { results, renderResults, showTapping, showSpiral };
})();
