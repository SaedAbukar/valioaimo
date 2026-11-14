/* Aimo Agent Gateway — UI (minimal Material 3). Destinations: Autopilot · Orders · Insights · Settings. */
(function (G) {
'use strict';
const C = G.AimoCore, F = G.AimoFlows;
const { BY_GTIN, BY_KEY, money, money0, fq, dayLabel, sum, r2, clone } = C;
const S = () => C.S;
const $ = s => document.querySelector(s);
const h = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ICONS = (G.AIMO_DATA && G.AIMO_DATA.icons) || {};
const ic = (n, cls = '') => { const d = ICONS[n] || ICONS['help_outline'] || ['', '']; return `<svg class="ms ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${d[/fill/.test(cls) ? 1 : 0]}</svg>`; };
const pct = x => x == null ? '–' : Math.round(x * 100) + '%';
const buyer = () => S().buyers[S().buyerId];
const dateL = iso => { const d = new Date(iso + 'T12:00:00Z'); return dayLabel(iso).slice(0, 3) + ' ' + d.getUTCDate() + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()]; };
const STATUS = { AUTO: ['Ordered', 'ok', 'check_circle'], NOTIFY: ['Ordered · notified', 'ok', 'check_circle'], APPROVE: ['Needs approval', 'approve', 'schedule'], BLOCK: ['Blocked', 'block', 'block'] };
const status = (txt, kind = '', icon) => `<span class="status ${kind}">${icon ? ic(icon) : ''}${h(txt)}</span>`;
const UI = G.AimoUI = { route: 'autopilot', ap: { text: F.GALA, mode: 'event', eventId: null, traceId: null }, orders: { filter: 'all', more: false }, how: { tab: 'arch', node: 'policy', ent: null }, audit: { view: 'buyer', verify: null }, prefs: {}, compare: [], busy: false };

// ---------------------------------------------------------------- chart (single hue, end label)
function chart(vals, opt = {}) {
  const pts = vals.map((v, i) => [i, v]).filter(p => p[1] != null); if (pts.length < 2) return '';
  const min = opt.min ?? Math.min(...pts.map(p => p[1])), max = opt.max ?? Math.max(...pts.map(p => p[1]));
  const X = i => i / (vals.length - 1) * 100, Y = v => 4 + (1 - (v - min) / ((max - min) || 1)) * 92;
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(2) + ' ' + Y(p[1]).toFixed(2)).join(' '); const last = pts[pts.length - 1];
  const grid = [4, 50, 96].map(y => `<line x1="0" x2="100" y1="${y}" y2="${y}" stroke="var(--outline-variant)" stroke-width="1" vector-effect="non-scaling-stroke"/>`).join('');
  const yl = [[4, max], [50, (min + max) / 2], [96, min]].map(([y, v]) => `<span class="small muted num" style="position:absolute;left:0;top:${y * 1.4 - 8}px">${h(opt.fmt ? opt.fmt(v) : v)}</span>`).join('');
  const xs = opt.labels || []; const xi = [0, Math.round((xs.length - 1) / 3), Math.round(2 * (xs.length - 1) / 3), xs.length - 1];
  return `<div style="position:relative;padding:0 52px 0 40px" role="img" aria-label="${h(opt.label || '')}, latest ${h(opt.fmt ? opt.fmt(last[1]) : last[1])}">${yl}<svg class="chart" viewBox="0 0 100 100" preserveAspectRatio="none" style="height:140px;overflow:visible">${grid}<path d="${d}" fill="none" stroke="var(--primary)" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg><span class="title-s num" style="position:absolute;right:0;top:${Y(last[1]) * 1.4 - 10}px">${h(opt.fmt ? opt.fmt(last[1]) : last[1])}</span><div class="row between small muted" style="margin-top:6px">${xi.map(i => `<span>${h(xs[i] || '')}</span>`).join('')}</div></div>`;
}

// ---------------------------------------------------------------- shell
const DEST = [['autopilot', 'auto_awesome', 'Autopilot'], ['orders', 'receipt_long', 'Orders'], ['insights', 'insights', 'Insights'], ['settings', 'settings', 'Settings']];
const CHILD = { preferences: 'Preferences', mandate: 'Mandate', allergens: 'Allergens and diets', agents: 'Agents', ops: 'Valio Aimo view', audit: 'Audit log', how: 'How it works', demo: 'Demo scenarios' };
const pendingN = () => S().approvals.filter(a => a.status === 'pending' && a.buyerId === S().buyerId).length;
const top = r => CHILD[r] ? 'settings' : r;
function nav() { return DEST.map(([id, icon, l]) => { const on = top(UI.route) === id; return `<a class="dest ${on ? 'on' : ''}" href="#${id}" aria-current="${on ? 'page' : 'false'}"><span class="ind">${ic(icon, on ? 'fill' : '')}${id === 'orders' && pendingN() ? `<span class="dot">${pendingN()}</span>` : ''}</span><span class="lbl">${l}</span></a>`; }).join(''); }
function render() {
  const child = CHILD[UI.route];
  $('#rail').innerHTML = `<div class="logo">${ic('hub', 'fill')}</div>` + nav();
  $('#navbar').innerHTML = nav();
  $('#topbar').innerHTML = `${child ? `<button class="iconbtn" data-act="back" aria-label="Back">${ic('arrow_back')}</button>` : ''}<h1>${child || { autopilot: 'Aimo', orders: 'Orders', insights: 'Insights', settings: 'Settings' }[UI.route]}</h1>${child ? '' : `<button class="btn text" data-act="org" aria-haspopup="menu" title="Organisation">${ic('apartment')}<span class="ellipsis" style="max-width:160px">${h(buyer().name.split(' – ')[0])}</span></button>`}`;
  const fn = SCREENS[UI.route] || SCREENS.autopilot;
  $('#main').innerHTML = `<div class="page ${['insights', 'ops', 'how', 'autopilot'].includes(UI.route) ? 'wide' : ''}">${fn()}</div>`;
}
G.AimoRender = render;
const go = r => { if (location.hash !== '#' + r) location.hash = r; else { UI.route = r; render(); } };
window.addEventListener('hashchange', () => { const r = location.hash.slice(1); if (SCREENS[r]) { UI.route = r; render(); $('#main').scrollTop = 0; } });
$('#main').addEventListener('scroll', e => $('#topbar').classList.toggle('lifted', e.target.scrollTop > 4));

function sheet(title, body, foot = '') {
  if (!$('#layer .scrim')) UI.lastFocus = document.activeElement;
  document.querySelectorAll('.snack').forEach(x => x.remove());
  $('#layer').innerHTML = `<div class="scrim" data-act="scrim"><div class="sheet" role="dialog" aria-modal="true" aria-label="${h(title)}"><div class="handle"></div><header><h2>${h(title)}</h2><button class="iconbtn" data-act="close" aria-label="Close">${ic('close')}</button></header><div class="sbody">${body}</div>${foot ? `<footer>${foot}</footer>` : ''}</div></div>`;
  const b = $('#layer .sheet [data-act=close]'); if (b) b.focus();
}
const closeSheet = () => { $('#layer').innerHTML = ''; if (UI.lastFocus && document.body.contains(UI.lastFocus)) UI.lastFocus.focus(); };
let snT; function snack(msg, act) { clearTimeout(snT); document.querySelectorAll('.snack').forEach(x => x.remove()); const el = document.createElement('div'); el.className = 'snack'; el.setAttribute('role', 'status'); el.innerHTML = `<span>${h(msg)}</span>${act ? `<button data-act="${act[1]}" ${act[2] || ''}>${act[0]}</button>` : ''}`; document.body.appendChild(el); snT = setTimeout(() => el.remove(), 5000); }
const li = (o) => `<${o.act ? 'button' : 'div'} class="li ${o.act ? '' : 'static'}" ${o.act ? `data-act="${o.act}"` : ''} ${o.attrs || ''}>${o.icon ? `<span class="lead">${ic(o.icon)}</span>` : ''}<span class="txt"><span class="body-l ellipsis">${o.title}</span>${o.sub ? `<span class="body muted ellipsis">${o.sub}</span>` : ''}</span>${o.trail != null ? `<span class="trail">${o.trail}</span>` : ''}${o.act && o.chev !== false ? `<span class="chev">${ic('chevron_right')}</span>` : ''}</${o.act ? 'button' : 'div'}>`;
const dataNote = tables => `<p class="small muted">Data: ${tables.map(t => `<button class="ent" data-act="dm" data-v="${t}">${t}</button>`).join(' ')}</p>`;

// =============================================================== AUTOPILOT
const SCREENS = {};
const curEvent = () => S().events.find(e => e.eventId === UI.ap.eventId) || null;
const curTrace = () => S().traces[UI.ap.traceId] || null;
SCREENS.autopilot = () => {
  const u = UI.ap; const hasResult = (u.mode === 'event' && curEvent() && curEvent().buyerId === S().buyerId) || (u.mode === 'order' && curTrace() && curTrace().buyerId === S().buyerId);
  if (hasResult && !u.expanded && !UI.busy) return `<div class="stack" style="gap:12px;padding-top:8px"><h2 class="display">What are you planning?</h2><button class="input row" data-act="expand" aria-label="Edit request: ${h(u.text)}" style="cursor:text;text-align:left;border-radius:var(--r-m);gap:12px"><span class="grow ellipsis body-l">${h(u.text)}</span>${ic('edit')}</button></div>` + resultHtml();
  let out = `<div class="stack" style="gap:16px;padding-top:8px"><h2 class="display">What are you planning?</h2>
    <div class="prompt"><label for="apText" class="hide">Request</label><textarea id="apText" class="input" rows="3" aria-label="What are you planning?" placeholder="Gala dinner on Saturday for 180 guests: salmon, beef tenderloin, chocolate mousse. 12 vegans." data-in="ap">${h(u.text)}</textarea><button class="iconbtn mic ${u.listening ? 'on' : ''}" data-act="mic" aria-label="${u.listening ? 'Stop listening' : 'Speak'}">${ic(u.listening ? 'stop' : 'mic')}</button></div>
    ${u.note ? `<p class="small muted">${h(u.note)}</p>` : ''}
    <div class="row between"><button class="btn text" data-act="examples">${ic('lightbulb')}Examples</button><button class="btn filled" data-act="plan" ${UI.busy ? 'disabled' : ''}>${UI.busy ? 'Planning…' : 'Plan'}</button></div></div>`;
  return out + resultHtml();
};
function resultHtml() { const u = UI.ap, ev = curEvent(), T = curTrace();
  if (u.mode === 'event' && ev && ev.buyerId === S().buyerId) return `<div class="result">${eventResult(ev)}</div>`;
  if (u.mode === 'order' && T && T.buyerId === S().buyerId) return `<div class="result">${orderResult(T)}</div>`; return ''; }
