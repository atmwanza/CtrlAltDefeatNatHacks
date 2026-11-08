// DrawDx balance test (camera Romberg): tablet side. EXPERIMENTAL.
// Adds a third "Balance" tab next to Spiral and Tapping. Stand still 30 s with eyes open,
// then 30 s with eyes closed; voice prompts guide the eyes-closed part. The camera is the
// same one the tapping test uses (Pi or webcam capture); the laptop does the analysis.
// Loaded after app.js and tapping.js, and reuses their globals (canvasContainer,
// resultsPanel, mainEl, showDrawingView, initCanvas, enterFullscreen, escapeHtml,
// window.drawdxTapping) and the tapping panel's styles.

(() => {
  const STAGE_SECONDS = 30;
  const HEALTH_MS = 2000;
  const STREAM_RETRY_MS = 1000;
  const STATUS_TIMEOUT_MS = 180000;

  const $ = id => document.getElementById(id);
  const spiralTab = $('mode-spiral-btn');
  const tappingTab = $('mode-tapping-btn');
  const modeSwitch = spiralTab.parentElement;

  // ---------- build the tab, camera badge and panel ----------

  const balanceTab = document.createElement('button');
  balanceTab.id = 'mode-balance-btn';
  balanceTab.className = 'mode-btn';
  balanceTab.setAttribute('role', 'tab');
  balanceTab.setAttribute('aria-selected', 'false');
  balanceTab.textContent = 'Balance';
  modeSwitch.appendChild(balanceTab);

  const cameraBadge = document.createElement('span');
  cameraBadge.id = 'bal-camera-badge';
  cameraBadge.className = 'tap-camera-badge balance-only';
  cameraBadge.textContent = 'Camera: checking…';
  $('tap-camera-badge').after(cameraBadge);

  const panel = document.createElement('section');
  panel.id = 'balance-panel';
  panel.className = 'hidden';
  panel.innerHTML = `
    <div class="tap-header">
      <div>
        <h2>Balance</h2>
        <p class="tap-sub">Romberg test: how much the body sways while standing still, eyes open and then eyes closed</p>
      </div>
      <span class="tap-proto">Experimental · healthy baseline only</span>
    </div>
    <div class="tap-grid">
      <div class="tap-camera">
        <div class="tap-preview-wrap">
          <img id="bal-preview" alt="Camera view of the whole body">
          <div id="bal-preview-empty" class="tap-preview-empty">Camera preview appears here</div>
          <div id="bal-overlay" class="tap-overlay hidden"></div>
        </div>
      </div>
      <div class="tap-side">
        <ol class="tap-steps">
          <li>Stand about 2.5–3 m from the camera so your <strong>whole body, head to feet</strong>, is in view.</li>
          <li>Face it with your feet together and your arms by your sides.</li>
          <li>Stand still for 30 seconds with your eyes open, then 30 seconds with your eyes closed. A voice tells you when, so turn the tablet's sound on.</li>
        </ol>
        <label class="bal-height">Your height
          <input id="bal-height" type="number" inputmode="numeric" min="100" max="230" value="170"> cm
        </label>
        <div class="tap-buttons">
          <button id="bal-start-btn" class="btn btn-primary">Start balance test</button>
        </div>
        <div id="bal-progress" class="tap-progress hidden"><div id="bal-progress-bar" class="tap-progress-bar"></div></div>
        <div id="bal-message" class="tap-message" role="status"></div>
      </div>
    </div>
    <div id="bal-results"></div>`;
  mainEl.appendChild(panel);

  const preview = $('bal-preview');
  const previewEmpty = $('bal-preview-empty');
  const overlay = $('bal-overlay');
  const startBtn = $('bal-start-btn');
  const heightInput = $('bal-height');
  const progress = $('bal-progress');
  const progressBar = $('bal-progress-bar');
  const message = $('bal-message');
  const resultsEl = $('bal-results');
  const previewWrap = preview.closest('.tap-preview-wrap');

  let active = false;          // balance view showing
  let cameraReady = false;
  let running = false;         // a test is in progress
  let streaming = false;
  let retryTimer = null;
  let healthTimer = null;
  let spiralResultsWereShowing = false;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ---------- switching tabs ----------
  // tapping.js only knows Spiral and Tapping. Leaving Balance first puts the page back in
  // the spiral state, then tapping.js's own tab handlers carry on from there as usual.

  function setTabs(on) {
    for (const t of [spiralTab, tappingTab]) {
      if (on) { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); }
    }
    balanceTab.classList.toggle('active', on);
    balanceTab.setAttribute('aria-selected', String(on));
    if (!on) { spiralTab.classList.add('active'); spiralTab.setAttribute('aria-selected', 'true'); }
  }

  function showBalance() {
    if (active || spiralTab.disabled) return;   // spiralTab is disabled while a tapping trial runs
    if (document.body.classList.contains('mode-tapping') && window.drawdxTapping) {
      window.drawdxTapping.showSpiral();
    }
    active = true;
    spiralResultsWereShowing = !resultsPanel.classList.contains('hidden');
    setTabs(true);
    document.body.classList.add('mode-balance');
    canvasContainer.style.display = 'none';
    resultsPanel.classList.add('hidden');
    mainEl.classList.remove('drawing-locked');   // the panel can scroll
    mainEl.scrollTop = 0;
    panel.classList.remove('hidden');
    checkHealth();
    healthTimer = setInterval(checkHealth, HEALTH_MS);
    startPreview();
  }

  function leaveBalance() {
    active = false;
    stopPreview();
    clearInterval(healthTimer);
    panel.classList.add('hidden');
    document.body.classList.remove('mode-balance');
    setTabs(false);
    if (spiralResultsWereShowing) {
      resultsPanel.classList.remove('hidden');
    } else {
      showDrawingView();   // must be visible before initCanvas() measures it
      initCanvas();
    }
  }

  balanceTab.addEventListener('click', () => { enterFullscreen(); showBalance(); });

  // capture phase: runs before tapping.js's handlers on the Spiral / Tapping buttons
  modeSwitch.addEventListener('click', e => {
    const tab = e.target.closest('.mode-btn');
    if (!active || !tab || tab === balanceTab) return;
    if (running) { e.stopPropagation(); return; }
    leaveBalance();
  }, true);

  // ---------- camera status + preview ----------

  async function checkHealth() {
    try {
      const h = await fetch('/health', { cache: 'no-store' }).then(r => r.json());
      cameraReady = !!h.capture_ready;
      const names = { picamera: 'Pi camera', webcam: 'laptop webcam', synthetic: 'test source' };
      cameraBadge.textContent = cameraReady ? `● ${names[h.capture_source] || 'camera'} connected` : '● Camera not connected';
      cameraBadge.classList.toggle('ok', cameraReady);
    } catch (_) {
      cameraReady = false;
      cameraBadge.textContent = '● Server not reachable';
      cameraBadge.classList.remove('ok');
    }
    updateButtons();
    if (cameraReady && !streaming) startPreview();
    if (!cameraReady && streaming) stopPreview();
    if (!running && !cameraReady) {
      setMessage('Waiting for the camera. Start the Pi, or run the webcam capture on the laptop.', 'warn');
    } else if (!running && message.dataset.kind === 'warn' && message.textContent.startsWith('Waiting')) {
      setMessage('');
    }
  }

  function startPreview() {
    clearTimeout(retryTimer);
    if (!active || !cameraReady) return;
    streaming = true;
    preview.src = `/tapping/stream.mjpg?overlay=0&t=${Date.now()}`;   // no hand skeleton here
  }

  function stopPreview() {
    clearTimeout(retryTimer);
    streaming = false;
    preview.removeAttribute('src');
    preview.classList.remove('live');
    previewEmpty.classList.remove('hidden');
  }

  preview.addEventListener('load', () => { preview.classList.add('live'); previewEmpty.classList.add('hidden'); });
  preview.addEventListener('error', () => {
    preview.classList.remove('live');
    if (!active || !streaming) return;
    previewEmpty.classList.remove('hidden');
    clearTimeout(retryTimer);
    retryTimer = setTimeout(startPreview, STREAM_RETRY_MS);
  });

  document.addEventListener('visibilitychange', () => {
    if (!active) return;
    if (document.hidden) stopPreview(); else startPreview();
  });

  function updateButtons() {
    startBtn.disabled = running || !cameraReady;
    spiralTab.disabled = running;
    tappingTab.disabled = running;
  }

  function setMessage(text, kind = '') {
    message.textContent = text;
    message.dataset.kind = kind;
    message.className = `tap-message ${kind}`;
  }

  // ---------- voice + beeps ----------

  let audioCtx = null;
  function unlockAudio() {                  // must run inside the Start tap, or Safari stays silent
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume();
      if (window.speechSynthesis) speechSynthesis.speak(new SpeechSynthesisUtterance(''));
    } catch (_) { /* no audio */ }
  }

  function beep(ms = 250, hz = 880) {
    if (!audioCtx) return;
    try {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = hz;
      gain.gain.value = 0.2;
      osc.connect(gain).connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + ms / 1000);
    } catch (_) { /* ignore */ }
  }

  function say(text) {
    setMessage(text, 'live');
    if (!window.speechSynthesis) return Promise.resolve();
    return new Promise(resolve => {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 0.95;
      u.onend = resolve;
      u.onerror = resolve;
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
      setTimeout(resolve, 8000);            // never hang if the voice doesn't report back
    });
  }

  // ---------- the test: eyes open -> eyes closed -> results ----------

  startBtn.addEventListener('click', () => { unlockAudio(); runTest(); });

  async function runTest() {
    if (running || !cameraReady) return;
    running = true;
    updateButtons();
    resultsEl.innerHTML = '';
    try {
      await say('Stand still with your feet together and your arms by your sides. Keep your eyes open.');
      await countdown();
      const eo = await recordStage('EO', 'Eyes open: stand as still as you can.');
      if (!eo) return;
      beep(400, 660);
      await say('Relax for a moment.');
      const eoUp = await waitFor(eo, s => s !== 'recording');   // the camera is free once the clip is in
      if (eoUp.state === 'error') return fail(eoUp.error);

      await say('Next, stand the same way, and close your eyes when you hear the beep.');
      await sleep(1500);
      beep();
      await say('Close your eyes now.');
      const ec = await recordStage('EC', 'Eyes closed: stand as still as you can.');
      if (!ec) return;
      beep(400, 660);
      await say('Done. You can open your eyes.');

      setMessage('Analysing both recordings…');
      const [a, b] = await Promise.all([waitFor(eo, s => s === 'done'), waitFor(ec, s => s === 'done')]);
      if (a.state !== 'done') return fail(a.error);
      if (b.state !== 'done') return fail(b.error);
      const res = await fetch('/balance/result', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eo, ec }),
      });
      const data = await res.json();
      if (!res.ok) return fail(data.detail || `Server returned ${res.status}`);
      renderResults(data);
      setMessage('Done.', 'ok');
    } catch (err) {
      fail(err.message);
    } finally {
      running = false;
      overlay.classList.add('hidden');
      overlay.classList.remove('rec');
      progress.classList.add('hidden');
      progressBar.style.width = '0%';
      updateButtons();
    }
  }

  function fail(text) { setMessage(text || 'Something went wrong. Try again.', 'error'); }

  async function countdown() {
    overlay.classList.remove('hidden', 'rec');
    for (const n of ['3', '2', '1']) { overlay.textContent = n; await sleep(1000); }
  }

  async function recordStage(condition, text) {
    let sid;
    try {
      const res = await fetch('/balance/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ condition, height_cm: Number(heightInput.value) || null }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Server returned ${res.status}`);
      sid = body.session_id;
    } catch (err) {
      fail(`Could not start recording: ${err.message}`);
      return null;
    }
    setMessage(text, 'live');
    previewWrap.classList.add('is-recording');   // red glow while recording (style.css)
    previewWrap.classList.remove('is-recording');
    overlay.classList.remove('hidden');
    overlay.classList.add('rec');
    progress.classList.remove('hidden');
    const t0 = performance.now();
    // timer, not requestAnimationFrame: rAF pauses in background tabs and would stall the flow
    await new Promise(resolve => {
      const timer = setInterval(() => {
        const elapsed = (performance.now() - t0) / 1000;
        const f = Math.min(1, elapsed / STAGE_SECONDS);
        progressBar.style.width = `${f * 100}%`;
        overlay.textContent = `● REC  ${Math.max(0, STAGE_SECONDS - elapsed).toFixed(0)}s`;
        if (f >= 1) { clearInterval(timer); resolve(); }
      }, 200);
    });
    overlay.classList.add('hidden');
    progress.classList.add('hidden');
    return sid;
  }

  async function waitFor(sid, done) {
    const deadline = performance.now() + STATUS_TIMEOUT_MS;
    while (performance.now() < deadline) {
      try {
        const job = await fetch(`/balance/status/${sid}`, { cache: 'no-store' }).then(r => r.json());
        if (done(job.state) || job.state === 'error') return job;
      } catch (_) { /* transient: keep polling */ }
      await sleep(1000);
    }
    return { state: 'error', error: 'Timed out waiting for the camera or the analysis.' };
  }

  // ---------- results ----------

  const NAMES = { EO: 'Eyes open', EC: 'Eyes closed' };
  const fmt = (v, unit) => (v == null || !Number.isFinite(Number(v))) ? '—' : `${Number(v).toFixed(1)} ${unit}`;

  function stageCard(cond, s) {
    const unit = s.units || 'mm';
    const m = s.measurements || {};
    const band = s.status !== 'scored' ? '' :
      s.deviation_index < 0.15 ? 'low' : s.deviation_index < 0.4 ? 'moderate' : 'high';
    const state = { scored: 'Compared', no_baseline: 'Measured', invalid_trial: 'Not reliable' }[s.status] || '';
    const reasons = (s.reasons || []).map(r => `<li>${escapeHtml(r)}</li>`).join('');
    const notes = (s.warnings || []).map(w => `<li>${escapeHtml(w)}</li>`).join('');
    const metric = (label, value, help) => `
      <div class="tap-metric">
        <div class="tap-metric-label">${label}</div>
        <div class="tap-metric-value">${escapeHtml(value)}</div>
        <div class="tap-metric-help">${help}</div>
      </div>`;
    const metrics = s.status === 'invalid_trial' ? '' : `
      <div class="tap-metrics">
        ${metric('Sway speed', fmt(m.mean_vel, unit + '/s'), 'How fast the body drifted')}
        ${metric('Side-to-side sway', fmt(m.rms_ml, unit), 'Typical distance from the centre')}
        ${metric('Total sway path', fmt(m.path_len, unit), 'Distance moved in 30 s')}
      </div>`;
    return `
      <div class="tap-card${s.status === 'invalid_trial' ? ' invalid' : ''}">
        <div class="tap-card-head"><h3>${NAMES[cond]}</h3><span class="tap-card-state">${state}</span></div>
        <div class="bal-label ${band}">${escapeHtml(s.status === 'scored' ? s.label : (s.message || ''))}</div>
        ${reasons ? `<ul class="tap-warnings">${reasons}</ul>` : ''}
        ${metrics}
        ${notes ? `<ul class="bal-notes">${notes}</ul>` : ''}
      </div>`;
  }

  function renderResults(data) {
    const cards = ['EO', 'EC'].map(c => stageCard(c, data.stages[c] || {})).join('');
    const r = data.romberg || {};
    const ratio = r.mean_vel ? r.mean_vel.ec_eo_ratio : null;
    const romberg = r.status === 'ok' && ratio != null ? `
      <div class="tap-asymmetry">
        <strong>Eyes closed vs open</strong>
        <span>Sway speed with eyes closed: <b>×${ratio.toFixed(2)}</b> the eyes-open value</span>
        <span class="tap-asym-note">Sway usually rises when the eyes close; what counts as too much has to come from a healthy baseline.</span>
      </div>` : '';
    const n = data.baseline_trials || {};
    const base = (n.EO || n.EC)
      ? `Compared with our healthy baseline (${n.EO || 0} eyes-open and ${n.EC || 0} eyes-closed trials).`
      : 'No healthy baseline recorded yet, so these are measurements only.';
    resultsEl.innerHTML = `<div class="tap-results">${cards}</div>${romberg}
      <div class="tap-disclaimer">${escapeHtml(base)} ${escapeHtml(data.disclaimer || '')}</div>`;
  }

  updateButtons();

  // For testing from the browser console: window.drawdxBalance.renderResults({...})
  window.drawdxBalance = { renderResults, showBalance };
})();