/* Kitchens: a CRM-style view of every site in the organisation, with a detail panel per site. */
(function () {
'use strict';
const A = () => window.AimoApp;
const K = { data: null, tab: 'overview' };
const eur = (v) => (v == null ? '–' : '€' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }));
const initials = (n) => n.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();

function spark(values, w = 120, h = 34) {
  if (!values || values.length < 2) return '';
  const max = Math.max(...values), min = Math.min(...values);
  const x = (i) => (i * (w - 4)) / (values.length - 1) + 2, y = (v) => h - 3 - ((v - min) / ((max - min) || 1)) * (h - 8);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = values.length - 1;
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="Spend over 12 months">
    <polygon points="${x(0)},${h} ${pts} ${x(last)},${h}" fill="var(--primary-soft)"/>
    <polyline points="${pts}" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(last)}" cy="${y(values[last])}" r="3.5" fill="var(--primary)"/></svg>`;
}

async function load() {
  const { API, S } = A();
  try { K.data = await API.kitchens(S.buyerId); } catch (e) { K.data = null; }
  if (S.view === 'settings') A().renderView();
}

function siteCard(s) {
  const { esc, ic } = A();
  const waste = s.wastePct == null ? '–' : s.wastePct.toFixed(1) + '%';
  return `<button class="site" data-ksite="${esc(s.id)}">
    <span class="site-h"><span class="av big">${esc(initials(s.name.replace('Pohjola ', 'P ')))}</span><span><b>${esc(s.name)}</b><small>${esc(s.type)}</small></span></span>
    <span class="site-kpis"><span><b class="num">${eur(s.spendMonth)}</b><small>last 30 days</small></span><span><b class="num">${waste}</b><small>left over</small></span><span><b class="num">${s.onTimePct == null ? '–' : Math.round(s.onTimePct) + '%'}</b><small>on time</small></span></span>
    ${spark(s.trend, 240, 40)}
    <span class="site-foot">${ic('pin')}<span>${esc(s.address)}</span><span class="av sm" title="${esc(s.lead)}">${esc(initials(s.lead))}</span></span></button>`;
}

