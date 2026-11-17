// Plain-language summary of every test done so far, written by Gemini (POST /summary,
// 01/llm_summary.py). app.js and tapping.js report their results here, and the same
// paragraph appears in both panels. The scores are the result: if the summary is switched
// off or fails, the cards simply stay hidden.
(() => {
  const state = { spiral: null, tapping: null, severity: null };
  let request = 0;
  let enabled = true;   // false once the server says it has no Gemini key

  const cards = () => ['spiral-summary', 'tap-summary']
    .map(id => document.getElementById(id)).filter(Boolean);

  function render(mode, text) {
    for (const card of cards()) {
      card.classList.toggle('hidden', mode === 'hidden');
      card.classList.toggle('llm-summary-loading', mode === 'loading');
      card.querySelector('.llm-summary-text').textContent =
        mode === 'loading' ? 'Writing a plain-language summary…' : (text || '');
    }
  }

  async function refresh() {
    const id = ++request;
    if (!enabled || !(state.spiral || state.tapping)) { render('hidden'); return; }
    render('loading');
    let data = null;
    try {
      const res = await fetch('/summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state),
      });
      if (res.ok) data = await res.json();
    } catch (_) { /* optional extra: never interrupt the results */ }
    if (id !== request) return;              // a newer result arrived while this one was out
    if (data && data.status === 'off') enabled = false;
    if (data && data.llm_summary) render('ok', data.llm_summary);
    else render('hidden');
  }

  window.prismSummary = {
    setSpiral(result) { state.spiral = result; refresh(); },
    clearSpiral() { if (state.spiral) { state.spiral = null; refresh(); } },
    // score: the /tapping/compare response; severity: {right, left} severity bands (or null)
    setTapping(score, severity) { state.tapping = score; state.severity = severity; refresh(); },
    clearTapping() { if (state.tapping) { state.tapping = null; state.severity = null; refresh(); } },
  };
})();