function eventResult(ev) {
  const p = ev.plan, b = p.brief; const pol = p.policy; const ap = S().approvals.find(a => a.eventId === ev.eventId && a.status === 'pending');
  const dates = Object.keys(p.deliveries).sort().map(dateL).join(', ');
  const st = ap ? status('Needs approval', 'approve', 'schedule') : ev.status === 'reconciled' ? status('Done · usage recorded', 'ok', 'check_circle') : ev.status === 'ordered' ? status(pol.outcome === 'NOTIFY' ? 'Ordered · notified' : 'Ordered', 'ok', 'check_circle') : ev.status === 'blocked' ? status('Blocked', 'block', 'block') : status('Planned');
  const diets = [...Object.entries(b.diet).filter(([, n]) => n).map(([k, n]) => `${n} ${C.DIET_LABELS[k]}`), ...Object.entries(b.allergies).map(([a, n]) => `${n} ${a === 'nuts' ? 'nut' : C.ALLERGEN_LABELS[a].toLowerCase()} allergy`)].join(', ');
  const d = p.did; const safe = p.safety.every(s => s.safe);
  const reconciled = ev.reconciliation;
  return `<div class="card"><div class="stack" style="gap:4px"><span class="label muted">Event</span><h2 class="headline">${h(b.name)}</h2><p class="body muted">${b.lang === 'fi' ? `${['ma', 'ti', 'ke', 'to', 'pe', 'la', 'su'][C.weekday(b.date)]} ${+b.date.slice(8)}.${+b.date.slice(5, 7)}. · ${ev.guests} hengelle · ${b.style === 'buffet' ? 'noutopöytä' : 'pöytiin tarjoilu'}` : `${dateL(b.date)} · ${ev.guests} guests · ${h(b.style)}${b.services.length > 1 ? ' · ' + h(b.services.slice(1).map(s => s.name.toLowerCase() + ' ' + s.guests).join(', ')) : ''}`}</p></div>
    <dl class="kv body-l"><dt>Total</dt><dd>${money(p.total)}</dd><dt>Per guest</dt><dd>${money(p.total / ev.guests)} <span class="muted small">target ${money0(p.target || 0)}</span></dd><dt>Delivery</dt><dd>${dates}</dd><dt>Status</dt><dd class="big">${st}</dd>${['ordered', 'reconciled'].includes(ev.status) && !ap ? `<dt>Order</dt><dd><button class="btn text" data-act="order" data-trace="${ev.traceId}" style="margin:-10px -12px -10px 0">${ev.orderIds.join(', ')}</button></dd>` : ''}</dl>
    ${ap ? `<button class="btn filled block" data-act="approval" data-id="${ap.approvalId}">Approve and order</button><p class="small muted" style="margin-top:-8px">${h(ap.policy.decisions.filter(x => x.outcome === 'APPROVE').map(x => x.reason)[0] || '')}</p>` : ''}
    <details class="x"><summary class="small muted">${d.searched} products compared · ${d.leftoversNetted} leftovers used · ${d.approvals} approval${d.approvals === 1 ? '' : 's'} needed ${ic('expand_more', 's')}</summary><dl class="kv body" style="padding-bottom:8px">${[['Dishes understood', d.dishes], ['Ingredients calculated', d.ingredients], ['Signed offers checked', `${d.verified} of ${d.offers}`], ['Allergen checks', d.allergenChecks], ['Leftover lots checked', d.leftoversChecked], ['Quantities right-sized from history', d.rightSized], ['Deliveries', d.deliveries], ['Time saved, estimate', Math.round(d.minutesSaved / 6) / 10 + ' h']].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></details></div>
  <div class="list">
    <div class="li static"><span class="lead">${ic('group')}</span><span class="txt"><span class="body-l">Guests</span></span><span class="stepper"><button class="iconbtn" data-act="guests" data-d="-10" aria-label="10 fewer guests">${ic('remove')}</button><output aria-live="polite">${ev.guests}</output><button class="iconbtn" data-act="guests" data-d="10" aria-label="10 more guests">${ic('add')}</button></span></div>
    ${ev.lastDelta ? li({ icon: 'swap_vert', title: `Guests ${ev.lastDelta.from} → ${ev.lastDelta.to}`, sub: `${ev.lastDelta.diff.length} items changed · top-up ${money(ev.lastDelta.deltaTotal)}`, act: 'evdelta' }) : ''}
    ${li({ icon: 'shopping_basket', title: 'Basket', sub: `${p.basket.length} items · ${Object.keys(p.deliveries).length} deliver${Object.keys(p.deliveries).length === 1 ? 'y' : 'ies'}`, act: 'evbasket' })}
    ${li({ icon: 'restaurant', title: 'Menu and diets', sub: `${b.services.reduce((a, s) => a + s.dishes.length, 0)} dishes${diets ? ' · ' + h(diets) : ''}`, act: 'evmenu' })}
    ${li({ icon: 'health_and_safety', title: 'Allergen check', sub: safe ? 'All diet groups covered safely' : 'Needs attention', act: 'evsafety' })}
    ${li({ icon: 'event_note', title: 'Prep timeline', sub: `${p.timeline[0].rel} to ${p.timeline[p.timeline.length - 1].rel}`, act: 'evtimeline' })}
    ${li({ icon: 'gavel', title: 'Rules', sub: pol.ruleIds.length ? `${pol.outcome.charAt(0) + pol.outcome.slice(1).toLowerCase()} · ${pol.ruleIds.join(', ')}` : 'No rule fired', act: 'evrules' })}
    ${['ordered', 'reconciled'].includes(ev.status) ? li({ icon: 'fact_check', title: 'After the event', sub: reconciled ? `${pct(reconciled.metrics.utilisation)} used · ${money(reconciled.metrics.wastedEUR)} wasted` : 'Record what was used', act: reconciled ? 'evreport' : 'evreconcile' }) : ''}
  </div>`;
}
function orderResult(T) {
  const pol = T.policy; const plan = (T.plans || []).find(p => p.planId === T.chosenPlan) || (T.plans || [])[0]; const ap = S().approvals.find(a => a.traceId === T.traceId); const ord = S().orders.find(o => o.traceId === T.traceId);
  const title = (T.lines || []).length === 1 ? `${fq(T.lines[0].qty, T.lines[0].unit)} ${T.lines[0].label}` : (T.lines || []).length ? `${T.lines.length} items` : T.text;
  const st = !pol ? status('Not planned') : ord ? status(STATUS[pol.outcome === 'APPROVE' ? 'AUTO' : pol.outcome][0], 'ok', 'check_circle') : ap && ap.status === 'pending' ? status('Needs approval', 'approve', 'schedule') : ap ? status(ap.status.replace('_', ' '), ap.status === 'rejected' ? 'block' : 'ok') : pol.outcome === 'BLOCK' ? status('Blocked', 'block', 'block') : status('–');
  const excl = sum((T.lines || []).map(l => l.excluded.length)); const offers = Object.keys(T.offers || {}).length;
  return `<div class="card"><div class="stack" style="gap:4px"><span class="label muted">Order</span><h2 class="headline">${h(title)}</h2><p class="body muted">by ${dateL(T.parsed.needBy)} · ${h(S().buyers[T.buyerId].name)}</p></div>
    <dl class="kv body-l"><dt>Total</dt><dd>${plan ? money(ord ? ord.total : plan.total) : '–'}</dd><dt>Delivery</dt><dd>${plan ? [...new Set(plan.lines.map(l => l.deliveryDate))].sort().map(dateL).join(', ') : '–'}</dd><dt>Plan</dt><dd>${plan ? h(plan.label + ' · ' + plan.title) : '–'}</dd><dt>Status</dt><dd class="big">${st}</dd>${ord ? `<dt>Order</dt><dd><button class="btn text" data-act="order" data-trace="${T.traceId}" style="margin:-10px -12px -10px 0">${ord.orderId}</button></dd>` : ''}</dl>
    ${ap && ap.status === 'pending' ? `<button class="btn filled block" data-act="approval" data-id="${ap.approvalId}">Review approval</button>` : ord ? '' : pol && pol.outcome === 'BLOCK' ? `<p class="body t-block">${h(pol.decisions.find(d => d.outcome === 'BLOCK').reason)}</p>` : ''}
    <details class="x"><summary class="small muted">${sum((T.lines || []).map(l => l.searched))} products compared · ${offers} signed offers · ${excl} excluded ${ic('expand_more', 's')}</summary><div class="stack" style="padding-bottom:8px">${T.steps.map(s => `<div class="row" style="align-items:flex-start"><span class="${s.status === 'block' || s.status === 'error' ? 't-block' : s.status === 'warn' || s.status === 'approve' ? 't-approve' : 't-ok'}">${ic(s.status === 'block' ? 'block' : s.status === 'warn' || s.status === 'approve' ? 'schedule' : 'check', 's')}</span><span class="body"><b class="title-s">${h(s.title)}.</b> <span class="muted">${h(s.detail)}</span></span></div>`).join('')}</div></details></div>
  <div class="list">
    ${(T.plans || []).length ? li({ icon: 'alt_route', title: 'Options', sub: `${T.plans.length} plan${T.plans.length > 1 ? 's' : ''} · agent picked ${plan.label}`, act: 'plans' }) : ''}
    ${(T.lines || []).length ? li({ icon: 'compare_arrows', title: 'Products', sub: T.lines.map(l => l.need.needGroupLabel || l.label).slice(0, 2).join(', ') + (T.lines.length > 2 ? ` +${T.lines.length - 2}` : ''), act: 'products' }) : ''}
    ${pol ? li({ icon: 'gavel', title: 'Rules', sub: pol.ruleIds.length ? `${pol.outcome.charAt(0) + pol.outcome.slice(1).toLowerCase()} · ${pol.ruleIds.join(', ')}` : 'No rule fired', act: 'trrules' }) : ''}
    ${T.buyerId === 'BUY-KAARI' ? li({ icon: 'science', title: 'Try an unsafe product', sub: 'Force 240 L almond drink to see the block', act: 'force' }) : ''}
  </div>`;
}
// ---- event sheets
function decisionsHtml(pol) {
  const by = {}; for (const d of pol.decisions) (by[d.ruleId + d.outcome] = by[d.ruleId + d.outcome] || []).push(d);
  const rows = Object.values(by).map(ds => `<div class="stack" style="gap:2px;padding:8px 0"><div class="row"><span class="rule">${ds[0].ruleId}</span><span class="title-s">${h(ds[0].title)}</span><span class="grow"></span>${status(ds[0].outcome.toLowerCase(), ds[0].outcome === 'BLOCK' ? 'block' : ds[0].outcome === 'APPROVE' ? 'approve' : '')}</div><p class="body muted">${h(ds[0].reason)}${ds.length > 1 ? ` (${ds.length - 1} more like this)` : ''}</p></div>`).join('<div class="divider"></div>');
  const sup = (pol.suppressed || []).map(s => `<p class="small muted"><span class="rule">${s.ruleId}</span> not applied: ${h(s.reason)}</p>`).join('');
  return `<p class="body-l">${h(pol.summary)}</p><div>${rows || '<p class="muted">No rule fired.</p>'}</div>${sup}`;
}
function basketSheet(ev) {
  const p = ev.plan;
  const body = Object.entries(p.deliveries).sort().map(([date, ls]) => `<div class="section"><div class="row between label muted"><span>${dateL(date)}</span><span class="num">${money(sum(ls.map(l => l.lineTotal)))}</span></div><div class="list">${ls.map((l, i) => `<details class="x li" style="display:block;padding:0 16px"><summary><span class="txt"><span class="body-l ellipsis">${h(l.name)}</span><span class="body muted">${h(l.roundingNote)}${l.why && l.why.history ? ' · right-sized' : ''}${l.why && l.why.leftovers && l.why.leftovers.length ? ' · leftovers used' : ''}</span></span><span class="trail num">${money(l.lineTotal)}</span></summary>${lineWhy(l)}</details>`).join('')}</div></div>`).join('');
  sheet('Basket', body + dataNote(['plan_line', 'offer', 'leftover_lot']));
}
function lineWhy(l) {
  const w = l.why || {};
  return `<dl class="kv body" style="padding:0 0 12px;grid-template-columns:auto 1fr">${[['For', (w.sources || []).map(s => `${h(s.dish)}: ${s.portions} × ${fq(s.perPortion, s.unit)}`).join('<br>')], ['History', h(w.history || '')], ['Leftovers', h((w.leftovers || []).join(' '))], ['Constraints', [...(l.diet || []).map(d => C.DIET_LABELS[d]), ...(l.excludeAllergens || []).map(a => 'no ' + C.ALLERGEN_LABELS[a].toLowerCase())].join(', ')], ['Choice', h([w.preference, w.tradeoff].filter(Boolean).join(' · '))], ['Price', `${money(l.unitPrice)}/${l.unit}`]].filter(r => r[1]).map(([k, v]) => `<dt>${k}</dt><dd style="text-align:left">${v}</dd>`).join('')}</dl>${l.offerId ? `<button class="btn text" data-act="offer" data-id="${l.offerId}" style="margin:-8px 0 8px -12px">${ic('verified')}Signed offer</button>` : ''}`;
}
function menuSheet(ev) {
  const p = ev.plan;
  sheet('Menu and diets', `<div class="list">${p.menu.filter(m => m.recipe).map(m => li({ title: h(m.dish.name) + (m.dish.said && m.dish.said.toLowerCase() !== m.dish.name.toLowerCase() && /[äöå]|kinkku|laatik|rosolli|puuro|keitto|piirak/i.test(m.dish.said) ? ` <span class="small muted">“${h(m.dish.said)}”</span>` : '') + (m.dish.match === 'nearest' ? ' <span class="small muted">(nearest recipe)</span>' : ''), sub: m.portions.filter(x => x.n).map(x => `${x.n} ${x.recipeId === m.recipe.id ? 'standard' : h(x.name.toLowerCase())}`).join(' · '), trail: `<span class="small">${h(m.serviceName)}</span>` })).join('')}</div>${p.brief.assumptions.length ? `<div class="section"><span class="label">Assumptions</span>${p.brief.assumptions.map(a => `<p class="body muted">${h(a)}</p>`).join('')}</div>` : ''}${p.brief.context ? `<p class="body muted">${h(p.brief.context.text)}</p>` : ''}${dataNote(['event', 'event_dish', 'recipe', 'site_day_context'])}`);
}
function safetySheet(ev) {
  const s = ev.plan.safety;
  sheet('Allergen check', (s.length ? `<div class="list">${s.map(x => li({ icon: x.safe ? 'check_circle' : 'error', title: h(x.group), sub: x.dishes.filter(d => d.variant).map(d => h(d.serves)).join(', ') || 'Standard menu is safe', trail: x.safe ? status('Safe', 'ok') : status('Check', 'block') })).join('')}</div><p class="body muted">Safe-variant ingredients exclude the allergen as a hard filter. Any unsafe product is blocked (R1).</p>` : '<p class="muted">No diets or allergies given.</p>') + dataNote(['event_allergy_count', 'product_allergen']));
}
function timelineSheet(ev) {
  sheet('Prep timeline', ev.plan.timeline.map(d => `<div class="section"><div class="row label muted"><span style="width:56px">${d.rel}</span><span>${dateL(d.date)}</span></div><div class="list plain">${d.items.map(it => `<div class="row body" style="padding:4px 0 4px 56px;align-items:flex-start"><span class="muted">${ic({ delivery: 'local_shipping', prep: 'skillet', service: 'groups', reconcile: 'fact_check' }[it.kind], 's')}</span><span>${h(it.text)}</span></div>`).join('')}</div></div>`).join(''));
}
function reconcileSheet(ev) {
  const pred = F.predictReconciliation(ev.eventId); UI.recDraft = pred;
  sheet(`How did ${ev.name} go?`, `<p class="body muted">Prefilled from the plan. Change only what differs.</p><div class="field" style="max-width:200px"><label for="rcG">Guests who came</label><input id="rcG" class="input" inputmode="numeric" value="${ev.guests - 4}"></div><div class="list">${pred.map((p, i) => `<div style="padding:12px 16px;${i ? 'border-top:1px solid var(--outline-variant)' : ''}"><div class="row between"><span class="body-l ellipsis">${h(p.name)}</span><span class="small muted num">${fq(p.ordered + p.carriedIn, p.unit)}</span></div><div class="grid2" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-top:8px">${[['used', 'Used'], ['kept', 'Kept'], ['wasted', 'Wasted']].map(([k, l]) => `<div class="field"><label for="rc${i}${k}">${l}</label><input id="rc${i}${k}" class="input num" style="min-height:40px;padding:8px 12px" inputmode="decimal" value="${p[k]}" data-in="rec" data-i="${i}" data-k="${k}"></div>`).join('')}</div></div>`).join('')}</div>`, `<button class="btn text" data-act="allused">All used</button><button class="btn filled" data-act="saverec">Save</button>`);
}
function reportSheet(ev) {
  const r = ev.reconciliation, m = r.metrics; const lab = m.perfect ? 'Perfect order' : null;
  sheet(`${ev.name}: usage`, `<div class="grid2"><div class="kpi" style="cursor:default"><span class="small muted">Used</span><span class="v">${pct(m.utilisation)}</span></div><div class="kpi" style="cursor:default"><span class="small muted">Wasted</span><span class="v">${money0(m.wastedEUR)}</span><span class="small muted">${fq(m.wastedKg, 'kg')} · ${fq(m.co2eKg, 'kg')} CO₂e est.</span></div></div>${lab ? `<p class="body t-ok">${ic('check_circle', 's')} ${lab}</p>` : ''}
  <p class="body muted">${r.consumption.filter(c => c.wasted > 0).length} of ${r.consumption.length} items had waste · ${money(m.reusedEUR)} kept for later use.</p><div class="section"><span class="label muted">Per product · used / kept / wasted</span><div class="stack" style="gap:12px">${r.consumption.filter(c => c.ordered + c.carriedIn > 0).sort((a, b) => b.wasted * b.unitPrice - a.wasted * a.unitPrice).slice(0, 10).map(c => { const t = c.ordered + c.carriedIn + c.shortage; const lb0 = F.lineUsageLabel(c); const lb = lb0 === 'under_ordered' || (lb0 === 'over_ordered' && c.wasted > 0) ? lb0 : null; return `<div class="stack" style="gap:4px"><div class="row between body"><span class="ellipsis">${h(c.name)}</span><span class="muted small">${lb ? h({ over_ordered: 'Over-ordered', under_ordered: 'Under-ordered', right_sized: 'Right-sized' }[lb]) : ''}</span></div><div class="bar"><i style="width:${c.used / t * 100}%"></i><i class="s" style="width:${(c.kept + c.redistributed) / t * 100}%"></i><i class="w" style="width:${c.wasted / t * 100}%"></i></div></div>`; }).join('')}</div></div>
  <div class="section"><span class="label muted">Next time</span>${F.eventAdvice(ev).slice(0, 4).map(a => `<p class="body">${h(a)}</p>`).join('')}</div>${dataNote(['consumption', 'outcome_label', 'v_usage_fact'])}`, `<button class="btn tonal" data-act="nextgala">Plan the next gala</button>`);
}
function deltaSheet(ev) {
  const d = ev.lastDelta;
  sheet(`Guests ${d.from} → ${d.to}`, `<div class="list">${d.diff.map(x => li({ title: h(x.name), sub: `${fq(x.was, x.unit)} → ${fq(x.now, x.unit)}`, trail: `<span class="num ${x.d > 0 ? '' : 'muted'}">${x.d > 0 ? '+' : ''}${fq(x.d, x.unit)}</span>` })).join('')}</div><p class="body muted">Top-up ${money(d.deltaTotal)}. Rules are checked on the whole event.</p>`);
}
// ---- order sheets
function plansSheet(T) {
  sheet('Options', T.plans.filter(p => p.policy).map(p => `<div class="card outlined" style="padding:16px;gap:8px"><div class="row between"><span class="title">${p.label} · ${h(p.title)}</span>${p.planId === T.chosenPlan ? '<span class="small t-ok">Agent pick</span>' : ''}</div>${p.lines.map(l => `<div class="row between body"><span class="ellipsis">${fq(l.qty, l.unit)} ${h(l.brand)} · ${dateL(l.deliveryDate)}</span><span class="num">${money(l.lineTotal)}</span></div><p class="small muted">${h(l.roundingNote)}${l.role === 'substitute' ? ' · replaces ' + h(l.substituteFor.name) + ' (' + (l.priceDeltaPct >= 0 ? '+' : '') + l.priceDeltaPct + '%)' : ''}</p>`).join('')}<div class="row between"><span class="body muted">${Math.round(p.coverage.pctByNeedBy)}% by need-by · ${p.policy.ruleIds.join(', ') || 'no rules'}</span><span class="title num">${money(p.total)}</span></div>${status(STATUS[p.policy.outcome][0].replace('Ordered', 'Can order'), p.policy.outcome === 'BLOCK' ? 'block' : p.policy.outcome === 'APPROVE' ? 'approve' : 'ok')}</div>`).join('') + dataNote(['plan', 'plan_line', 'policy_decision']));
}
function productsSheet(T) {
  const vf = T.verifs || {};
  sheet('Products', T.lines.map(l => `<div class="section"><span class="label muted">${h(l.need.needGroupLabel || l.label)} · ${fq(l.qty, l.unit)}</span><div class="list">${l.ranked.slice(0, 4).map(it => { const v = vf[it.offerId]; return `<details class="x li" style="display:block;padding:0 16px"><summary><span class="txt"><span class="body-l ellipsis">${h(it.brand)} · ${h(it.name)}</span><span class="body muted">${money(it.unitPrice)}/${it.unit} · ${it.lateOnly ? 'from ' + dateL(it.earliest) : fq(it.availByNeedBy, it.unit) + ' by need-by'}${it.favourite ? ' · favourite' : ''}</span></span><span class="trail small">${it.tier === 'ALSO' ? '' : it.tier.toLowerCase()}</span></summary>
      <p class="body" style="padding-bottom:8px">${h(it.tradeoff)}</p>
      <div class="stack" style="gap:6px;padding-bottom:8px">${it.breakdown.filter(b => b.weight > 0).map(b => `<div class="row small"><span style="width:150px" class="muted">${h(b.label)}</span><div class="bar grow"><i style="width:${b.value * 100}%"></i></div><span class="num" style="width:44px;text-align:right">${b.contribution.toFixed(2)}</span></div>`).join('')}<p class="small muted">${h(it.rankReason)} · score ${it.score.toFixed(3)}${it.bonuses.map(b => ' · ' + h(b.label)).join('')}${it.reasons.map(r => ' · ' + h(r.text)).join('')}</p></div>
      <div class="row wrap" style="padding-bottom:12px;margin-left:-12px">${it.rank > 1 ? `<button class="btn text" data-act="choose" data-line="${l.lineId}" data-g="${it.gtin}">Choose this</button>` : ''}<button class="btn text" data-act="cmp" data-g="${it.gtin}">Compare</button>${v ? `<button class="btn text" data-act="offer" data-id="${it.offerId}">${v.verified ? 'Signed offer ✓' : 'Offer not verified'}</button>` : ''}<button class="btn text" data-act="fav" data-g="${it.gtin}">${it.favourite ? 'Unfavourite' : 'Favourite'}</button></div></details>`; }).join('')}</div>${l.excluded.length ? `<details class="x"><summary class="body muted">${l.excluded.length} excluded ${ic('expand_more', 's')}</summary><div class="stack">${l.excluded.map(e => `<p class="body"><span>${h(e.name)}</span><br><span class="muted small">${h(e.reason)}</span></p>`).join('')}</div></details>` : ''}</div>`).join('') + dataNote(['offer', 'plan_score', 'candidate_exclusion']));
}
async function offerSheet(o, v) {
  v = v || await C.verifyOffer(o); UI.curOffer = o;
  sheet('Signed offer', `<dl class="kv body"><dt>Product</dt><dd>${h(o.name)}</dd><dt>Price</dt><dd>${money(o.unitPrice)}/${o.unit}, valid to ${o.validUntil.slice(11, 16)} UTC</dd><dt>Available</dt><dd>${fq(o.availability.qtyAvailable, o.unit)} by ${o.availability.byDate ? dateL(o.availability.byDate) : '–'}</dd><dt>GTIN</dt><dd class="mono" style="word-break:normal">${o.gtin}</dd></dl>
  <div class="section"><span class="label muted">${v.verified ? 'All checks passed' : 'Checks failed'} · trust level ${v.trustLevel}</span><div class="list">${v.checks.map(c => li({ icon: c.ok ? 'check_circle' : 'cancel', title: h(c.label), sub: h(c.detail) })).join('')}</div></div>
  <details class="x"><summary class="body muted">Credential (VC 2.0, JWS ES256) ${ic('expand_more', 's')}</summary><p class="mono" style="max-height:200px;overflow:auto">${h(o.proof.jws)}</p></details>`, `<button class="btn text" data-act="tamper-offer">Edit price</button><button class="btn text" data-act="expire-offer">Wait 16 min</button>`);
}
function compareSheet(gs) {
  gs = [...new Set(gs)].slice(-4); if (gs.length < 2) { snack('Pick one more product to compare'); return; } const ps = gs.map(g => BY_GTIN[g]); const nb = C.addDays(C.clock.today(), 3); const sig = C.computeSignals(S().buyerId);
  const rows = [['Price', p => money(C.BE.price(p.gtin)) + '/' + p.unit], ['Pack', p => `${fq(p.packSize, p.unit)} × ${p.unitsPerCase}`], ['Stock by ' + dateL(nb), p => fq(C.BE.availableBy(p.gtin, nb), p.unit)], ['On time', p => Math.round(p.onTimeRate * 100) + '%'], ['Quality', p => p.qualityGrade.toFixed(1)], ['Labels', p => p.certificates.map(c => c.label).join(', ') || '–'], ['Origin', p => p.origin.country], ['Allergens', p => p.allergens.map(a => C.ALLERGEN_LABELS[a]).join(', ') || '–'], ['Your history', p => { const s = C.productSignal(sig, p.gtin); return s ? `${s.orders} orders` : 'new'; }]];
  sheet('Compare', `<div style="overflow-x:auto"><table class="body" style="border-collapse:collapse;width:100%"><thead><tr><th></th>${ps.map(p => `<th class="title-s" style="text-align:left;padding:8px;min-width:140px">${h(p.brand)}<br><span class="small muted">${h(p.name)}</span></th>`).join('')}</tr></thead><tbody>${rows.map(([l, f]) => `<tr style="border-top:1px solid var(--outline-variant)"><td class="muted" style="padding:8px 8px 8px 0;white-space:nowrap">${l}</td>${ps.map(p => `<td style="padding:8px" class="num">${h(f(p))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`, `<button class="btn text" data-act="cmpclear">Clear</button>`);
}

// =============================================================== ORDERS
SCREENS.orders = () => {
  const bid = S().buyerId; const pend = S().approvals.filter(a => a.status === 'pending' && a.buyerId === bid);
  const f = UI.orders.filter;
  let rs = S().processes.filter(r => r.buyerId === bid).slice().reverse();
  rs = rs.filter(r => f === 'all' || (f === 'events' && r.usageContext && r.usageContext.type === 'event') || (f === 'attention' && (r.decision.manualCorrection || F.labelsFor(r).some(x => ['late_delivery', 'bad_substitute', 'over_ordered', 'under_ordered'].includes(x)))) || (f === 'blocked' && r.decision.outcome === 'BLOCK'));
  const shown = UI.orders.more ? rs : rs.slice(0, 25);
  return `${pend.length ? `<div class="section"><span class="label">Waiting for approval</span><div class="list">${pend.map(a => li({ icon: 'schedule', title: h(a.title), sub: `${money(a.total)} · ${h((a.policy.decisions.find(d => d.outcome === 'APPROVE') || {}).title || '')}`, act: 'approval', attrs: `data-id="${a.approvalId}"` })).join('')}</div></div>` : ''}
  <div class="section"><div class="chips" role="group" aria-label="Filter">${[['all', 'All'], ['events', 'Events'], ['attention', 'Needs attention'], ['blocked', 'Blocked']].map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-act="ofilter" data-v="${k}" aria-pressed="${f === k}">${f === k ? ic('check') : ''}${l}</button>`).join('')}</div>
  <div class="list">${shown.map(r => { const o = r.decision.outcome; const ap = r.decision.approverAction; const lbl = o === 'BLOCK' ? status('Blocked', 'block') : ap === 'reject' ? status('Rejected', 'block') : o === 'APPROVE' && !r.orderIds.length ? status('Needs approval', 'approve') : ap ? status('Approved') : status('Ordered'); return li({ title: h(r.request.excerpt), sub: `${dateL(r.createdAt.slice(0, 10))} · ${money0(r.outcome.totalEUR)}`, trail: lbl, act: 'proc', attrs: `data-id="${r.processId}"` }); }).join('') || '<div class="empty">Nothing here</div>'}</div>
  ${!UI.orders.more && rs.length > 25 ? `<button class="btn text" data-act="omore">Show all ${rs.length}</button>` : ''}</div>`;
};
function processSheet(id) {
  const r = S().processes.find(p => p.processId === id); if (!r) return; const T = S().traces[r.traceId]; const evs = S().audit.filter(e => e.traceId === r.traceId);
  const labels = F.labelsFor(r).map(c => ({ perfect_order: 'Perfect order', right_sized: 'Right-sized', over_ordered: 'Over-ordered', under_ordered: 'Under-ordered', good_substitute: 'Good substitute', bad_substitute: 'Bad substitute', price_good: 'Good price', late_delivery: 'Late delivery', autonomous: 'Autonomous', corrected: 'Corrected', top_choice: 'Top choice', exception_free: 'No exceptions' }[c] || c));
  const m = r.consumption ? F.eventMetrics(r.consumption) : null;
  sheet(r.request.excerpt.length > 60 ? r.request.excerpt.slice(0, 58) + '…' : r.request.excerpt, `<dl class="kv body"><dt>Date</dt><dd>${dateL(r.createdAt.slice(0, 10))}</dd><dt>Total</dt><dd>${money(r.outcome.totalEUR)}</dd><dt>Decision</dt><dd>${h(r.decision.outcome || '–')}${r.decision.ruleIds.length ? ' · ' + r.decision.ruleIds.join(', ') : ''}</dd>${r.decision.approver ? `<dt>Approval</dt><dd>${h(r.decision.approver.name)}, ${r.decision.approvalLatencyMin} min</dd>` : ''}<dt>Delivery</dt><dd>${r.feedback ? (r.feedback.onTime ? 'On time' : 'Late') : 'Pending'}</dd>${m ? `<dt>Used</dt><dd>${pct(m.utilisation)} · ${money(m.wastedEUR)} wasted</dd>` : ''}</dl>
  <div class="chips">${labels.map(l => `<span class="tag">${h(l)}</span>`).join('')}</div>
  <div class="section"><span class="label muted">Items</span><div class="list">${r.lines.map(l => li({ title: h(l.name), sub: `${fq(l.qty, l.unit)} · ${money(l.unitPrice)}/${l.unit}`, trail: `<span class="num">${money(l.lineTotal)}</span>` })).join('')}</div></div>
  ${r.outcome.substitutions.length ? `<div class="section"><span class="label muted">Substitutions</span>${r.outcome.substitutions.map(s => `<p class="body">${h(s.toName)} <span class="muted">for ${h(s.fromName)}, ${s.priceDeltaPct >= 0 ? '+' : ''}${s.priceDeltaPct}%${r.feedback && r.feedback.substituteAccepted != null ? (r.feedback.substituteAccepted ? ' · kitchen accepted' : ' · kitchen rejected') : ''}</span></p>`).join('')}</div>` : ''}
  ${r.decision.ruleIds.length ? `<div class="section"><span class="label muted">Rules</span>${r.decision.ruleIds.map(id => `<p class="body"><span class="rule">${id}</span> ${h(C.RULES[id].title)}</p>`).join('')}</div>` : ''}
  ${T && T.steps.length ? `<details class="x"><summary class="title-s">Agent steps ${ic('chevron_right', 'chev')}</summary><div class="stack">${T.steps.map(s => `<p class="body"><b class="title-s">${h(s.title)}.</b> <span class="muted">${h(s.detail)}</span></p>`).join('')}</div></details>` : ''}
  <details class="x"><summary class="title-s">Audit trail · ${evs.length} events ${ic('chevron_right', 'chev')}</summary><div class="stack">${evs.map(e => `<p class="body">${h(C.sentence(e))}<br><span class="small muted">${e.ts.slice(0, 16).replace('T', ' ')} · #${e.seq} · ${e.hash.slice(0, 10)}</span></p>`).join('')}</div></details>
  ${dataNote(['purchase_process', 'order_line', 'policy_decision', 'audit_event'])}`);
}
function approvalSheet(id) {
  const a = S().approvals.find(x => x.approvalId === id); if (!a) return; const b = S().buyers[a.buyerId]; UI.apDraft = { id, lines: {} };
  sheet('Approval', `<dl class="kv body-l"><dt>Request</dt><dd>${h(a.title.length > 48 ? a.title.slice(0, 46) + '…' : a.title)}</dd><dt>Total</dt><dd>${money(a.total)}</dd></dl>
  <div class="stack" style="gap:4px">${a.policy.decisions.filter(d => d.outcome === 'APPROVE').slice(0, 3).map(d => `<p class="body"><span class="rule">${d.ruleId}</span> ${h(d.reason)}</p>`).join('')}</div>
  <div class="section"><span class="label muted">Items</span><div class="list">${a.lines.map(l => `<div class="li static" style="flex-wrap:wrap"><span class="txt" style="min-width:180px"><span class="body-l ellipsis">${h(l.name)}</span><span class="body muted">${h(l.roundingNote)} · ${money(l.lineTotal)}</span></span><div class="seg" role="group" aria-label="Decision"><button class="on" data-act="apl" data-l="${l.lineId}" data-v="approve" aria-label="Approve">${ic('check')}</button><button data-act="apl" data-l="${l.lineId}" data-v="modify" aria-label="Change quantity">${ic('edit')}</button><button data-act="apl" data-l="${l.lineId}" data-v="reject" aria-label="Reject">${ic('close')}</button></div><span class="stepper hide" id="mod-${l.lineId}"><button class="iconbtn" data-act="apc" data-l="${l.lineId}" data-d="-1" aria-label="Fewer">${ic('remove')}</button><output id="cs-${l.lineId}">${l.cases}</output><button class="iconbtn" data-act="apc" data-l="${l.lineId}" data-d="1" aria-label="More">${ic('add')}</button></span></div>`).join('')}</div></div>
  <div class="grid2"><div class="field"><label for="apWho">Approver</label><select id="apWho" class="input">${b.approvers.map(x => `<option value="${x.id}">${h(x.name)}</option>`).join('')}</select></div><div class="field"><label for="apWhy">Note</label><input id="apWhy" class="input" placeholder="Optional"></div></div>`, `<button class="btn text" data-act="apsubmit" data-all="reject">Reject</button><button class="btn filled" data-act="apsubmit">Approve</button>`);
}

// =============================================================== INSIGHTS
const METRIC_KEY = { autonomous_rate: 'autonomousRate', manual_correction_rate: 'manualCorrectionRate', top_choice_rate: 'topChoiceRate', utilisation: 'utilisation', waste_eur: 'wasteEUR', waste_rate: 'wasteRate', coverage: 'coverage', rounding_overage: 'roundingOverage', need_by_hit_rate: 'needByHitRate', fill_rate: 'fillRate', approval_latency: 'approvalP50', substitute_acceptance: 'substitutionAcceptance', spend_eur: 'spend', exceptions_per_process: 'exceptionsPerProcess' };
const fmtM = (u, v) => v == null ? '–' : u === '%' ? pct(v) : u === 'EUR' ? money0(v) : u === 'min' ? Math.round(v) + ' min' : u === 'count' ? v.toFixed(2) : fq(v);
function metricTile(code, k, all) {
  const md = F.METRIC_DEFS[code]; const key = METRIC_KEY[code]; const src = all ? k.all : k.current; const cur = code === 'waste_eur' ? F.wasteInsights(S().buyerId).totals.wastedEUR : src[key]; const prev = k.previous[key];
  const d = !all && cur != null && prev != null && code !== 'waste_eur' ? cur - prev : null; const better = md.better_when === 'higher' ? 1 : md.better_when === 'lower' ? -1 : 0;
  return `<button class="kpi" data-act="metric" data-v="${code}"><span class="small muted">${h(md.name)}</span><span class="v">${fmtM(md.unit, cur)}</span><span class="small ${d && better && d * better < 0 ? 't-approve' : 'muted'}">${code === 'waste_eur' ? 'Last 12 weeks' : all ? '12 weeks' : '4-week avg' + (d == null ? '' : ' · ' + (d >= 0 ? '+' : '−') + fmtM(md.unit === '%' ? '%' : md.unit, Math.abs(d)).replace('%', md.unit === '%' ? ' pts' : ''))}</span></button>`;
}
SCREENS.insights = () => {
  const k = F.kpis(S().buyerId); const recs = F.recommendations(S().buyerId).filter(r => r.action.type !== 'info').slice(0, 5);
  return `<div class="grid4">${['autonomous_rate', 'manual_correction_rate', 'waste_eur', 'need_by_hit_rate'].map(c => metricTile(c, k)).join('')}</div>
  <div class="card"><div class="row between"><span class="title">Autonomous rate, weekly</span><span class="small muted">to ${dateL(C.clock.today()).slice(4)}</span></div>${chart(k.series.map(s => s.autonomousRate == null ? null : s.autonomousRate * 100), { min: 0, max: 100, fmt: v => Math.round(v) + '%', labels: k.series.map((s, i, a) => i === a.length - 1 ? 'This week' : dateL(s.week).slice(4)), label: 'Autonomous rate per week' })}</div>
  <div class="section"><span class="label">Recommendations</span><div class="list">${recs.map(r => `<div class="li"><button class="txt" data-act="rec" data-id="${r.id}" style="border:0;background:none;text-align:left;cursor:pointer;padding:8px 0;color:inherit"><span class="body-l">${h(r.title)}</span><span class="body muted ellipsis">${h(r.impact)}</span></button><span class="trail">${r.status === 'applied' ? '<span class="small muted">Applied</span>' : `<button class="btn text" data-act="applyrec" data-id="${r.id}">Apply</button>`}</span></div>`).join('') || '<div class="empty">No recommendations right now</div>'}</div></div>
  <button class="btn text" data-act="allmetrics" style="align-self:flex-start">See all metrics</button>`;
};
function allMetricsSheet() {
  const k = F.kpis(S().buyerId); const w = F.wasteInsights(S().buyerId);
  const val = c => { const md = F.METRIC_DEFS[c]; const v = c === 'waste_eur' ? w.totals.wastedEUR : k.all[METRIC_KEY[c]]; return c === 'rounding_overage' ? fq(v || 0) + ' units' : fmtM(md.unit, v); };
  sheet('All metrics', `<p class="body muted">Last 12 weeks. Tap a metric for its definition.</p><div class="list">${Object.keys(F.METRIC_DEFS).map(c => li({ title: h(F.METRIC_DEFS[c].name), sub: h(F.METRIC_DEFS[c].better_when + ' is better'), trail: `<span class="body-l num" style="color:var(--on-surface)">${val(c)}</span>`, act: 'metric', attrs: `data-v="${c}"` })).join('')}</div>
  <div class="section"><span class="label muted">Most wasted</span><div class="list">${w.topWasted.slice(0, 5).map(p => li({ title: h(p.name), sub: `${fq(p.wasted, p.unit)} over ${p.n} events`, trail: `<span class="num">${money0(p.wastedEUR)}</span>` })).join('')}</div></div>
  <div class="section"><span class="label muted">Leftovers in stock</span><div class="list">${w.leftovers.map(l => li({ title: `${fq(l.qty, l.unit)} ${h(l.name)}`, sub: `Use by ${dateL(l.bestBefore)} · ${h(l.sourceLabel)}` })).join('') || '<div class="empty">None</div>'}</div></div>
  ${dataNote(['metric_definition', 'v_process_fact', 'v_usage_fact', 'leftover_lot'])}`);
}

// =============================================================== SETTINGS
SCREENS.settings = () => {
  const b = buyer(); const m = C.mandateOf(b.id); const pf = S().profiles[b.id]; const v = UI.audit.verify; const ag = S().agents[b.agents[0].id];
  const theme = document.documentElement.dataset.theme || 'system';
  return `<div class="list">
    ${li({ icon: 'tune', title: 'Preferences', sub: `${C.PRESET_LABELS[pf.org.preset] || 'Custom'} · ${pf.favourites.length} favourites`, act: 'nav', attrs: 'data-v="preferences"' })}
    ${li({ icon: 'verified_user', title: 'Mandate', sub: `${money0(m.limits.perOrderEUR)} per order · version ${m.version}, signed by ${h(m.issuedBy.name)}`, act: 'nav', attrs: 'data-v="mandate"' })}
    ${li({ icon: 'no_food', title: 'Allergens and diets', sub: m.hardExclusions.allergens.map(a => C.ALLERGEN_LABELS[a]).join(', ') || 'No exclusions', act: 'nav', attrs: 'data-v="allergens"' })}
    ${li({ icon: 'smart_toy', title: 'Agents', sub: ag.killed ? 'Suspended' : 'Active', act: 'nav', attrs: 'data-v="agents"' })}
  </div>
  <div class="list">
    ${li({ icon: 'receipt_long', title: 'Audit log', sub: v ? (v.ok ? `Intact · ${v.checked} events` : `Broken at event ${v.brokenAt}`) : 'Not checked', act: 'nav', attrs: 'data-v="audit"' })}
    ${li({ icon: 'storefront', title: 'Valio Aimo view', sub: 'Agent traffic and guardrails, all customers', act: 'nav', attrs: 'data-v="ops"' })}
    ${li({ icon: 'account_tree', title: 'How it works', sub: 'Architecture, trust, data model', act: 'nav', attrs: 'data-v="how"' })}
    ${li({ icon: 'play_circle', title: 'Demo scenarios', sub: 'Run S0 to S8', act: 'nav', attrs: 'data-v="demo"' })}
  </div>
  <div class="row between" style="padding:0 4px"><span class="body-l">Theme</span><div class="seg" role="group" aria-label="Theme">${[['system', 'System'], ['light', 'Light'], ['dark', 'Dark']].map(([k, l]) => `<button class="${theme === k ? 'on' : ''}" data-act="theme" data-v="${k}">${l}</button>`).join('')}</div></div>
  <p class="small muted" style="padding:0 4px">Junction 2026 prototype for the Valio Aimo challenge. Synthetic data.</p>`;
};
// ---- preferences
const pd = () => { if (!UI.prefs.d || UI.prefs.b !== S().buyerId) { UI.prefs.d = clone(S().profiles[S().buyerId]); UI.prefs.b = S().buyerId; } return UI.prefs.d; };
function preview() {
  const d = pd(); const b = buyer(); const req = b.id === 'BUY-KAARI' ? { lineId: 'P', text: 'oat drink', qty: 240, unit: 'L' } : { lineId: 'P', text: 'lactose-free milk', qty: 1000, unit: 'L' };
  const l = C.planLine({ buyer: b, mandate: C.mandateOf(b.id), profile: d, signals: C.computeSignals(b.id), leftovers: [] }, req, C.addDays(C.clock.today(), 7), null, null);
  const mx = Math.max(...l.ranked.map(r => r.score), 0.01);
  return `<span class="label muted">Ranking for ${fq(req.qty, req.unit)} ${req.text}, next week</span><div class="list">${l.ranked.slice(0, 3).map(it => `<div class="li static"><span class="txt"><span class="body-l ellipsis">${it.rank}. ${h(it.brand)}</span><div class="bar" style="margin-top:6px"><i style="width:${it.score / mx * 100}%"></i></div></span><span class="trail small num">${it.score.toFixed(3)}</span></div>`).join('')}</div>`;
}
const QF = [['origin', 'Finnish', { field: 'origin', values: ['FI'], mode: 'preferred' }], ['organic', 'EU Organic', { field: 'certificate', values: ['EU Organic'], mode: 'preferred' }], ['hs', 'Hyvää Suomesta', { field: 'certificate', values: ['Hyvää Suomesta'], mode: 'preferred' }], ['quality', 'Quality 4.4+', { field: 'minQuality', value: 4.4, mode: 'preferred' }]];
const hasF = (d, f) => d.org.filters.some(x => JSON.stringify(x) === JSON.stringify(f));
SCREENS.preferences = () => {
  const d = pd(); const w = C.effectiveProfile(d, null).weights;
  const groups = Object.entries(d.needGroups);
  return `<div class="section"><span class="label">Rank by</span><div class="scroll-x"><div class="seg" role="group" aria-label="Preset">${Object.keys(C.PRESETS).map(p => `<button class="${d.org.preset === p ? 'on' : ''}" data-act="preset" data-v="${p}">${d.org.preset === p ? ic('check') : ''}${C.PRESET_LABELS[p]}</button>`).join('')}</div></div></div>
  <div class="list">${C.CRITERIA.map(c => `<div class="li static"><label for="w-${c}" class="body-l" style="width:180px;flex:none">${C.CRITERIA_LABELS[c]}</label><input id="w-${c}" type="range" min="0" max="60" value="${Math.round(w[c] * 100)}" data-in="w" data-c="${c}"><span class="num body" id="wv-${c}" style="width:40px;text-align:right">${Math.round(w[c] * 100)}%</span></div>`).join('')}</div>
  <div class="section" id="pv">${preview()}</div>
  <div class="section"><span class="label">Prefer</span><div class="chips">${QF.map(([k, l, f]) => `<button class="chip ${hasF(d, f) ? 'on' : ''}" data-act="qf" data-v="${k}" aria-pressed="${hasF(d, f)}">${hasF(d, f) ? ic('check') : ''}${l}</button>`).join('')}</div></div>
  <div class="section"><span class="label">Favourites</span><div class="list">${d.favourites.map(g => li({ icon: 'star', title: h(BY_GTIN[g].brand), sub: h(BY_GTIN[g].name), trail: `<button class="iconbtn" data-act="unfav" data-g="${g}" aria-label="Remove">${ic('close')}</button>` })).join('') || '<div class="empty" style="padding:24px">Add favourites from an order’s product list</div>'}</div></div>
  <div class="section"><span class="label">Always choose first</span><div class="list">${groups.map(([g, np]) => li({ icon: 'push_pin', title: h(BY_GTIN[np.pinned].brand + ' · ' + BY_GTIN[np.pinned].name), sub: h(C.needGroupLabel(g)), trail: `<button class="iconbtn" data-act="unpin" data-g="${g}" aria-label="Remove">${ic('close')}</button>` })).join('')}<div class="li static"><select class="input" data-in="pin" aria-label="Pin a product"><option value="">Pin a product…</option>${C.P.filter(p => C.P.filter(q => C.needGroupId(q) === C.needGroupId(p)).length > 1).map(p => `<option value="${p.gtin}">${h(p.brand)} · ${h(p.name)}</option>`).join('')}</select></div></div></div>
  <button class="btn filled block" data-act="savepref">Save preferences</button>`;
};
// ---- mandate & allergens
const md = () => { if (!UI.md || UI.mdb !== S().buyerId) { UI.md = clone(C.mandateOf(S().buyerId)); UI.mdb = S().buyerId; } return UI.md; };
SCREENS.mandate = () => {
  const d = md(); const cur = S().mandates[S().buyerId];
  return `<div class="section"><span class="label">Spending limits</span><div class="grid2">${[['perOrderEUR', 'Per order'], ['perMonthEUR', 'Per month'], ['perEventEUR', 'Per event'], ['perGuestEUR', 'Per guest target']].map(([k, l]) => `<div class="field"><label for="l-${k}">${l} (€)</label><input id="l-${k}" class="input num" inputmode="decimal" value="${d.limits[k] || ''}" data-in="lim" data-k="${k}"></div>`).join('')}</div></div>
  <div class="section"><span class="label">Substitutes</span><div class="list"><div class="li static"><label for="mdl" class="body-l" style="width:180px;flex:none">Max price difference</label><input id="mdl" type="range" min="0" max="15" value="${d.substitution.maxPriceDeltaPct}" data-in="mdl"><span class="num" id="mdlv" style="width:40px;text-align:right">${d.substitution.maxPriceDeltaPct}%</span></div>
  ${[['allowBrandSwitch', 'Allow other brands'], ['allowPackSizeChange', 'Allow other pack sizes'], ['sameCategoryOnly', 'Same category only']].map(([k, l]) => `<label class="li static"><span class="txt body-l">${l}</span><span class="switch"><input type="checkbox" ${d.substitution[k] ? 'checked' : ''} data-in="msw" data-k="${k}"></span></label>`).join('')}
  <div class="li static" style="flex-wrap:wrap"><span class="txt"><span class="body-l">Order without notifying</span><span class="body muted">Swaps within limits in these categories</span></span><span class="chips">${['dairy', 'produce', 'bakery', 'dry_goods'].map(c => `<button class="chip ${(d.substitution.silentCategories || []).includes(c) ? 'on' : ''}" data-act="msil" data-v="${c}">${c.replace('_', ' ')}</button>`).join('')}</span></div></div></div>
  <button class="btn filled block" data-act="sign">Sign as ${h(buyer().admin.name)}</button>
  <details class="x"><summary class="body muted">Version ${cur.current.mandate.version} · ${cur.versions.length} earlier ${ic('expand_more', 's')}</summary><p class="mono">${h(cur.current.jws.slice(0, 220))}…</p></details>`;
};
SCREENS.allergens = () => {
  const d = md();
  return `<div class="section"><span class="label">Never order products that contain</span><div class="chips">${C.ALLERGENS.map(a => { const on = d.hardExclusions.allergens.includes(a); return `<button class="chip ${on ? 'on' : ''}" data-act="mal" data-v="${a}" aria-pressed="${on}">${on ? ic('check') : ''}${C.ALLERGEN_LABELS[a]}</button>`; }).join('')}</div></div>
  <div class="section"><span class="label">Every product must be</span><div class="chips">${['milk_free', 'nut_free', 'lactose_free', 'gluten_free', 'egg_free', 'vegan'].map(x => { const on = d.hardExclusions.diet.includes(x); return `<button class="chip ${on ? 'on' : ''}" data-act="mdi" data-v="${x}" aria-pressed="${on}">${on ? ic('check') : ''}${C.DIET_LABELS[x].charAt(0).toUpperCase() + C.DIET_LABELS[x].slice(1)}</button>`; }).join('')}</div></div>
  <p class="body muted">These apply to every order and event. A product that breaks them is blocked.</p>
  <button class="btn filled block" data-act="sign">Sign as ${h(buyer().admin.name)}</button>`;
};
SCREENS.agents = () => `<div class="list">${Object.values(S().agents).map(a => `<label class="li static"><span class="txt"><span class="body-l">${h(a.name)}</span><span class="body muted">${h(S().buyers[a.buyerId].name)} · ${a.killed ? 'suspended' : 'active'}</span></span><span class="switch"><input type="checkbox" ${a.killed ? '' : 'checked'} data-in="kill" data-id="${a.id}" aria-label="${h(a.name)} active"></span></label>`).join('')}</div><p class="body muted">Switching an agent off stops all its requests (rule V3).</p>`;
SCREENS.ops = () => {
  const o = F.opsSummary(); const t = sum(Object.values(o.mix)) || 1;
  return `<div class="grid4">${[['Requests, 12 weeks', o.total], ['Autonomous', pct((o.mix.AUTO + o.mix.NOTIFY) / t)], ['Approval time, median', Math.round(o.approvalP50 || 0) + ' min'], ['Blocked', o.mix.BLOCK]].map(([l, v]) => `<div class="kpi" style="cursor:default"><span class="small muted">${l}</span><span class="v">${v}</span></div>`).join('')}</div>
  <div class="card"><span class="title">Decisions</span>${['AUTO', 'NOTIFY', 'APPROVE', 'BLOCK'].map(k => `<div class="row body"><span style="width:80px">${k.charAt(0) + k.slice(1).toLowerCase()}</span><div class="bar grow"><i style="width:${o.mix[k] / t * 100}%"></i></div><span class="num" style="width:40px;text-align:right">${o.mix[k]}</span></div>`).join('')}</div>
  <div class="section"><span class="label">Stock-outs causing substitutes</span><div class="list">${o.stockoutSubs.map(s => li({ title: h(s.name), sub: `${s.buyers} customer${s.buyers > 1 ? 's' : ''}`, trail: `<span class="num">${s.n}</span>` })).join('')}</div></div>
  <div class="section"><span class="label">Pack sizes behind waste</span><div class="list">${o.packOverage.map(p => li({ title: h(p.name), sub: `case ${fq(p.caseQty, p.unit)}`, trail: `<span class="num">${fq(p.wasted, p.unit)} wasted</span>` })).join('')}</div></div>
  ${o.blocked.length ? `<div class="section"><span class="label">Blocked requests</span><div class="list">${o.blocked.map(b => li({ title: h(b.text), sub: `${h(b.buyer)} · ${b.rules.join(', ')}` })).join('')}</div></div>` : ''}`;
};
SCREENS.audit = () => {
  const v = UI.audit.verify; let evs = S().audit.filter(e => UI.audit.view === 'ops' || e.buyerId === S().buyerId || !e.buyerId).slice(-50).reverse();
  return `<div class="card"><div class="row between"><span class="body-l ${v && !v.ok ? 't-block' : ''}">${v ? (v.ok ? `Chain intact · ${v.checked} events` : `Broken at event ${v.brokenAt}`) : 'Not checked'}</span><button class="btn tonal" data-act="verify">Verify</button></div>${v && !v.ok ? `<p class="body muted">${h(v.detail)}</p>` : ''}<div class="row"><button class="btn text" data-act="${S().tampered ? 'untamper' : 'tamper'}" style="margin-left:-12px">${S().tampered ? 'Restore the edited event' : 'Edit an event (tamper test)'}</button></div></div>
  <div class="seg" role="group" aria-label="View"><button class="${UI.audit.view === 'buyer' ? 'on' : ''}" data-act="aview" data-v="buyer">Buyer</button><button class="${UI.audit.view === 'ops' ? 'on' : ''}" data-act="aview" data-v="ops">Valio Aimo</button></div>
  <div class="list">${evs.map(e => `<div class="li static" style="align-items:flex-start;${v && !v.ok && v.brokenAt === e.seq ? 'background:var(--surface-3)' : ''}"><span class="txt"><span class="body">${h(C.sentence(e))}</span><span class="small muted">${e.ts.slice(5, 16).replace('T', ' ')} · #${e.seq} · ${e.hash.slice(0, 8)}${(e.ruleIds || []).length ? ' · ' + e.ruleIds.join(', ') : ''}${UI.audit.view === 'ops' && e.buyerId ? ' · ' + e.buyerId : ''}</span></span>${v && !v.ok && v.brokenAt === e.seq ? status('Edited', 'block') : ''}</div>`).join('')}</div>`;
};
// ---- how it works
const NODES = {
  buyer: [['chef', 'Chef', 'Says what is planned, by text or voice.', 'Web Speech API', ['event']], ['agent', 'Purchasing agent', 'Turns needs into requests and picks the least restricted plan. It proposes; it never decides.', 'MCP or REST client', ['purchase_process']], ['wallet', 'Mandate', 'A named person signs limits, exclusions and substitution rules.', 'AP2 Intent Mandate, JWS ES256', ['mandate']], ['approver', 'Approver', 'Gets one approval per request and can change any line.', 'Human oversight (EU AI Act Art. 14)', ['approval', 'manual_change']]],
  gateway: [['discovery', 'Discovery', 'Publishes capabilities, a signed agent card and public keys.', '/.well-known/ucp, agent card, JWKS', ['agent']], ['facade', 'REST and MCP', 'One set of handlers behind both interfaces.', 'OpenAPI 3.1, MCP', ['purchase_process']], ['autopilot', 'Event Autopilot', 'Brief, recipes, quantities, leftovers, sourcing, timing, one decision.', 'Recipe data, learned use per guest', ['event', 'recipe', 'sig_per_guest_consumption']], ['planner', 'Planner', 'Filters with reasons, ranks with your preferences, builds up to three plans.', 'GS1 GTIN', ['plan', 'plan_score', 'candidate_exclusion']], ['signer', 'Offer signer', 'Signs price and stock; price holds 15 minutes.', 'W3C VC 2.0, JWS ES256', ['offer']], ['policy', 'Policy engine', 'Fixed rules decide: auto, notify, approve or block.', 'rules.yaml, later OPA/Rego', ['policy_decision', 'decision_rule_hit']], ['ledger', 'Audit log', 'Every step, hash-chained and readable.', 'SHA-256 chain', ['audit_event']], ['learning', 'Learning', 'Outcomes become signals and recommendations with evidence.', '3NF model and views', ['line_feedback', 'consumption', 'recommendation']]],
  valio: [['pim', 'Catalog', 'Products, allergens, certificates.', 'GS1 GDSN, Digital Link', ['product']], ['stock', 'Price and stock', 'Customer prices and stock by date.', 'Adapter', ['offer']], ['orders', 'Orders and delivery', 'Takes confirmed orders, reports deliveries.', 'EPCIS (later)', ['purchase_order', 'delivery_line']]],
};
SCREENS.how = () => {
  const t = UI.how.tab;
  let out = `<div class="scroll-x"><div class="seg" role="group" aria-label="Section">${[['arch', 'Architecture'], ['trust', 'Trust'], ['data', 'Data model'], ['std', 'Standards']].map(([k, l]) => `<button class="${t === k ? 'on' : ''}" data-act="htab" data-v="${k}">${l}</button>`).join('')}</div></div>`;
  if (t === 'arch') { const all = Object.values(NODES).flat(); const n = all.find(x => x[0] === UI.how.node) || all[0];
    out += `<div class="lanes">${[['buyer', 'Buyer'], ['gateway', 'Gateway'], ['valio', 'Valio Aimo']].map(([k, l]) => `<div class="lane"><span class="label muted" style="padding:4px 8px">${l}</span>${NODES[k].map(x => `<button class="li ${x[0] === n[0] ? 'on' : ''}" data-act="node" data-v="${x[0]}"><span class="body">${x[1]}</span></button>`).join('')}</div>`).join('')}</div>
    <div class="card"><span class="title">${n[1]}</span><p class="body-l">${n[2]}</p><dl class="kv body"><dt>Standard</dt><dd>${h(n[3])}</dd><dt>Data</dt><dd>${n[4].map(x => `<button class="ent" data-act="dm" data-v="${x}">${x}</button>`).join(' ')}</dd></dl></div>`; }
  if (t === 'trust') out += `<div class="list">${C.CHECKS.map(([, l], i) => li({ icon: ['key', 'timer', 'inventory', 'link', 'block', 'refresh'][i], title: `${i + 1}. ${l}`, sub: ['Checked against the gateway public key.', 'Prices are fixed for 15 minutes.', 'Stock read within 5 minutes.', 'Shown values equal the signed values.', 'Not on the revocation list.', 'Checkout re-reads price and stock and refuses to charge a different price.'][i] })).join('')}</div><p class="body muted">The agent may act only on offers that pass these checks. Catalog data alone is for browsing.</p>`;
  if (t === 'data') out += dataModel(UI.how.hl);
  if (t === 'std') out += `<div class="list">${[['OpenAPI 3.1 and MCP', 'Same handlers, two interfaces'], ['A2A agent card', 'Discovery and verification'], ['AP2 mandates', 'Signed consent and signed order confirmation'], ['W3C VC 2.0, JWS ES256', 'Signed offers'], ['GS1 GTIN, Digital Link', 'Product identity'], ['EU 1169/2011 Annex II', 'The 14 allergens'], ['EU AI Act Art. 12 and 14', 'Logging and human oversight']].map(([a, b]) => li({ title: a, sub: b })).join('')}</div>`;
  return out;
};
function dataModel(hl) {
  const sch = C.D.schema; const all = [...sch.tables, ...sch.views]; const set = new Set(hl || []); const by = {}; for (const x of all) (by[x.labels.domain || 'REF'] = by[x.labels.domain || 'REF'] || []).push(x);
  const NAMES = { REF: 'Reference', CFG: 'Configuration', TXN: 'Transactions', OBS: 'Outcomes', AUD: 'Audit', INS: 'Insight', DER: 'Derived' }; const sel = all.find(x => x.name === UI.how.ent);
  return `<p class="body muted">${sch.tables.length} tables and ${sch.views.length} views in third normal form, in three layers: raw events (90 days), refined tables, insight views.</p>
  ${sel ? `<div class="card"><div class="row between"><span class="title mono" style="font-size:16px">${sel.name}</span><span class="small muted">${h(sel.labels.domain || '')} · ${h(sel.labels.feeds || '')}</span></div>${sel.labels.grain ? `<p class="body muted">One row per ${h(sel.labels.grain.replace(/^one row per /, ''))}</p>` : ''}<dl class="kv small">${sel.columns.map(c => `<dt class="mono">${c.name}</dt><dd style="text-align:left">${h(c.type)}${c.ref ? ' → ' + c.ref : ''}${c.note ? ' · ' + h(c.note) : ''}</dd>`).join('') || '<dt>View</dt><dd style="text-align:left">Derived from base tables</dd>'}</dl></div>` : ''}
  ${Object.keys(NAMES).filter(k => by[k]).map(k => `<div class="section"><span class="label muted">${NAMES[k]} · ${by[k].length}</span><div class="chips">${by[k].map(x => `<button class="ent ${UI.how.ent === x.name ? 'on' : set.has(x.name) ? 'hl' : ''}" data-act="dm" data-v="${x.name}">${x.name}</button>`).join('')}</div></div>`).join('')}
  <details class="x"><summary class="body muted">Data layers diagram ${ic('expand_more', 's')}</summary><div class="svgwrap"><div style="min-width:1200px">${C.D.layersSvg || ''}</div></div></details>`;
}
// ---- demo
const DEMO = [
  ['S0', 'Gala for 180 guests', 'Starts the demo fresh and plans the gala', async () => { go('autopilot'); await busy(async () => { await F.boot(); S().buyerId = 'BUY-POHJOLA'; await F.runScene('S3'); await F.runScene('S4'); await F.runScene('S2'); S().buyerId = 'BUY-POHJOLA'; }); await planText(F.GALA); }],
  ['S0+', 'Guests change to 200', 'Re-scaled basket, one approval', async () => { go('autopilot'); await rescale(200); }],
  ['S1', 'Milk, enough stock', 'Ordered automatically', () => scene('S1')],
  ['S2', 'Milk, partial stock', 'Split order, alternatives shown', () => scene('S2')],
  ['S3', 'Last-minute event order', 'Over the order limit, one approval', () => scene('S3')],
  ['S4', 'Hospital, milk- and nut-free', 'Safe substitute, unsafe one blocked', () => scene('S4')],
  ['S5', 'Standing order up 22%', 'Paused for approval', () => scene('S5')],
  ['X1', 'Offer expires, price changes', 'Re-quoted, never charged differently', () => scene('X1')],
  ['T', 'Tamper with the audit log', 'Verification finds the edit', async () => { C.tamper(); UI.audit.verify = await C.auditVerify(); go('audit'); }],
  ['S6', 'Apply a recommendation', 'Milk swaps now order without notifying', async () => { S().buyerId = 'BUY-POHJOLA'; await F.applyRecommendation('BUY-POHJOLA', 'silent-dairy', 'Laura Virtanen'); UI.md = null; await scene('S2'); }],
  ['S7', 'Change preferences', 'Domestic first, Maitokaari pinned', async () => { S().buyerId = 'BUY-POHJOLA'; const pf = S().profiles['BUY-POHJOLA']; pf.org.preset = 'domestic_sustainable'; pf.org.weights = { ...C.PRESETS.domestic_sustainable }; const B = BY_KEY.milk_lf_semi_maitokaari; pf.needGroups[C.needGroupId(B)] = { pinned: B.gtin, fallback: [] }; pf.version++; UI.prefs.d = null; await C.audit({ actor: 'human:Laura Virtanen', action: 'preferences_updated', buyerId: 'BUY-POHJOLA', reason: `v${pf.version}: domestic first, ${B.name} pinned` }); await scene('S1'); }],
  ['S8', 'Record usage, plan next gala', 'Report, then right-sized quantities', async () => { S().buyerId = 'BUY-POHJOLA'; UI.ap.mode = 'event'; const pend = S().approvals.find(a => a.eventId === UI.ap.eventId && a.status === 'pending'); if (pend) await F.decideApproval(pend.approvalId, { approver: buyer().approvers[0], all: 'approve', reason: 'Approved for the demo' }); const ev = curEvent(); if (ev && ev.status === 'ordered' && !ev.reconciliation) { const pred = F.predictReconciliation(ev.eventId); for (const p of pred) if (/cream|roll/i.test(p.name)) { const w = r2(p.used * .12); p.used = r2(p.used - w); p.wasted = r2(p.wasted + w); } await F.reconcileEvent(ev.eventId, pred, ev.guests - 4, 'Jari Lehtonen'); } go('autopilot'); render(); const e2 = curEvent(); if (e2 && e2.reconciliation) reportSheet(e2); }],
  ['OPS', 'Valio Aimo view', 'Decisions, blocks, waste signals', () => go('ops')],
];
SCREENS.demo = () => `<div class="list">${DEMO.map((d, i) => `<div class="li"><span class="lead body muted" style="width:32px">${d[0]}</span><span class="txt"><span class="body-l">${d[1]}</span><span class="body muted">${d[2]}</span></span><span class="trail"><button class="btn text" data-act="demo" data-i="${i}">Run</button></span></div>`).join('')}</div><button class="btn outlined" data-act="reset">Reset demo</button>`;

// =============================================================== flows
async function busy(fn) { UI.busy = true; render(); try { return await fn(); } catch (e) { console.error(e); snack('Something went wrong. ' + e.message); } finally { UI.busy = false; render(); } }
const isOrderText = t => { const p = F.parseRequest(t); return p.lines.some(l => l.unit === 'L' || l.unit === 'kg'); };
async function planText(text) {
  UI.ap.text = text; UI.ap.expanded = false; const m = text.match(/^\s*(?:now|nyt)\s+(\d+)\s+(?:guests|hengelle|vierasta)/i);
  if (m && curEvent()) return rescale(+m[1]);
  if (isOrderText(text)) { await busy(async () => { const T = await F.runAgent(text, { buyerId: S().buyerId }); UI.ap.traceId = T.traceId; UI.ap.mode = 'order'; }); return; }
  await busy(async () => { const b = F.parseBrief(text); const r = await F.planEvent(b, { buyerId: S().buyerId }); UI.ap.eventId = r.eventId; UI.ap.mode = 'event'; await F.orderEvent(r.eventId); });
}
async function scene(id) { const sc = F.SCENES[id]; S().buyerId = sc.buyer; UI.ap.text = sc.text; go('autopilot'); await busy(async () => { const T = await F.runScene(id); UI.ap.traceId = T.traceId; UI.ap.mode = 'order'; }); }
async function rescale(n) { const ev = curEvent(); if (!ev) return; UI.ap.mode = 'event'; await busy(async () => { const r = await F.rescaleEvent(ev.eventId, n); const res = await F.orderEvent(ev.eventId, { delta: r.delta.delta }); snack(res.ap ? `${n} guests. Approval needed.` : res.order ? `${n} guests. Top-up ordered.` : `${n} guests.`); }); }

// =============================================================== actions
const tog = (a, v) => { const i = a.indexOf(v); i >= 0 ? a.splice(i, 1) : a.push(v); };
const ACT = {
  scrim(el, ev) { if (ev.target === el) closeSheet(); }, close: closeSheet,
  back() { history.length > 1 ? history.back() : go('settings'); }, nav(el) { go(el.dataset.v); },
  org(el) { const r = el.getBoundingClientRect(); const m = document.createElement('div'); m.className = 'menu'; m.setAttribute('role', 'menu'); m.style.top = r.bottom + 4 + 'px'; m.style.right = Math.max(8, innerWidth - r.right) + 'px'; m.innerHTML = Object.values(S().buyers).map(b => `<button role="menuitem" class="${b.id === S().buyerId ? 'on' : ''}" data-act="setorg" data-v="${b.id}"><span class="body-l">${h(b.name)}</span><span class="small muted">${h(b.segment)}</span></button>`).join(''); document.body.appendChild(m); setTimeout(() => document.addEventListener('click', () => m.remove(), { once: true }), 0); },
  setorg(el) { S().buyerId = el.dataset.v; UI.prefs.d = null; UI.md = null; render(); },
  examples(el) { const r = el.getBoundingClientRect(); const m = document.createElement('div'); m.className = 'menu'; m.setAttribute('role', 'menu'); m.style.top = r.bottom + 4 + 'px'; m.style.left = r.left + 'px'; m.innerHTML = [['gala', 'Gala for 180 guests'], ['fi', 'Pikkujoulut, in Finnish'], ['milk', '1,000 L lactose-free milk'], ['voice', 'Sample voice request']].map(([k, l]) => `<button role="menuitem" data-act="ex" data-v="${k}"><span class="body-l">${l}</span></button>`).join(''); document.body.appendChild(m); setTimeout(() => document.addEventListener('click', () => m.remove(), { once: true }), 0); },
  async ex(el) { const v = el.dataset.v; UI.ap.expanded = true; if (v === 'voice') return voice(); UI.ap.text = { gala: F.GALA, fi: F.PIKKUJOULU, milk: F.SCENES.S2.text }[v]; UI.ap.note = null; render(); },
  async plan() { const t = $('#apText'); UI.ap.expanded = false; await planText(t ? t.value : UI.ap.text); },
  expand() { UI.ap.expanded = true; render(); const t = $('#apText'); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); } },
  mic() { const SR = G.SpeechRecognition || G.webkitSpeechRecognition; if (UI.ap.listening && UI.rec) { UI.rec.stop(); return; } if (!SR) { UI.ap.note = 'Voice input is not available in this view. Type, or use Examples → Sample voice request.'; render(); return; } try { const rec = new SR(); UI.rec = rec; rec.lang = /[äö]|hengelle/i.test(UI.ap.text) ? 'fi-FI' : 'en-US'; rec.interimResults = true; rec.onresult = e => { let t = ''; for (const r of e.results) t += r[0].transcript; UI.ap.text = t; const x = $('#apText'); if (x) x.value = t; }; rec.onerror = e => { UI.ap.listening = false; UI.ap.note = 'Microphone unavailable (' + e.error + ').'; render(); }; rec.onend = () => { UI.ap.listening = false; render(); if (UI.ap.text) planText(UI.ap.text); }; rec.start(); UI.ap.listening = true; UI.ap.note = 'Listening…'; render(); } catch (e) { UI.ap.note = 'Voice input is not available in this view.'; render(); } },
  async guests(el) { const ev = curEvent(); if (ev) await rescale(Math.max(10, ev.guests + +el.dataset.d)); },
  evbasket() { basketSheet(curEvent()); }, evmenu() { menuSheet(curEvent()); }, evsafety() { safetySheet(curEvent()); }, evtimeline() { timelineSheet(curEvent()); }, evdelta() { deltaSheet(curEvent()); },
  evrules() { sheet('Rules', decisionsHtml(curEvent().plan.policy) + dataNote(['policy_decision', 'decision_rule_hit', 'mandate'])); },
  evreconcile() { reconcileSheet(curEvent()); }, evreport() { reportSheet(curEvent()); },
  async allused() { const ev = curEvent(); const pred = F.predictReconciliation(ev.eventId); for (const p of pred) { p.used = r2(p.ordered + p.carriedIn); p.kept = 0; p.wasted = 0; p.redistributed = 0; } const g = $('#rcG'); await F.reconcileEvent(ev.eventId, pred, g ? +g.value : ev.guests, buyer().approvers[1] ? buyer().approvers[1].name : buyer().admin.name); closeSheet(); render(); reportSheet(ev); },
  async saverec() { const ev = curEvent(); const g = +$('#rcG').value || ev.guests; const res = await F.reconcileEvent(ev.eventId, UI.recDraft, g, buyer().approvers[1] ? buyer().approvers[1].name : buyer().admin.name); if (res.errors) { snack(res.errors[0]); return; } closeSheet(); render(); reportSheet(ev); },
  async nextgala() { closeSheet(); go('autopilot'); await planText('Gala dinner on Friday 27 November for 160 guests: salmon starter, beef tenderloin with potato gratin, chocolate mousse. 10 vegans, 6 gluten-free.'); snack('Quantities adjusted from your last galas; leftovers used first.'); },
  order(el) { const r = S().processes.find(p => p.traceId === el.dataset.trace); if (r) processSheet(r.processId); },
  plans() { plansSheet(curTrace()); }, products() { productsSheet(curTrace()); }, trrules() { sheet('Rules', decisionsHtml(curTrace().policy) + dataNote(['policy_decision', 'decision_rule_hit'])); },
  async force() { await busy(async () => { const T = await F.forceLines('BUY-KAARI', [[BY_KEY.almond_drink_pahkinapuu.gtin, 240]], C.addDays(C.clock.today(), 4), '240 L almond drink, forced'); UI.ap.traceId = T.traceId; UI.ap.mode = 'order'; }); },
  async choose(el) { const T = curTrace(); const l = T.lines.find(x => x.lineId === el.dataset.line); const pick = l.ranked[0].gtin; closeSheet(); await busy(async () => { const nT = await F.runAgent(T.text, { buyerId: T.buyerId, parsed: clone(T.parsed), choices: { [l.lineId]: el.dataset.g }, manualChoice: { agentPick: pick, chosen: el.dataset.g } }); nT.manualChoice = { lineId: l.lineId, agentPick: pick, chosen: el.dataset.g, kind: 'preference' }; const rec = S().processes.find(p => p.traceId === nT.traceId); if (rec) rec.decision.manualChoice = nT.manualChoice; UI.ap.traceId = nT.traceId; }); snack('Re-planned with your choice. Saved as a preference.'); },
  cmp(el) { if (!UI.compare.includes(el.dataset.g)) UI.compare.push(el.dataset.g); if (UI.compare.length >= 2) compareSheet(UI.compare); else snack('Added. Pick one more to compare.'); }, cmpclear() { UI.compare = []; closeSheet(); },
  fav(el) { const pf = S().profiles[S().buyerId]; tog(pf.favourites, el.dataset.g); pf.version++; UI.prefs.d = null; C.audit({ actor: 'human:' + buyer().admin.name, action: 'preferences_updated', buyerId: S().buyerId, reason: `v${pf.version}: favourites ${BY_GTIN[el.dataset.g].name}` }); snack(pf.favourites.includes(el.dataset.g) ? 'Added to favourites' : 'Removed from favourites'); },
  async offer(el) { await offerSheet(S().offers[el.dataset.id]); },
  async 'tamper-offer'() { const o = UI.curOffer; o.unitPrice = r2(o.unitPrice * .8); await offerSheet(o); }, async 'expire-offer'() { C.clock.advance(16); await offerSheet(UI.curOffer); },
  approval(el) { approvalSheet(el.dataset.id); },
  apl(el) { UI.apDraft.lines[el.dataset.l] = { action: el.dataset.v }; el.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === el)); $('#mod-' + el.dataset.l).classList.toggle('hide', el.dataset.v !== 'modify'); },
  apc(el) { const o = $('#cs-' + el.dataset.l); o.textContent = Math.max(0, +o.textContent + +el.dataset.d); UI.apDraft.lines[el.dataset.l] = { action: 'modify' }; },
  async apsubmit(el) { const d = UI.apDraft; const a = S().approvals.find(x => x.approvalId === d.id); const b = S().buyers[a.buyerId]; const who = b.approvers.find(x => x.id === $('#apWho').value) || b.approvers[0]; const reason = $('#apWhy').value; const lines = {}; for (const l of a.lines) { const x = el.dataset.all ? { action: 'reject' } : (d.lines[l.lineId] || { action: 'approve' }); if (x.action === 'modify') x.cases = +$('#cs-' + l.lineId).textContent; lines[l.lineId] = x; } closeSheet(); await busy(async () => { const r = await F.decideApproval(a.approvalId, { approver: who, lines, reason }); snack(r.order ? `${r.order.orderId} placed` : 'Rejected'); }); },
  ofilter(el) { UI.orders.filter = el.dataset.v; render(); }, omore() { UI.orders.more = true; render(); }, proc(el) { processSheet(el.dataset.id); },
  metric(el) { const m = F.METRIC_DEFS[el.dataset.v]; sheet(m.name, `<dl class="kv body"><dt>Formula</dt><dd class="mono" style="text-align:right;word-break:normal">${h(m.formula)}</dd><dt>Source</dt><dd>${m.source_view}</dd><dt>Grain</dt><dd>${h(m.grain)}</dd><dt>Better when</dt><dd>${h(m.better_when)}</dd><dt>For</dt><dd>${h(m.audience)}</dd></dl>${dataNote(['metric_definition', m.source_view])}`); },
  rec(el) { const r = F.recommendations(S().buyerId).find(x => x.id === el.dataset.id); sheet(r.title, `<p class="body-l">${h(r.detail)}</p><p class="body">${h(r.impact)}</p>${r.context ? `<p class="body muted">${h(r.context)}</p>` : ''}<p class="small muted">Based on ${r.evidence.n} orders, ${h(r.evidence.period)}.</p><div class="list">${r.evidence.processIds.slice(0, 6).map(id => { const p = S().processes.find(x => x.processId === id); return p ? li({ title: h(p.request.excerpt), sub: dateL(p.createdAt.slice(0, 10)), act: 'proc', attrs: `data-id="${id}"` }) : ''; }).join('')}</div>`, r.status === 'applied' || r.action.type === 'info' ? '' : `<button class="btn filled" data-act="applyrec" data-id="${r.id}">Apply</button>`); },
  async applyrec(el) { closeSheet(); await busy(async () => { const r = await F.applyRecommendation(S().buyerId, el.dataset.id, buyer().admin.name); UI.md = null; UI.prefs.d = null; if (r) snack('Applied. ' + (r.action.type === 'mandate' ? 'New mandate version signed.' : 'Saved.'), r.id === 'silent-dairy' ? ['Try milk order', 'scene2'] : null); }); },
  async scene2() { await scene('S2'); },
  allmetrics: allMetricsSheet,
  theme(el) { const v = el.dataset.v; if (v === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v; try { localStorage.setItem('aimo-theme', v); } catch (e) { } render(); },
  preset(el) { const d = pd(); d.org.preset = el.dataset.v; d.org.weights = { ...C.PRESETS[el.dataset.v] }; render(); },
  qf(el) { const d = pd(); const f = QF.find(x => x[0] === el.dataset.v)[2]; const i = d.org.filters.findIndex(x => JSON.stringify(x) === JSON.stringify(f)); i >= 0 ? d.org.filters.splice(i, 1) : d.org.filters.push(clone(f)); render(); },
  unfav(el) { tog(pd().favourites, el.dataset.g); render(); }, unpin(el) { delete pd().needGroups[el.dataset.g]; render(); },
  async savepref() { const d = pd(); d.version = S().profiles[S().buyerId].version + 1; S().profiles[S().buyerId] = clone(d); await C.audit({ actor: 'human:' + buyer().admin.name, action: 'preferences_updated', buyerId: S().buyerId, reason: `v${d.version}: ${C.PRESET_LABELS[d.org.preset] || 'custom'}, ${d.favourites.length} favourites` }); UI.prefs.d = null; snack(`Preferences saved (version ${d.version})`); render(); },
  mal(el) { tog(md().hardExclusions.allergens, el.dataset.v); render(); }, mdi(el) { tog(md().hardExclusions.diet, el.dataset.v); render(); }, msil(el) { const d = md(); d.substitution.silentCategories = d.substitution.silentCategories || []; tog(d.substitution.silentCategories, el.dataset.v); render(); },
  async sign() { const b = buyer(); const d = clone(md()); d.version = C.mandateOf(b.id).version + 1; for (const k of ['issuedBy', 'validFrom', 'validUntil', 'type', 'buyerId', 'preferenceProfile']) delete d[k]; const r = await C.registerMandate(b.id, await C.signMandate(b.id, d), `v${d.version} signed in settings`); UI.md = null; render(); snack(r.ok ? `Signed. Mandate version ${d.version} is active.` : 'Signature rejected'); },
  async verify() { UI.audit.verify = await C.auditVerify(); render(); }, async tamper() { C.tamper(); UI.audit.verify = await C.auditVerify(); render(); }, async untamper() { C.untamper(); UI.audit.verify = await C.auditVerify(); render(); }, aview(el) { UI.audit.view = el.dataset.v; render(); },
  htab(el) { UI.how.tab = el.dataset.v; render(); }, node(el) { UI.how.node = el.dataset.v; render(); },
  dm(el) { UI.how.ent = el.dataset.v; if (document.querySelector('.sheet')) { sheet('Data model', dataModel([el.dataset.v])); } else { UI.how.tab = 'data'; go('how'); render(); $('#main').scrollTop = 0; } },
  async demo(el) { await DEMO[+el.dataset.i][3](); },
  async reset() { await busy(async () => { await F.boot(); await opening(); }); go('autopilot'); snack('Demo reset'); },
};
async function voice() { const target = F.GALA; UI.ap.text = ''; UI.ap.expanded = true; UI.ap.note = 'Sample voice request, transcribed live.'; render(); for (let i = 0; i <= target.length; i += 3) { const x = $('#apText'); if (x) x.value = target.slice(0, i); await new Promise(r => setTimeout(r, 16)); } UI.ap.text = target; await planText(target); }
document.addEventListener('click', e => { const el = e.target.closest('[data-act]'); if (el && ACT[el.dataset.act]) ACT[el.dataset.act](el, e); });
const INP = { ap(el) { UI.ap.text = el.value; }, w(el) { const d = pd(); d.org.weights = { ...C.effectiveProfile(d, null).weights }; d.org.weights[el.dataset.c] = +el.value / 100; d.org.preset = 'custom'; const w = C.normaliseW(d.org.weights); for (const c of C.CRITERIA) { const o = $('#wv-' + c); if (o) o.textContent = Math.round(w[c] * 100) + '%'; } $('#pv').innerHTML = preview(); }, mdl(el) { md().substitution.maxPriceDeltaPct = +el.value; $('#mdlv').textContent = el.value + '%'; }, rec(el) { UI.recDraft[+el.dataset.i][el.dataset.k] = parseFloat(el.value) || 0; } };
const CHG = { lim(el) { md().limits[el.dataset.k] = parseFloat(el.value) || 0; }, msw(el) { md().substitution[el.dataset.k] = el.checked; }, pin(el) { if (!el.value) return; const p = BY_GTIN[el.value]; pd().needGroups[C.needGroupId(p)] = { pinned: p.gtin, fallback: [] }; render(); }, async kill(el) { await F.setKill(el.dataset.id, !el.checked, 'Valio Aimo operations'); render(); snack(el.checked ? 'Agent active' : 'Agent suspended'); } };
document.addEventListener('input', e => { const el = e.target.closest('[data-in]'); if (el && INP[el.dataset.in]) INP[el.dataset.in](el); });
document.addEventListener('change', e => { const el = e.target.closest('[data-in]'); if (el && CHG[el.dataset.in]) CHG[el.dataset.in](el); });
document.addEventListener('keydown', e => { if (e.key === 'Tab' && $('#layer .sheet')) { const f = [...$('#layer .sheet').querySelectorAll('button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])')].filter(x => !x.disabled && x.offsetParent !== null); if (f.length) { const i = f.indexOf(document.activeElement); if (e.shiftKey && (i <= 0)) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && (i === -1 || i === f.length - 1)) { e.preventDefault(); f[0].focus(); } } } if (e.key === 'Escape') { document.querySelectorAll('.menu').forEach(m => m.remove()); if ($('.scrim')) closeSheet(); } if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && e.target.id === 'apText') ACT.plan(); });

// =============================================================== boot
async function opening() {
  S().buyerId = 'BUY-POHJOLA';
  await F.runScene('S3'); await F.runScene('S4'); await F.runScene('S2'); S().buyerId = 'BUY-POHJOLA';
  const b = F.parseBrief(F.GALA); const r = await F.planEvent(b, { buyerId: 'BUY-POHJOLA' }); await F.orderEvent(r.eventId);
  UI.ap = { text: F.GALA, mode: 'event', eventId: r.eventId, traceId: null }; UI.audit.verify = await C.auditVerify();
}
(async function start() {
  try { const t = localStorage.getItem('aimo-theme'); if (t && t !== 'system') document.documentElement.dataset.theme = t; } catch (e) { }
  const r = location.hash.slice(1); if (SCREENS[r]) UI.route = r;
  try { await F.boot(); await opening(); render(); } catch (e) { console.error(e); $('#main').innerHTML = `<div class="page"><p class="empty">The demo could not start in this browser (${h(e.message)}). Try a current Chrome, Safari or Firefox.</p></div>`; }
})();
})(window);
