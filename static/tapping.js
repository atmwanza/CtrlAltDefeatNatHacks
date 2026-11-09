// DrawDx finger-tapping prototype (MDS-UPDRS 3.4): tablet side.
// The laptop backend drives the camera (Raspberry Pi, or the laptop webcam fallback);
// this page only starts recordings, shows a preview and renders results. Loaded after
// app.js, whose globals (canvasContainer, resultsPanel, mainEl, showDrawingView,
// initCanvas, escapeHtml) it reuses for switching between the two tests.

(() => {
  const TAP_SECONDS = 10;
  const COUNTDOWN = ['3', '2', '1'];
  const STREAM_RETRY_MS = 1000;
  const HEALTH_MS = 2000;
  const STATUS_MS = 500;
  const STATUS_TIMEOUT_MS = 90000;
  // Tapping score. Our team check (Nov 8) showed the first, size-only score followed tapping
  // speed (same person 61 then 6), so it was hidden; the score now includes speed and is
  // scored per hand (held-out AUC 0.91). Set to false to hide it again (bars stay).
  const SHOW_COMBINED_SCORE = true;

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
  const progressLabel = $('tap-progress-label');
  const message = $('tap-message');
  const resultsEl = $('tap-results');
  const asymEl = $('tap-asymmetry');
  const scoreEl = $('tap-score');
  const clearBtn = $('tap-clear-btn');
  const footerEl = $('tap-footer');
  const previewWrap = preview.closest('.tap-preview-wrap');

  let active = false;          // tapping view showing
  let cameraReady = false;
  let running = false;         // a recording/analysis is in progress
  let streaming = false;       // live MJPEG preview connected
  let retryTimer = null;
  let healthTimer = null;
  let spiralResultsWereShowing = false;
  const results = { right: null, left: null };
  const sessions = { right: null, left: null };   // backend ids, for the two-hand score
  let generation = 0;          // bumped by Clear, so a late score reply can't bring old results back

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

  // A tab switch is a tap, so it may (re)enter fullscreen: Chrome drops fullscreen on
  // various events (reload, back gesture), and this brings it back on every switch.
  spiralTab.addEventListener('click', () => { enterFullscreen(); showSpiral(); });
  tappingTab.addEventListener('click', () => { enterFullscreen(); showTapping(); });

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
    if (cameraReady && !streaming) startPreview();
    if (!cameraReady && streaming) stopPreview();
    if (!running && !cameraReady) {
      setMessage('Waiting for the camera. Start the Pi, or run the webcam capture on the laptop.', 'warn');
    } else if (!running && message.dataset.kind === 'warn' && message.textContent.startsWith('Waiting')) {
      setMessage('');
    }
  }

  // One long-lived MJPEG connection (smooth ~20 fps), relayed by the laptop from the camera.
  // It keeps running during a recording so the person can keep their hand in view.
  function startPreview() {
    clearTimeout(retryTimer);
    if (!active || !cameraReady) return;
    streaming = true;
    preview.src = `/tapping/stream.mjpg?t=${Date.now()}`;
  }

  function stopPreview() {
    clearTimeout(retryTimer);
    streaming = false;
    preview.removeAttribute('src');   // closes the stream connection
    previewEmpty.classList.remove('hidden');
  }

  preview.addEventListener('load', () => { previewEmpty.classList.add('hidden'); });
  preview.addEventListener('error', () => {
    if (!active || !streaming) return;
    previewEmpty.classList.remove('hidden');
    clearTimeout(retryTimer);
    retryTimer = setTimeout(startPreview, STREAM_RETRY_MS);   // Wi-Fi blip / camera restart
  });

  document.addEventListener('visibilitychange', () => {
    if (!active) return;
    if (document.hidden) stopPreview(); else startPreview();
  });

  function updateButtons() {
    const disabled = running || !cameraReady;
    rightBtn.disabled = disabled;
    leftBtn.disabled = disabled;
    // two-step flow: a finished hand turns green, the next one pulses
    const done = h => !!(results[h] && results[h].valid);
    const ic = n => (window.tiIcon ? tiIcon(n) : '');
    rightBtn.innerHTML = done('right') ? `${ic('check')}Right hand done · redo` : `${ic('hand-finger')}Start right hand`;
    leftBtn.innerHTML = done('left') ? `${ic('check')}Left hand done · redo` : `${ic('hand-finger')}Start left hand`;
    const current = !done('right') ? 0 : !done('left') ? 1 : 2;
    document.querySelectorAll('#tap-steps .step-item').forEach((el, i) => {
      el.classList.toggle('active', i === current);
      if (i === current) el.setAttribute('aria-current', 'step'); else el.removeAttribute('aria-current');
    });
    rightBtn.classList.toggle('done', done('right'));
    leftBtn.classList.toggle('done', done('left'));
    rightBtn.classList.toggle('next', !running && !done('right') && done('left'));
    leftBtn.classList.toggle('next', !running && done('right') && !done('left'));
    spiralTab.disabled = running;
    if (clearBtn) {   // null if a cached old page is paired with this script: never break tapping over it
      clearBtn.disabled = running;
      clearBtn.classList.toggle('hidden', !(results.right || results.left));
    }
  }

  function setMessage(text, kind = '') {
    message.textContent = text;
    message.dataset.kind = kind;
    message.className = `tap-message ${kind}`;
  }

  // ---------- one recording: countdown -> record -> analyse -> show ----------

  rightBtn.addEventListener('click', () => runHand('right'));
  if (clearBtn) clearBtn.addEventListener('click', clearResults);

  // Clear both hands for the next person (like Draw Again on the spiral).
  function clearResults() {
    if (running) return;
    generation++;
    results.right = results.left = null;
    sessions.right = sessions.left = null;
    resultsEl.innerHTML = '';
    scoreEl.innerHTML = '';
    scoreEl.className = 'tap-score hidden';
    asymEl.classList.add('hidden');
    setMessage('Cleared. Start with the right hand.');
    updateButtons();
    mainEl.scrollTop = 0;
    window.scrollTo(0, 0);
  }
  leftBtn.addEventListener('click', () => runHand('left'));

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  async function runHand(hand) {
    if (running || !cameraReady) return;
    running = true;
    updateButtons();
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
    if (previewWrap) previewWrap.classList.add('is-recording');
    progress.classList.remove('hidden');
    const t0 = performance.now();
    // timer, not requestAnimationFrame: rAF pauses in background tabs and would stall the flow
    await new Promise(resolve => {
      const timer = setInterval(() => {
        const elapsed = (performance.now() - t0) / 1000;
        const f = Math.min(1, elapsed / TAP_SECONDS);
        progressBar.style.width = `${f * 100}%`;
        if (progressLabel) progressLabel.textContent = f >= 1 ? 'Done' : `${Math.ceil(TAP_SECONDS - elapsed)} s left`;
        if (elapsed > 0.8) {   // GO has been seen: shrink to a pill so the live view stays visible
          overlay.classList.add('rec');
          overlay.textContent = `● REC  ${Math.max(0, TAP_SECONDS - elapsed).toFixed(0)}s`;
        }
        if (f >= 1) { clearInterval(timer); resolve(); }
      }, 100);
    });
    overlay.classList.remove('rec');
    overlay.textContent = 'Stop';
    setMessage('Analysing…');

    const job = await pollStatus(sid);
    if (job.state !== 'done') {
      return finish(job.error || 'The recording did not come back from the camera.', 'error');
    }
    results[hand] = job.result;
    sessions[hand] = sid;
    renderResults();
    updateScore();
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
    if (previewWrap) previewWrap.classList.remove('is-recording');
    overlay.classList.add('hidden');
    overlay.classList.remove('rec');
    progress.classList.add('hidden');
    progressBar.style.width = '0%';
    if (progressLabel) progressLabel.textContent = '';
    setMessage(text, kind);
    updateButtons();
    if (!streaming) startPreview();
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
    card.className = `tap-card card${r.valid ? '' : ' invalid'}`;
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
    const compare = r.valid && Array.isArray(r.comparison) ? r.comparison.map(compareRow).join('') : '';
    const state = r.valid
      ? (r.severity ? severityPill(r.severity) : '')
      : `<span class="tap-card-state badge bg-yellow-lt">${window.tiIcon ? tiIcon('alert-triangle') : ''}Not reliable</span>`;
    card.innerHTML = `<div class="card-body">
      <div class="tap-card-head">
        <h3 class="card-title">${capitalise(hand)} hand</h3>
        ${state}
      </div>
      ${warnings ? `<ul class="tap-warnings">${warnings}</ul>` : ''}
      ${compare ? `<div class="tap-compare">${compare}</div>` : ''}
      <details class="tap-more"><summary>View raw signal</summary>
        ${r.series ? `<div class="tap-charts">
          <figure><canvas class="tap-trace"></canvas><figcaption>Finger opening over 10 s · dots = detected taps</figcaption></figure>
          <figure><canvas class="tap-bars"></canvas><figcaption>Size of each tap · line = trend</figcaption></figure>
        </div>` : ''}
        ${metrics ? `<div class="tap-metrics">${metrics}</div>` : ''}
        <div class="tap-quality">${escapeHtml(quality)}</div>
      </details>
    </div>`;
    // the charts live in a closed drawer (no size until it opens), so draw them on open
    const drawer = card.querySelector('details');
    drawer.addEventListener('toggle', () => {
      if (!drawer.open) return;
      drawTrace(card.querySelector('.tap-trace'), r.series);
      drawBars(card.querySelector('.tap-bars'), r.amplitudes || []);
    });
    return card;
  }

  // MDS-UPDRS 3.4 severity band (Islam et al. 2023): how a neurologist would likely rate
  // this hand's tapping, from its speed and opening angle over the first 10 taps.
  function severityPill(s) {
    const mild = s.band === '2+';
    const icon = window.tiIcon ? tiIcon(mild ? 'alert-triangle' : 'circle-check') : '';
    return `<span class="sev-pill badge ${mild ? 'bg-yellow-lt sev-mild' : 'bg-green-lt sev-normal'}"
      title="Severity estimate, MDS-UPDRS 3.4 (Islam et al. 2023)"><span class="sev-pill-label">Severity</span>${icon}${escapeHtml(s.label)}</span>`;
  }

  function severityBadge(s) {
    const mild = s.band === '2+';
    const v = s.validation || {};
    const f = s.features || {};
    return `
      <div class="tap-severity ${mild ? 'sev-mild' : 'sev-normal'}">
        <div class="tap-severity-head">
          <span class="tap-severity-label">Severity estimate · MDS-UPDRS 3.4</span>
          <span class="tap-severity-band">${escapeHtml(s.label)}</span>
        </div>
        <div class="tap-severity-src">${escapeHtml(capitalise(s.source || ''))}${v.auc ? ` · AUC ${v.auc.toFixed(2)}` : ''}
          · first ${f.n_taps_used || 10} taps · opening ${Math.round(f.amplitude_median_denoised)}°</div>
      </div>`;
  }

  // One feature against the Kasemsap healthy / Parkinson's averages, using the same bar as
  // the spiral cards (healthy average at 20%, Parkinson's average at 80%).
  function fmtCompare(c, v) {
    if (v == null || !Number.isFinite(Number(v))) return '—';
    v = Math.round(Number(v)) || 0;   // || 0 turns -0 into 0
    if (c.unit === 'pts') return `${v > 0 ? '+' : ''}${v} pts`;
    if (c.unit === '%') return `${v}%`;
    return `${v}`;
  }

  const SHORT_LABELS = { count: 'Taps in 10 s', mean: 'Opening size', std: 'Size variability',
                         diff10: 'Size drop, tap 1→10' };

  function compareRow(c) {
    const valueOk = c.value != null && Number.isFinite(Number(c.value));
    const pin = valueOk ? gaugePosition({ value: c.value, ctrl_mean: c.healthy_mean, pd_mean: c.pd_mean }) : null;
    const pct = valueOk && c.pd_mean !== c.healthy_mean
      ? 100 * (c.value - c.healthy_mean) / (c.pd_mean - c.healthy_mean) : 0;
    const band = c.scored ? pctBand(pct) : 'pct-unscored';
    const tag = c.scored ? '' : '<span class="feature-tag">not scored</span>';
    return `
      <div class="tap-compare-row ${band}" title="${escapeHtml(c.help)}">
        <div class="tap-compare-head">
          <span class="tap-compare-label">${escapeHtml(SHORT_LABELS[c.key] || c.label)}${tag}</span>
          <span class="feature-value">${valueOk ? escapeHtml(fmtCompare(c, c.value)) : 'not measured'}</span>
        </div>
        <div class="gauge-track">
          <div class="gauge-tick" style="left:${GAUGE_HEALTHY}%"></div>
          <div class="gauge-tick" style="left:${GAUGE_PD}%"></div>
          ${pin == null ? '' : `<div class="gauge-pin" style="left:${pin}%"></div>`}
        </div>
        <div class="feature-refs">
          <span style="left:${GAUGE_HEALTHY}%">Healthy ${escapeHtml(fmtCompare(c, c.healthy_mean))}</span>
          <span style="left:${GAUGE_PD}%">PD ${escapeHtml(fmtCompare(c, c.pd_mean))}</span>
        </div>
      </div>`;
  }

  // Tapping score: each hand scored on speed, opening size, variability and shrinkage; the
  // result is the worse hand. Model checked on people it wasn't trained on.
  async function updateScore() {
    const R = results.right, L = results.left;
    if (!(R && L && R.valid && L.valid)) { scoreEl.classList.add('hidden'); return; }
    if (!SHOW_COMBINED_SCORE) {
      scoreEl.innerHTML = `<div class="tap-score-off">
        <strong>No single tapping score.</strong> Each measure below is shown against the published
        healthy and Parkinson's groups instead.</div>`;
      scoreEl.classList.remove('hidden');
      return;
    }
    const gen = generation;
    let s;
    try {
      const res = await fetch('/tapping/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ right: sessions.right, left: sessions.left }),
      });
      s = await res.json();
      if (!res.ok) throw new Error(s.detail || `Server returned ${res.status}`);
    } catch (err) {
      if (gen !== generation) return;
      scoreEl.innerHTML = `<div class="tap-score-note">No tapping score: ${escapeHtml(err.message)}</div>`;
      scoreEl.classList.remove('hidden');
      return;
    }
    if (gen !== generation) return;   // cleared while the score was on its way
    const band = s.band;
    const v = s.validation;
    const td = s.tap_difference;
    const hs = s.hands;
    // what pushed the worse hand's score up the most (positive push = toward the Parkinson's group)
    const REASONS = { count: 'fewer taps (slower)', mean: 'smaller openings', std: 'uneven tap sizes',
                      diff10: 'taps shrinking from tap 1 to 10' };
    const top = hs[s.worse_hand].inputs.filter(i => i.push > 0.25).sort((a, b) => b.push - a.push)[0];
    const reason = top
      ? `The ${s.worse_hand} hand counts, mainly because of ${REASONS[top.key]}.`
      : `The ${s.worse_hand} hand counts; no single measure stood out.`;
    const match = handMatch();
    const vcls = { 'band-low': 'v-low', 'band-moderate': 'v-moderate', 'band-high': 'v-high' }[band.cls] || '';
    scoreEl.className = `tap-score verdict card dx-banner ${bandUi(band.cls).bg} ${vcls}`;
    scoreEl.innerHTML = `
      <div class="verdict-main">
        <div class="verdict-kicker">Tapping result</div>
        <div class="verdict-band dx-band ${band.cls}">${bandHtml(band.cls, band.label)}</div>
        <div class="verdict-why">${escapeHtml(reason)}</div>
      </div>
      <div class="verdict-stats">
        <div class="verdict-stat">
          <div class="verdict-big"><span class="verdict-num ${band.cls}">${s.score}</span><span class="verdict-suffix">/100</span></div>
          <div class="verdict-cap">Similarity to Parkinson's group</div>
        </div>
        <div class="verdict-stat">
          <div class="verdict-mid">R ${hs.right.score} · L ${hs.left.score}</div>
          <div class="verdict-cap">Each hand (worse counts)</div>
        </div>
        ${match ? `<div class="verdict-stat">
          <div class="verdict-mid">${match.speed}% · ${match.size}%</div>
          <div class="verdict-cap">Left–right match (speed · size)</div>
        </div>` : ''}
        <button class="btn verdict-retest" type="button">${window.tiIcon ? tiIcon('refresh') : ''}Retest</button>
      </div>
      <div class="verdict-scale">Under ${s.bands.typical_below} typical · ${s.bands.typical_below}–${s.bands.elevated_from - 1} borderline ·
        ${s.bands.elevated_from}+ elevated · a probability of matching the Parkinson&#39;s group (50 = equally likely either group),
        not a percentage chance of having Parkinson&#39;s · not a diagnosis</div>`;
    scoreEl.querySelector('.verdict-retest').addEventListener('click', clearResults);
    scoreEl.classList.remove('hidden');
    countUp(scoreEl.querySelector('.verdict-num'), s.score);
    scoreEl.scrollIntoView({ behavior: (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'), block: 'start' });
    // sources and validation, once, in the footer
    const sev = (R.severity || L.severity || {}).validation;
    if (footerEl) {
      footerEl.textContent = `ⓘ Screening estimate, not a diagnosis. Score: compared with ${s.reference.n_healthy} healthy people `
        + `and ${s.reference.n_parkinsons} with Parkinson's (Kasemsap et al., PLOS ONE 2025); on people it wasn't trained on, `
        + `AUC ${v.auc.toFixed(2)}, caught ${Math.round(v.sensitivity * 100)}% of Parkinson's, cleared ${Math.round(v.specificity * 100)}% `
        + `of healthy people. Severity: ${sev ? `${sev.n_videos} neurologist-rated home videos` : 'neurologist-rated home videos'} `
        + `(Islam et al., npj Digital Medicine 2023)${sev ? `, AUC ${sev.auc.toFixed(2)}` : ''}. `
        + `Hands differ by ${td.value} taps (healthy average ${td.healthy_mean.toFixed(1)}).`;
    }
  }

  // speed and size match between the hands, 100% = identical
  function handMatch() {
    const R = results.right, L = results.left;
    const ok = r => r && r.valid && Number.isFinite(r.rate_hz) && Number.isFinite(r.amp_mean) && r.amp_mean > 0;
    if (!(ok(R) && ok(L))) return null;
    const ratio = (a, b) => Math.round(Math.min(a, b) / Math.max(a, b) * 100);
    return { speed: ratio(R.rate_hz, L.rate_hz), size: ratio(R.amp_mean, L.amp_mean) };
  }

  function renderAsymmetry() {
    if (SHOW_COMBINED_SCORE) { asymEl.classList.add('hidden'); return; }   // in the verdict banner instead
    const R = results.right, L = results.left;
    const ok = r => r && r.valid && Number.isFinite(r.rate_hz) && Number.isFinite(r.amp_mean);
    if (!(ok(R) && ok(L))) { asymEl.classList.add('hidden'); return; }
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
  window.drawdxTapping = { results, sessions, renderResults, updateScore, updateButtons, showTapping, showSpiral, clearResults };
})();
