// DrawDx balance study: tablet side. A PLANNED STUDY, NOT A TEST: the tab shows the study plan;
// the working recorder (pilot) sits in a closed drawer and only turns the camera on when opened.
// Nobody gets a health result.
// Protocol from the published Parkinson's balance dataset (de Oliveira et al. 2022): quiet
// standing, heels ~10 cm apart, 30 s eyes open then 30 s eyes closed. Consent first; anonymous
// ID; numbers only, saved on the laptop (balance_api.py /balance/study/*).
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
  balanceTab.className = 'mode-btn nav-link';
  balanceTab.setAttribute('role', 'tab');
  balanceTab.setAttribute('aria-selected', 'false');
  balanceTab.innerHTML = `${window.tiIcon ? tiIcon('walk') : ''}Balance (planned)`;
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
        <h2>Balance study <span class="bal-planned">planned</span></h2>
        <p class="tap-sub">Our next step: collect camera-based balance data from healthy people and people with
          Parkinson's. <b>Not part of today's screening, and not a test.</b></p>
      </div>
      <span class="tap-proto">Future study</span>
    </div>
    <div class="bal-plan">
      <div class="bal-plan-card">
        <h3>Why</h3>
        <p>Balance problems (postural instability) are a key sign of Parkinson's. Every public balance dataset we
          found was recorded on a lab force plate; we found <b>no camera-based balance data from people with
          Parkinson's</b>, so a camera tool has nothing to be checked against yet.</p>
      </div>
      <div class="bal-plan-card">
        <h3>Who</h3>
        <p>Healthy volunteers and people with Parkinson's, recruited with <b>research ethics approval</b> and
          informed consent, for example through a movement-disorders clinic.</p>
      </div>
      <div class="bal-plan-card">
        <h3>Protocol</h3>
        <p>Copied from the published Parkinson's balance dataset (de Oliveira et al. 2022): stand still, heels about
          10 cm apart, <b>30 s eyes open, then 30 s eyes closed</b>, one camera 2 m away.</p>
      </div>
      <div class="bal-plan-card">
        <h3>What we'd measure</h3>
        <p>Side-to-side sway, sway speed, and how much sway rises when the eyes close. Then compare healthy people
          with people with Parkinson's, and with the published force-plate data.</p>
      </div>
      <div class="bal-plan-card">
        <h3>Privacy</h3>
        <p>No names and no video: numbers only, under an anonymous ID. Participants can withdraw at any time.</p>
      </div>
      <div class="bal-plan-card bal-status">
        <h3>Status</h3>
        <p><b>Built:</b> camera recording, body tracking (MediaPipe Pose), sway analysis (centre-of-mass model,
          quality checks), consent and anonymous storage.<br><b>Not started:</b> data collection.</p>
      </div>
    </div>
    <details id="bal-pilot" class="bal-pilot">
      <summary>Try the recorder (pilot, for our team)</summary>
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
          <li>Stand about <strong>2 m</strong> from the camera, <strong>whole body, head to feet,</strong> in view.</li>
          <li>Heels about a hand-width apart (10 cm), toes slightly out, arms by your sides. Look at a point on the wall.</li>
          <li>Stand still: <strong>30 s eyes open, then 30 s eyes closed</strong>. A voice tells you when (sound on).</li>
        </ol>
        <div class="bal-form">
          <label>Age <select id="bal-age">
            <option value="">choose…</option><option>18-29</option><option>30-44</option><option>45-59</option>
            <option>60-74</option><option>75+</option><option>prefer not to say</option></select></label>
          <label>Sex <select id="bal-sex">
            <option value="">skip</option><option>female</option><option>male</option><option>other</option>
            <option>prefer not to say</option></select></label>
          <label class="bal-height">Height
            <input id="bal-height" type="number" inputmode="numeric" min="100" max="230" value="170"> cm</label>
        </div>
        <label class="bal-consent"><input id="bal-consent" type="checkbox">
          <span>I agree to my <b>anonymous numbers</b> (no name, no video) being saved for this student project's
            research. I can ask for them to be deleted.</span></label>
        <div class="tap-buttons">
          <button id="bal-start-btn" class="btn btn-primary">Start recording (2 × 30 s)</button>
        </div>
        <div id="bal-progress" class="tap-progress hidden"><div id="bal-progress-bar" class="tap-progress-bar"></div></div>
        <div id="bal-message" class="tap-message" role="status"></div>
      </div>
    </div>
    <div id="bal-results"></div>
    <div id="bal-dataset" class="bal-dataset"></div>
    </details>
    <div class="tap-footer">ⓘ A planned student study, not a medical test. Protocol after de Oliveira et al., Front Neurosci
      2022 (public Parkinson's balance dataset, force plate, CC0) and Santos &amp; Duarte, PeerJ 2016 (public healthy-adult
      dataset). Camera method (body tracking + de Leva centre-of-mass model) as in Sonar et al., Sensors 2026. One camera
      measures side-to-side sway only.</div>`;
  mainEl.appendChild(panel);

  const preview = $('bal-preview');
  const previewEmpty = $('bal-preview-empty');
  const overlay = $('bal-overlay');
  const startBtn = $('bal-start-btn');
  const heightInput = $('bal-height');
  const ageInput = $('bal-age');
  const sexInput = $('bal-sex');
  const consentInput = $('bal-consent');
  const datasetEl = $('bal-dataset');
  const progress = $('bal-progress');
  const progressBar = $('bal-progress-bar');
  const message = $('bal-message');
  const resultsEl = $('bal-results');
  const previewWrap = preview.closest('.tap-preview-wrap');
  const pilot = $('bal-pilot');

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
    if (!active || !cameraReady || !pilot.open) return;
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
    startBtn.disabled = running || !cameraReady || !consentInput.checked || !ageInput.value;
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
  pilot.addEventListener('toggle', () => {
    if (pilot.open) { checkHealth(); startPreview(); } else if (!running) { stopPreview(); }
  });
  consentInput.addEventListener('change', updateButtons);
  ageInput.addEventListener('change', updateButtons);

  async function runTest() {
    if (running || !cameraReady) return;
    running = true;
    updateButtons();
    resultsEl.innerHTML = '';
    try {
      await say('Stand with your heels a hand-width apart, arms by your sides, and look at a point on the wall. Keep your eyes open.');
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
      if (!consentInput.checked) return fail('Nothing was saved: consent was withdrawn before the end.');
      const res = await fetch('/balance/study/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eo, ec, consent: true, age_band: ageInput.value, sex: sexInput.value,
                               height_cm: Number(heightInput.value) || null }),
      });
      const data = await res.json();
      if (!res.ok) return fail(data.detail || `Server returned ${res.status}`);
      renderSaved(data);
      setMessage(`Saved as ${data.participant}. Thank you!`, 'ok');
      consentInput.checked = false;            // the next person gives their own consent
      updateButtons();
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
    previewWrap.classList.remove('is-recording');
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

  // ---------- study: what was saved, and the dataset so far ----------

  const STAGES = [['EO', 'eo', 'Eyes open'], ['EC', 'ec', 'Eyes closed']];

  function renderSaved(data) {
    const r = data.row;
    const unit = r.units === 'mm' ? 'mm' : 'px';
    const num = (v, d = 1) => (v == null || !Number.isFinite(Number(v))) ? '—' : Number(v).toFixed(d);
    const cards = STAGES.map(([C, k, name]) => {
      const ok = r[`${k}_valid`];
      const reasons = (data.reasons[C] || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
      return `
        <div class="tap-card${ok ? '' : ' invalid'}">
          <div class="tap-card-head"><h3>${name}</h3>
            <span class="tap-card-state">${ok ? 'Recorded' : 'Saved, flagged'}</span></div>
          ${reasons ? `<ul class="tap-warnings">${reasons}</ul>` : ''}
          <div class="tap-metrics">
            <div class="tap-metric"><div class="tap-metric-label">Side-to-side sway</div>
              <div class="tap-metric-value">${num(r[`${k}_rms_ml_mm`])} ${unit}</div>
              <div class="tap-metric-help">Typical distance from the centre</div></div>
            <div class="tap-metric"><div class="tap-metric-label">Sway speed</div>
              <div class="tap-metric-value">${num(r[`${k}_mean_vel_mm_s`])} ${unit}/s</div>
              <div class="tap-metric-help">How fast the body drifted</div></div>
          </div>
        </div>`;
    }).join('');
    resultsEl.innerHTML = `
      <div class="bal-saved">
        <div>
          <div class="verdict-kicker">Saved to our dataset</div>
          <div class="bal-pid">Participant ${escapeHtml(data.participant)}</div>
          <div class="verdict-why">Thank you! Eyes closed ÷ eyes open (side-to-side sway):
            <b>${r.romberg_rms_ml != null ? '×' + num(r.romberg_rms_ml, 2) : '—'}</b>. Sway usually rises with the eyes closed.
            These are measurements for our study, not a health result.</div>
        </div>
        <button id="bal-withdraw" class="btn">Delete my numbers</button>
      </div>
      <div class="tap-results">${cards}</div>`;
    $('bal-withdraw').addEventListener('click', () => withdraw(data.participant));
    renderDataset(data.summary);
    resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function withdraw(pid) {
    try {
      const res = await fetch(`/balance/study/${encodeURIComponent(pid)}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Server returned ${res.status}`);
      resultsEl.innerHTML = `<div class="bal-saved"><div class="verdict-why">${escapeHtml(pid)}'s numbers were deleted.</div></div>`;
      renderDataset(data.summary);
      setMessage(`${pid} deleted.`, 'ok');
    } catch (err) {
      fail(`Could not delete: ${err.message}`);
    }
  }

  function renderDataset(s) {
    if (!s) return;
    const m = s.median || {};
    const med = m.eo_rms_ml_mm != null
      ? ` Median side-to-side sway: ${m.eo_rms_ml_mm} mm eyes open, ${m.ec_rms_ml_mm} mm eyes closed (×${m.romberg_rms_ml}).`
      : '';
    datasetEl.innerHTML = `<b>Our dataset so far: ${s.n_participants} participant${s.n_participants === 1 ? '' : 's'}</b>
      (${s.n_usable} with both recordings usable).${escapeHtml(med)}`;
  }

  async function loadDataset() {
    try { renderDataset(await fetch('/balance/study/summary', { cache: 'no-store' }).then(r => r.json())); }
    catch (_) { /* shown after the first save instead */ }
  }

  updateButtons();
  loadDataset();

  // For testing from the browser console
  window.drawdxBalance = { renderResults, renderSaved, renderDataset, showBalance };
})();