/* Orders, Jira style: Board (columns) or List (rows), group into swimlanes by status / event / kitchen,
 * search + quick filters, event colour labels, keys (POH-901), history of a year, activity timeline. */
(function () {
'use strict';
const A = () => window.AimoApp;
const STATUSES = [['planning', 'Planning'], ['waiting', 'Waiting for OK'], ['ordered', 'Ordered'], ['delivered', 'Delivered'], ['done', 'Done']];
const O = { mode: null, group: 'status', q: '', site: '', quick: {}, page: 1, size: 50, sort: 'date', dir: 'desc', hist: null, loading: false };
const colorOf = (name) => (name ? [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 8 + 1 : null);
const eur = (v) => (v == null ? '' : '€' + Number(v).toLocaleString('en-US', { maximumFractionDigits: v >= 100 ? 0 : 2 }));
const dl = (d) => { if (!d) return ''; const x = new Date(d + 'T12:00:00'); return x.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + x.getDate() + '.' + (x.getMonth() + 1) + '.'; };

function mode() {
  if (!O.mode) O.mode = A().store.get('ordersMode', window.matchMedia('(max-width: 860px)').matches ? 'list' : 'board');
  return O.mode;
}

async function load() {
  const { API, S } = A();
  O.loading = true;
  try {
    O.hist = await API.history(S.buyerId, { page: O.page, size: O.size, q: O.q, siteId: O.site, sort: O.sort, dir: O.dir });
    if (!O.sites) { const k = await API.kitchens(S.buyerId); O.sites = (k && k.sites) || []; }
  } catch (e) { O.hist = { orders: [], total: 0, page: 1, size: O.size }; }
  O.loading = false;
  if (S.view === 'orders') A().renderView();
}

function reset() { O.hist = null; O.sites = null; O.site = ''; O.q = ''; O.page = 1; O.quick = {}; }

// one shape for live tickets and past orders
function liveItems() {
  return A().boardItems().map((i) => Object.assign({}, i, { live: true }));
}
function histItems() {
  return ((O.hist && O.hist.orders) || []).map((o) => ({
    id: o.id, key: o.key, live: false, status: 'done', statusLabel: 'Done', type: o.type === 'event' ? 'event' : 'order',
    title: o.event || 'Regular delivery', subtitle: `${o.lines} products · ${o.site}`, site: o.site, siteId: o.siteId,
    due: o.date, total: o.total, totalLabel: eur(o.total), eventColor: o.event ? colorOf(o.event) : null, eventName: o.event,
    outcome: o.outcome, onTime: o.onTime,
  }));
}

function filtered(includeHistory) {
  const now = new Date('2026-11-13T12:00:00');
  const week = new Date(now); week.setDate(now.getDate() + 7);
  let items = liveItems();
  if (includeHistory) items = items.concat(histItems());
  const q = O.q.toLowerCase();
  return items.filter((i) => {
    if (q && ![i.key, i.title, i.subtitle, i.site, i.eventName].some((x) => String(x || '').toLowerCase().includes(q))) return false;
    if (O.site && i.siteId && i.siteId !== O.site) return false;
    if (O.quick.needsOk && i.status !== 'waiting') return false;
    if (O.quick.events && i.type !== 'event') return false;
    if (O.quick.week && !(i.due && new Date(i.due + 'T12:00:00') <= week && new Date(i.due + 'T12:00:00') >= now)) return false;
    if (O.event && i.eventName !== O.event) return false;
    return true;
  });
}

function label(i) {
  return i.eventColor ? `<span class="ev-label" style="--ev: var(--ev-${i.eventColor})">${A().esc(i.eventName.length > 22 ? i.eventName.slice(0, 21) + '…' : i.eventName)}</span>` : '<span class="ev-label plain">Regular</span>';
}

function card(i) {
  const { esc } = A();
  return `<button class="tk ${i.eventColor ? 'has-ev' : ''}" style="${i.eventColor ? `--ev: var(--ev-${i.eventColor})` : ''}" data-open="${esc(i.id)}" data-live="${i.live ? 1 : 0}">
    <span class="tk-top"><span class="tk-key">${esc(i.key)}</span>${label(i)}</span>
    <b>${esc(i.title)}</b><small>${esc(i.subtitle)}</small>
    <span class="tk-foot"><span class="tk-due">${i.due ? A().ic('clip') + esc(dl(i.due)) : ''}</span><span class="num">${esc(i.totalLabel || '')}</span></span></button>`;
}

function lanes(items) {
  if (O.group === 'status') return [{ id: '', label: '', items }];
  const key = O.group === 'event' ? (i) => i.eventName || 'Regular deliveries' : (i) => i.site || 'Kitchen';
  const map = new Map();
  for (const i of items) { const k = key(i); if (!map.has(k)) map.set(k, []); map.get(k).push(i); }
  return [...map.entries()].map(([k, v]) => ({ id: k, label: k, items: v, color: O.group === 'event' && v[0].eventColor }));
}

function boardHtml(items) {
  const { esc } = A();
  return lanes(items).map((ln) => `${ln.label ? `<div class="lane-h">${ln.color ? `<i class="dot" style="background: var(--ev-${ln.color})"></i>` : ''}${esc(ln.label)} <span class="muted">${ln.items.length}</span></div>` : ''}
    <div class="board5">${STATUSES.map(([s, l]) => {
      const cs = ln.items.filter((i) => i.status === s);
      const shown = s === 'done' ? cs.slice(0, 12) : cs;
      return `<section class="col5" aria-label="${l}"><h2>${l}<span>${cs.length}</span></h2>${shown.map(card).join('') || '<div class="col-empty">Nothing here</div>'}${cs.length > shown.length ? `<button class="btn text" data-omode="list">See all ${cs.length}</button>` : ''}</section>`;
    }).join('')}</div>`).join('');
}

function th(id, labelText) {
  const on = O.sort === id;
  return `<th scope="col"><button class="th ${on ? 'on' : ''}" data-osort="${id}">${labelText}${on ? (O.dir === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>`;
}

function listHtml(items) {
  const { esc } = A();
  const rows = (arr) => arr.map((i) => `<tr data-open="${esc(i.id)}" data-live="${i.live ? 1 : 0}" tabindex="0">
      <td class="k"><span class="stripe" style="background:${i.eventColor ? `var(--ev-${i.eventColor})` : 'var(--outline)'}"></span>${esc(i.key)}</td>
      <td><b>${esc(i.title)}</b><small>${esc(i.subtitle)}</small></td><td>${label(i)}</td><td>${esc(i.site || '')}</td>
      <td><span class="pill ${i.status}">${esc(i.statusLabel)}</span></td><td class="num">${esc(dl(i.due))}</td><td class="num r">${esc(i.totalLabel || '')}</td></tr>`).join('');
  const body = lanes(items).map((ln) => (ln.label ? `<tr class="grp"><td colspan="7">${ln.color ? `<i class="dot" style="background: var(--ev-${ln.color})"></i>` : ''}${esc(ln.label)} <span class="muted">${ln.items.length}</span></td></tr>` : '') + rows(ln.items)).join('');
  const total = (O.hist && O.hist.total) || 0;
  const from = (O.page - 1) * O.size + 1, to = Math.min(total, O.page * O.size);
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr>${th('key', 'Key')}<th scope="col">Summary</th><th scope="col">Event</th>${th('site', 'Kitchen')}<th scope="col">Status</th>${th('date', 'Due')}${th('total', 'Total')}</tr></thead><tbody>${body || '<tr><td colspan="7" class="muted">No orders match.</td></tr>'}</tbody></table></div>
    <div class="cards-m">${items.map(card).join('') || '<p class="muted">No orders match.</p>'}</div>
    <div class="pager"><span class="muted num">Past orders ${total ? `${from}–${to} of ${total.toLocaleString('en-US')}` : '0'}</span>
      <button class="ibtn" data-opage="-1" aria-label="Previous page" ${O.page <= 1 ? 'disabled' : ''}>${A().ic('chevl')}</button>
      <button class="ibtn" data-opage="1" aria-label="Next page" ${to >= total ? 'disabled' : ''}>${A().ic('chevr')}</button></div>`;
}

function view() {
  const { esc, ic, S, KITCHENS } = A();
  if (!O.hist && !O.loading) load();
  const m = mode();
  const items = filtered(true);
  const events = [...new Map(liveItems().concat(histItems()).filter((i) => i.eventName).map((i) => [i.eventName, i])).values()].slice(0, 8);
  const chip = (k, l) => `<button class="fchip ${O.quick[k] ? 'on' : ''}" data-oquick="${k}" aria-pressed="${!!O.quick[k]}">${O.quick[k] ? ic('check') : ''}${l}</button>`;
  return `<div class="wrap wide"><div class="page-h"><h1>Orders</h1><span class="muted">${esc(KITCHENS[S.buyerId].name)}</span>
      <div class="seg-ctl" role="group" aria-label="View"><button data-omode="board" aria-pressed="${m === 'board'}">${ic('board')}Board</button><button data-omode="list" aria-pressed="${m === 'list'}">${ic('list')}List</button></div></div>
    <div class="toolbar">
      <label class="search">${ic('search')}<input id="o-q" type="search" placeholder="Search orders, events, keys" value="${esc(O.q)}" aria-label="Search orders"></label>
      <select id="o-site" aria-label="Kitchen"><option value="">All kitchens</option>${(O.sites || []).map((s) => `<option value="${s.id}" ${O.site === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
      <select id="o-group" aria-label="Group by"><option value="status" ${O.group === 'status' ? 'selected' : ''}>No grouping</option><option value="event" ${O.group === 'event' ? 'selected' : ''}>Group by event</option><option value="site" ${O.group === 'site' ? 'selected' : ''}>Group by kitchen</option></select>
      ${chip('needsOk', 'Needs OK')}${chip('week', 'Due this week')}${chip('events', 'Events only')}
    </div>
    ${events.length ? `<div class="ev-legend" aria-label="Events">${events.map((e) => `<button class="ev-chip ${O.event === e.eventName ? 'on' : ''}" style="--ev: var(--ev-${e.eventColor})" data-oevent="${esc(e.eventName)}"><i></i>${esc(e.eventName)}</button>`).join('')}${O.event ? '<button class="btn text" data-oevent="">Clear</button>' : ''}</div>` : ''}
    ${m === 'board' ? boardHtml(items) : listHtml(items)}</div>`;
}

async function open(id, live) {
  const { S, API, esc, openPanel, openOrder, ic } = A();
  const isLive = live === undefined ? A().boardItems().some((x) => x.id === id) : live;
  if (isLive) {
    openOrder(id);
    try {
      const act = (await API.activity(id)).activity || [];
      if (act.length && S.panel && S.panel.id === id) {
        S.panel.html += `<section><div class="day-h">Activity</div><ol class="timeline">${act.map((a) => `<li><b>${esc(a.text)}</b><small>${esc(a.who)} · ${esc(new Date(a.at).toLocaleString('en-GB', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' }))}</small></li>`).join('')}</ol></section>`;
        A().render();
      }
    } catch (e) { /* timeline is optional */ }
    return;
  }
  const it = histItems().find((x) => x.id === id) || { id, key: id, title: id };
  const d = await API.orderDetail(S.buyerId, id);
  const lines = d.lines || [];
  openPanel('history', `${it.key} · ${it.title}`, `<div class="stepper">${STATUSES.map(() => '<i class="on"></i>').join('')}</div>
    <div class="acts"><span class="pill done">Done</span>${it.eventColor ? label(it) : ''}<span class="pill ${it.onTime ? 'ordered' : 'waiting'}">${it.onTime ? 'On time' : 'Late'}</span></div>
    <dl class="kv"><dt>Delivered</dt><dd>${esc(dl(it.due))}</dd><dt>Kitchen</dt><dd>${esc(it.site || '')}</dd><dt>Total</dt><dd class="num">${esc(it.totalLabel || '')}</dd><dt>How it went</dt><dd>${esc(it.outcome || '')}</dd></dl>
    <section><div class="day-h">${lines.length} products</div>${lines.map((l) => `<div class="item"><span>${esc(l.product)}<span class="src">${esc(l.outcome)}</span></span><b class="num">${esc(String(l.qty))} ${esc(l.unit)} · ${eur(l.value)}</b></div>`).join('') || '<p class="muted">Details are available in the full app.</p>'}</section>
    <div class="acts"><button class="btn" data-go="insights">${ic('insights')} See trends in Insights</button></div>`, id);
}

async function click(t, d) {
  if (d.omode) { O.mode = d.omode; A().store.set('ordersMode', O.mode); A().renderView(); return true; }
  if (d.oquick) { O.quick[d.oquick] = !O.quick[d.oquick]; A().renderView(); return true; }
  if (d.oevent !== undefined) { O.event = d.oevent || null; A().renderView(); return true; }
  if (d.osort) { O.dir = O.sort === d.osort && O.dir === 'desc' ? 'asc' : 'desc'; O.sort = d.osort === 'key' ? 'date' : d.osort; O.page = 1; await load(); return true; }
  if (d.opage) { O.page = Math.max(1, O.page + +d.opage); await load(); return true; }
  if (d.open) { await open(d.open, d.live === '1'); return true; }
  return false;
}

let qTimer;
document.addEventListener('input', (e) => {
  if (e.target.id === 'o-q') { O.q = e.target.value; clearTimeout(qTimer); qTimer = setTimeout(async () => { O.page = 1; await load(); const el = document.getElementById('o-q'); if (el) { el.focus(); el.setSelectionRange(O.q.length, O.q.length); } }, 250); }
});
document.addEventListener('change', async (e) => {
  if (e.target.id === 'o-site') { O.site = e.target.value; O.page = 1; await load(); }
  if (e.target.id === 'o-group') { O.group = e.target.value; A().renderView(); }
});
document.addEventListener('keydown', (e) => {
  const tr = e.target.closest && e.target.closest('tr[data-open]');
  if (tr && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(tr.dataset.open, tr.dataset.live === '1'); }
});
document.addEventListener('click', (e) => {
  const tr = e.target.closest && e.target.closest('tr[data-open]');
  if (tr) open(tr.dataset.open, tr.dataset.live === '1');
});

window.AimoOrders = { view, load, reset, click, open };
})();
