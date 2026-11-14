/* Insights: "Your year" (a Wrapped-style story) and "Explore" (filters + a question -> chart, through the insight rails). */
(function () {
'use strict';
const A = () => window.AimoApp;
const I = { source: 'demo', tab: 'year', site: '', card: 0, wrapped: null, ex: { filters: {}, prompt: '', answer: null, loading: false, view: 'chart', steps: false, asked: [] } };
const STARTERS = ['Spend by month', 'Top 10 products by spend, rest as other', 'Waste % by kitchen compared to previous period, last 3 months',
  'Category mix per kitchen', 'Carbon footprint by category, share', 'Orders by weekday and kitchen as a heatmap', 'Spend and waste % by product'];
const STEP_WORDS = { start_analysis: 'Opened your data', describe_data: 'Looked at what can be asked', get_values: 'Checked the values', run_query: 'Asked the question',
  suggest_chart: 'Picked the chart types that fit', build_chart: 'Drew the chart', explain_result: 'Wrote the summary' };

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function vegaConfig() {
  const cat = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => css('--ev-' + i));
  return {
    background: null, font: 'Figtree, system-ui, sans-serif', padding: 4, view: { stroke: null },
    axis: { labelColor: css('--muted'), titleColor: css('--muted'), gridColor: css('--outline'), domainColor: css('--outline'), tickColor: css('--outline'),
      labelFontSize: 12, titleFontSize: 12, titleFontWeight: 500, gridOpacity: 0.7 },
    legend: { labelColor: css('--fg'), titleColor: css('--muted'), labelFontSize: 12, titleFontSize: 12, orient: 'bottom', symbolType: 'circle' },
    title: { color: css('--fg'), fontSize: 14, fontWeight: 600, anchor: 'start' },
    range: { category: cat, ordinal: { scheme: 'teals' }, ramp: [css('--seq-1'), css('--seq-2'), css('--seq-3')], heatmap: [css('--seq-1'), css('--seq-2'), css('--seq-3')] },
    mark: { color: cat[0] }, bar: { color: cat[0] }, line: { color: cat[0] }, point: { color: cat[0], size: 50, filled: true },
    area: { color: cat[0] }, arc: { stroke: css('--surface'), strokeWidth: 2 }, rect: { stroke: css('--surface'), strokeWidth: 2 },
    text: { color: css('--fg'), font: 'Figtree, system-ui, sans-serif' },
    style: { anomaly: { stroke: css('--surface') } },  // unusual periods: a surface ring keeps them legible on the line
  };
}

function draw(el, spec) {
  if (!el || !spec) return;
  if (spec.type === 'table' || !window.vegaEmbed) { el.innerHTML = table(spec); return; }
  const s = JSON.parse(JSON.stringify(spec));
  s.config = Object.assign(vegaConfig(), s.config || {});
  s.autosize = { type: 'fit-x', contains: 'padding' };
  window.vegaEmbed(el, s, { actions: false, renderer: 'svg' }).catch(() => { el.innerHTML = table(spec); });
}

function table(spec) {
  const { esc } = A();
  const rows = spec.rows || (spec.data && spec.data.values) || [];
  const cols = spec.columns || (rows[0] ? Object.keys(rows[0]).map((n) => ({ name: n, label: n })) : []);
  const f = (v) => (typeof v === 'number' ? v.toLocaleString('en-US', { maximumFractionDigits: 1 }) : esc(v ?? '–'));
  return `<div class="tbl-wrap"><table class="tbl compact"><thead><tr>${cols.map((c) => `<th scope="col">${esc(c.label)}</th>`).join('')}</tr></thead>
    <tbody>${rows.slice(0, 200).map((r) => `<tr>${cols.map((c) => `<td class="${typeof r[c.name] === 'number' ? 'num r' : ''}">${f(r[c.name])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

async function load() {
  const { API, S } = A();
  if (!I.sites) { try { I.sites = ((await API.kitchens(S.buyerId)) || {}).sites || []; } catch (e) { I.sites = []; } }
  if (I.tab === 'year' && !I.wrapped) {
    try { I.wrapped = await API.wrapped(S.buyerId, I.site, I.source); } catch (e) { I.wrapped = { cards: [] }; }
  }
  if (I.tab === 'explore' && !I.ex.answer && !I.ex.loading) await ask(STARTERS[0]);
  if (S.view === 'insights') A().renderView();
}
function reset() { I.wrapped = null; I.sites = null; I.site = ''; I.card = 0; I.ex.answer = null; I.ex.asked = []; I.ex.filters = {}; }

function siteSelect(id) {
  const { esc } = A();
  return `<select id="${id}" aria-label="Kitchen"><option value="">All kitchens</option>${(I.sites || []).map((s) => `<option value="${s.id}" ${(id === 'y-site' ? I.site : I.ex.filters.siteId) === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>`;
}

function yearView() {
  const { esc, ic } = A();
  const cards = (I.wrapped && I.wrapped.cards) || [];
  if (!I.wrapped) return '<p class="muted">Loading your year…</p>';
  const c = cards[Math.min(I.card, cards.length - 1)] || {};
  return `<div class="story-bar">${siteSelect('y-site')}<span class="muted">${esc(I.wrapped.title || '')}</span></div>
    <div class="story" data-kind="${esc(c.kind || '')}" tabindex="0" aria-roledescription="story" aria-label="Card ${I.card + 1} of ${cards.length}">
      <div class="story-prog">${cards.map((_, i) => `<i class="${i < I.card ? 'done' : i === I.card ? 'now' : ''}"></i>`).join('')}</div>
      <div class="story-body">
        <span class="story-eyebrow">${esc(c.eyebrow || '')}</span>
        <h2 class="story-h">${esc(c.headline || '')}</h2>
        ${c.sub ? `<p class="story-sub">${esc(c.sub)}</p>` : ''}
        ${(c.numbers || []).length ? `<div class="story-nums">${c.numbers.map((n) => `<div><b class="num">${esc(n.value)}</b><span>${esc(n.label)}</span></div>`).join('')}</div>` : ''}
        ${c.chart ? '<div class="story-chart" id="story-chart"></div>' : ''}
      </div>
      <button class="story-nav prev" data-ycard="-1" aria-label="Previous" ${I.card === 0 ? 'disabled' : ''}>${ic('chevl')}</button>
      <button class="story-nav next" data-ycard="1" aria-label="Next" ${I.card >= cards.length - 1 ? 'disabled' : ''}>${ic('chevr')}</button>
    </div>
    <div class="story-foot"><span class="muted num">${I.card + 1} / ${cards.length}</span>${I.card >= cards.length - 1 ? `<button class="btn primary" data-itab="explore">${ic('spark')} Explore your data</button>` : `<button class="btn" data-ycard="1">Next</button>`}</div>`;
}

function exploreView() {
  const { esc, ic } = A();
  const ex = I.ex, a = ex.answer;
  const f = ex.filters;
  const sel = (id, label, opts, val) => `<select id="${id}" aria-label="${label}"><option value="">${label}</option>${opts.map(([v, l]) => `<option value="${v}" ${val === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
  let body = '';
  if (ex.loading) body = '<div class="typing" role="status"><i></i>Asking your data</div>';
  else if (a && a.offline) body = `<div class="card"><div class="card-t">This preview has a few recorded questions. Try one:</div><div class="chips">${a.examples.map((e) => `<button class="fchip" data-ask="${esc(e)}">${esc(e)}</button>`).join('')}</div></div>`;
  else if (a && a.error) body = `<div class="card" data-type="cant_do"><div class="card-t">${esc(a.error)}</div></div>`;
  else if (a) {
    body = `<article class="answer">
      <div class="answer-h"><div><h2>${esc(a.caption)}</h2>${(a.assumed || []).length ? `<p class="muted">${esc(a.assumed.join(' '))}</p>` : ''}</div>
        <div class="seg-ctl small" role="group" aria-label="Show as"><button data-exview="chart" aria-pressed="${ex.view === 'chart'}">Chart</button><button data-exview="table" aria-pressed="${ex.view === 'table'}">Table</button></div></div>
      <div id="ex-chart" class="ex-chart"></div>
      <ul class="facts">${(a.facts || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
      <button class="why-link" data-exsteps aria-expanded="${ex.steps}">How I made this</button>
      ${ex.steps ? `<ol class="timeline">${(a.steps || []).map((s) => `<li><b>${esc(STEP_WORDS[s.tool] || s.tool)}</b>${s.tool === 'run_query' ? `<small><code>${esc(JSON.stringify(s.args))}</code></small>` : ''}${s.error ? `<small>Fixed: ${esc(s.error.message)}</small>` : ''}</li>`).join('')}</ol>
        <p class="muted small">${a.engine === 'claude' ? 'Answered by Claude Haiku using the insight tools.' : 'Answered by the built-in rules using the insight tools.'} Any agent can call the same tools over the API or MCP.</p>` : ''}
    </article>`;
  }
  return `<div class="ask-bar">
      <form class="ask" id="ask-form"><span>${ic('spark')}</span><input id="ex-q" placeholder="Ask anything, e.g. waste by kitchen last 3 months" value="${esc(ex.prompt)}" aria-label="Your question"><button class="btn primary" type="submit">Ask</button></form>
      <div class="toolbar">${siteSelect('ex-site')}
        ${sel('ex-period', 'Whole year', [['last_month', 'This month'], ['last_3_months', 'Last 3 months'], ['last_6_months', 'Last 6 months']], f.period)}
        ${sel('ex-cat', 'All categories', ['Dairy', 'Meat', 'Fish', 'Fruit & veg', 'Bakery', 'Dry goods', 'Plant-based'].map((c) => [c, c]), f.category)}
        ${sel('ex-ev', 'All event types', ['Gala', 'Wedding', 'Conference', 'Christmas party', 'Birthday', 'Lunch'].map((c) => [c, c]), f.event_type)}</div>
      <div class="chips starters">${STARTERS.map((s) => `<button class="fchip ${ex.prompt === s ? 'on' : ''}" data-ask="${esc(s)}">${esc(s)}</button>`).join('')}</div>
    </div>${body}`;
}

function view() {
  const { esc, S, KITCHENS } = A();
  if (!I.sites && !I.loadingStarted) { I.loadingStarted = true; load().finally(() => { I.loadingStarted = false; }); }
  return `<div class="wrap wide"><div class="page-h"><h1>Insights</h1><span class="muted">${esc(KITCHENS[S.buyerId].name)}</span>
    ${A().S.mode === 'live' ? `<div class="seg-ctl small src-switch" role="group" aria-label="Data"><button data-isrc="demo" aria-pressed="${I.source !== 'live'}">Demo history</button><button data-isrc="live" aria-pressed="${I.source === 'live'}">${I.source === 'live' ? '<span class="live-dot"></span>' : ''}Live orders</button></div>` : ''}
    <div class="seg-ctl" role="tablist" aria-label="Insights"><button role="tab" data-itab="year" aria-selected="${I.tab === 'year'}" aria-pressed="${I.tab === 'year'}">Your year</button><button role="tab" data-itab="explore" aria-selected="${I.tab === 'explore'}" aria-pressed="${I.tab === 'explore'}">Explore</button></div></div>
    ${I.tab === 'year' ? yearView() : exploreView()}</div>`;
}

function after() {
  if (I.tab === 'year' && I.wrapped) {
    const c = (I.wrapped.cards || [])[I.card];
    if (c && c.chart) draw(document.getElementById('story-chart'), Object.assign({}, c.chart, { height: 170 }));
  }
  if (I.tab === 'explore' && I.ex.answer && I.ex.answer.chart) {
    const a = I.ex.answer;
    draw(document.getElementById('ex-chart'), I.ex.view === 'table' ? { type: 'table', columns: a.columns, rows: a.rows } : a.chart);
  }
}

async function ask(prompt) {
  const { API, S } = A();
  const seq = (I.ex.seq = (I.ex.seq || 0) + 1);  // only the latest question's answer is shown
  I.ex.prompt = prompt; I.ex.loading = true; I.ex.steps = false;
  if (S.view === 'insights') A().renderView();
  const f = I.ex.filters;
  let answer;
  try {
    answer = await API.ask(S.buyerId, prompt, { period: f.period, category: f.category, event_type: f.event_type }, f.siteId, I.source);
  } catch (e) { answer = { error: e.message || 'That question could not be answered.' }; }
  if (seq !== I.ex.seq) return;  // a newer question was asked meanwhile
  I.ex.answer = answer;
  I.ex.loading = false;
  if (S.view === 'insights') A().renderView();
}

async function click(t, d) {
  if (d.isrc) { I.source = d.isrc; I.wrapped = null; I.card = 0; I.ex.answer = null; A().renderView(); await load(); return true; }
  if (d.itab) { I.tab = d.itab; A().renderView(); await load(); return true; }
  if (d.ycard) { const n = (I.wrapped.cards || []).length; I.card = Math.max(0, Math.min(n - 1, I.card + +d.ycard)); A().renderView(); return true; }
  if (d.ask) { await ask(d.ask); return true; }
  if (d.exview) { I.ex.view = d.exview; A().renderView(); return true; }
  if ('exsteps' in d) { I.ex.steps = !I.ex.steps; A().renderView(); return true; }
  return false;
}

document.addEventListener('submit', (e) => { if (e.target.id === 'ask-form') { e.preventDefault(); const v = document.getElementById('ex-q').value.trim(); if (v) ask(v); } });
document.addEventListener('change', async (e) => {
  const id = e.target.id, v = e.target.value || undefined;
  if (id === 'y-site') { I.site = v || ''; I.wrapped = null; I.card = 0; await load(); }
  const map = { 'ex-site': 'siteId', 'ex-period': 'period', 'ex-cat': 'category', 'ex-ev': 'event_type' };
  if (map[id]) { I.ex.filters[map[id]] = v; await ask(I.ex.prompt || STARTERS[0]); }
});
document.addEventListener('keydown', (e) => {
  if (A() && A().S.view === 'insights' && I.tab === 'year' && !/INPUT|SELECT|TEXTAREA/.test((e.target.tagName || ''))) {
    if (e.key === 'ArrowRight') click(null, { ycard: '1' });
    if (e.key === 'ArrowLeft') click(null, { ycard: '-1' });
  }
});
let sx = null;
document.addEventListener('touchstart', (e) => { if (e.target.closest && e.target.closest('.story')) sx = e.touches[0].clientX; }, { passive: true });
document.addEventListener('touchend', (e) => { if (sx == null) return; const dx = e.changedTouches[0].clientX - sx; sx = null; if (Math.abs(dx) > 40) click(null, { ycard: dx < 0 ? '1' : '-1' }); });

window.AimoInsights = { view, after, load, reset, click, draw };
})();