function view() {
  const { esc, ic, S, KITCHENS, store } = A();
  if (!K.data && !K.loading) { K.loading = true; load().finally(() => { K.loading = false; }); }
  const d = K.data;
  const theme = store.get('theme', 'system');
  const orgs = Object.entries(KITCHENS).map(([id, k]) => `<button class="org-pick ${id === S.buyerId ? 'on' : ''}" data-buyer="${id}" aria-pressed="${id === S.buyerId}"><span class="av">${esc(k.initials)}</span>${esc(k.name)}</button>`).join('');
  if (!d) return `<div class="wrap wide"><div class="page-h"><h1>Kitchens</h1></div><div class="org-row">${orgs}</div><p class="muted">Loading…</p></div>`;
  const credit = d.org.openInvoices / d.org.creditLimit * 100;
  return `<div class="wrap wide"><div class="page-h"><h1>Kitchens</h1><span class="muted">${d.sites.length} ${d.sites.length === 1 ? 'site' : 'sites'}</span></div>
    <div class="org-row" aria-label="Organisation">${orgs}</div>
    <section class="org">
      <div class="org-main"><span class="av xl">${esc(KITCHENS[S.buyerId].initials)}</span><div><h2>${esc(d.org.name)}</h2><p class="muted">${esc(d.org.segment)}</p></div></div>
      <div class="org-stats">
        <div><small>Credit in use</small><b class="num">${eur(d.org.openInvoices)} <span class="muted">of ${eur(d.org.creditLimit)}</span></b><span class="meter"><i style="width:${Math.min(100, credit).toFixed(0)}%"></i></span></div>
        <div><small>People who OK orders</small><span class="avs">${d.org.approvers.map((a) => `<span class="av" title="${esc(a.name)}, ${esc(a.role)}">${esc(initials(a.name))}</span>`).join('')}</span></div>
        <div><small>Prices</small><b>${d.liveApi ? 'Live from Valio Aimo' : 'Demo prices'}</b></div>
      </div>
    </section>
    <div class="sites">${d.sites.map(siteCard).join('')}</div>
    <div class="grid2">
      <section class="section"><h2>Favourites, all sites</h2><div class="list">${d.favourites.map((f) => `<div class="li">${A().ic('star')}<span>${esc(f.name)}</span>${f.pinned ? '<small class="tag-s">Always first</small>' : ''}</div>`).join('') || '<div class="li"><span>None yet<small>I remember what you pick.</small></span></div>'}</div></section>
      <section class="section"><h2>Your rules</h2><div class="list">${d.limits.map((l) => `<div class="li"><span>${esc(l.label)}</span><b class="num">${eur(l.value)}</b></div>`).join('')}
        <div class="li"><span>Never order<small>${d.allergens.length ? esc(d.allergens.map((a) => ({ nuts: 'nuts', peanuts: 'peanuts', sesame: 'sesame', milk: 'milk' }[a] || a)).join(', ')) : 'Nothing blocked'}</small></span></div></div></section>
    </div>
    <section class="section"><h2>Appearance</h2><div class="seg-ctl" role="group" aria-label="Theme">${['system', 'light', 'dark'].map((t) => `<button data-theme-set="${t}" aria-pressed="${theme === t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div></section>
    <section class="section"><h2>How it works</h2><p class="muted">Every assistant, ours or any other, follows the same steps, checked by the gateway: understand, recall your favourites first, look further only for gaps, plan, check your rules, show cards, order, learn. Questions about your data follow a second set: describe, ask, choose a chart, explain.</p>
      ${S.mode === 'live' ? `<div class="acts"><button class="btn" data-reset>${ic('chat')} Start the demo again</button><button class="btn" data-opsview>${ic('insights')} Valio Aimo view</button></div>
      <p class="muted small">Demo switch: what Valio Aimo sees across customers, never one customer alone.</p>` : ''}</section></div>`;
}

// ---------------------------------------------------------------- Valio Aimo view (operations, demo switch)
const pct = (v) => (v == null ? '–' : Math.round(v) + '%');
const secs = (v) => (v == null ? '–' : v < 90 ? Math.round(v) + ' s' : Math.round(v / 60) + ' min');

async function openOps() {
  const { API, openPanel } = A();
  openPanel('ops', 'Valio Aimo view', '<p class="muted">Loading…</p>');
  try {
    const [m, d, l] = await Promise.all([API.ops('metrics'), API.ops('demand?by=day'), API.ops('lost-sales')]);
    K.ops = { m, d, l };
  } catch (e) { K.ops = { error: e.message }; }
  openPanel('ops', 'Valio Aimo view', opsHtml());
  after();
}

function opsHtml() {
  const { esc } = A();
  const o = K.ops || {};
  if (o.error) return `<p class="muted">${esc(o.error)}</p>`;
  const c = o.m.channel;
  const k = o.m.kAnonymity;
  const tiles = c ? [['Ordered without a human', pct(c.autonomous_rate)], ['Needed an OK', pct(c.approval_rate)], ['Fill rate', pct(c.fill_rate)],
    ['Re-quoted', pct(c.requote_rate)], ['Approval wait (90%)', secs(c.p90_approval_wait)], ['Agent sessions', c.sessions]] : [];
  const lost = o.l.rows.length ? `<div class="list">${o.l.rows.map((r) => `<div class="li"><span>${esc(r.why)}<small>${r.lines} ${r.lines === 1 ? 'need' : 'needs'}</small></span><b class="num">${Math.round(r.unmet_qty)} units</b></div>`).join('')}</div>`
    : `<p class="muted">Nothing to show yet: each reason needs at least ${k} customers.${o.l.suppressed ? ` ${o.l.suppressed} hidden.` : ''}</p>`;
  return `<p class="muted">Agents say what they need before they order: a date, an amount, a diet. Across customers, grouped so that no group shows fewer than ${k} customers.</p>
    <h3 class="day-h">Agent channel</h3>
    ${c ? `<div class="site-kpis ops-kpis">${tiles.map(([t, v]) => `<span><b class="num">${esc(v)}</b><small>${esc(t)}</small></span>`).join('')}</div>` : `<p class="muted">${esc(o.m.note || '')}</p>`}
    <h3 class="day-h">Planned need, by delivery day</h3>
    ${o.d.chart ? '<div id="ops-demand" class="ex-chart short"></div>' : `<p class="muted">Nothing to show yet (fewer than ${k} customers per day).</p>`}
    ${o.d.suppressed ? `<p class="muted small">${o.d.suppressed} ${o.d.suppressed === 1 ? 'day has' : 'days have'} fewer than ${k} customers, so ${o.d.suppressed === 1 ? 'it is' : 'they are'} hidden.</p>` : ''}
    <h3 class="day-h">What agents could not get</h3>${lost}`;
}

function after() {
  const { S } = A();
  if (S.panel && S.panel.kind === 'ops' && K.ops && K.ops.d && K.ops.d.chart) window.AimoInsights.draw(document.getElementById('ops-demand'), K.ops.d.chart);
}

function openSite(id) {
  const { esc, openPanel, ic } = A();
  const s = K.data.sites.find((x) => x.id === id);
  const d = K.data;
  const tabs = [['overview', 'Overview'], ['people', 'People'], ['deliveries', 'Deliveries'], ['rules', 'Rules']];
  const body = {
    overview: `<div class="site-kpis big"><span><b class="num">${eur(s.spendMonth)}</b><small>last 30 days</small></span><span><b class="num">${s.ordersMonth}</b><small>orders</small></span><span><b class="num">${s.wastePct == null ? '–' : s.wastePct.toFixed(1) + '%'}</b><small>left over</small></span></div>
      <div><div class="day-h">Spend, last 12 months</div>${spark(s.trend, 360, 80)}</div>
      <div class="acts"><button class="btn primary" data-kgo="insights">${ic("insights")} See insights</button><button class="btn" data-kgo="orders">${ic('board')} Orders</button></div>`,
    people: `<div class="list">${[{ name: s.lead, role: 'Kitchen lead' }].concat(d.org.approvers.filter((a) => a.name !== s.lead)).map((p) => `<div class="li"><span class="av">${esc(initials(p.name))}</span><span>${esc(p.name)}<small>${esc(p.role)}${d.org.approvers.some((a) => a.name === p.name) ? ' · can OK orders' : ''}</small></span></div>`).join('')}</div>`,
    deliveries: `<dl class="kv"><dt>Address</dt><dd>${esc(s.address)}</dd><dt>Delivery days</dt><dd><span class="chips">${s.deliveryDays.map((x) => `<span class="chip found">${x}</span>`).join('')}</span></dd><dt>Time</dt><dd>In the morning</dd><dt>Order by</dt><dd>17:00 the day before</dd></dl>`,
    rules: `<div class="list">${d.limits.map((l) => `<div class="li"><span>${esc(l.label)}</span><b class="num">${eur(l.value)}</b></div>`).join('')}</div><p class="muted">Rules are shared by all kitchens in ${esc(d.org.name)}.</p>`,
  };
  openPanel('site', s.name, `<p class="muted">${esc(s.type)}</p><div class="seg-ctl small" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-ktab="${k}" data-kid="${esc(id)}" aria-selected="${K.tab === k}" aria-pressed="${K.tab === k}">${l}</button>`).join('')}</div>${body[K.tab]}`, id);
}

async function click(t, d) {
  if (d.opsview !== undefined) { await openOps(); return true; }
  if (d.ksite) { K.tab = 'overview'; K.open = d.ksite; openSite(d.ksite); return true; }
  if (d.ktab) { K.tab = d.ktab; openSite(d.kid); return true; }
  if (d.kgo) {
    const { S } = A();
    S.panel = null; S.view = d.kgo;
    if (d.kgo === 'insights') { window.AimoInsights.reset(); }
    A().render();
    if (d.kgo === 'insights') window.AimoInsights.load();
    if (d.kgo === 'orders') window.AimoOrders.load();
    return true;
  }
  return false;
}

window.AimoKitchens = { view, after, load, click, reset: () => { K.data = null; } };
})();
