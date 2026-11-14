/* Aimo Agent Gateway — flows: buyer agent loop, checkout & approvals, outcome store,
 * seeded history, insights & recommendations, Event Autopilot, consumption & waste, ops. */
(function (G) {
'use strict';
const C = G.AimoCore;
const { BY_GTIN, BY_KEY, clock, addDays, dayLabel, fq, money, money0, r2, r1, sum, median, quant, clone, rid, audit } = C;
const RECIPES = C.D.recipes.recipes; const RBY = Object.fromEntries(RECIPES.map(r => [r.id, r]));
const STYLE_BUFFER = C.D.recipes.styleBuffer;
const S = () => C.S;
const agentOf = bid => S().buyers[bid].agents[0].id;
const agentActor = bid => 'agent:' + agentOf(bid).split(':')[1];

// ======================================================= agent-side request parser (deterministic)
const WEEKDAYS = { monday: 0, tuesday: 1, wednesday: 2, thursday: 3, friday: 4, saturday: 5, sunday: 6, maanantai: 0, tiistai: 1, keskiviikko: 2, torstai: 3, perjantai: 4, lauantai: 5, sunnuntai: 6 };
function nextWeekday(wd, today) { let d = addDays(today, 1); while (C.weekday(d) !== wd) d = addDays(d, 1); return d; }
function parseDate(text, today) {
  const t = text.toLowerCase(); let m;
  if ((m = t.match(/(\d{4}-\d{2}-\d{2})/))) return { date: m[1], phrase: m[1] };
  if (/\b(tomorrow|huomenna)\b/.test(t)) return { date: addDays(today, 1), phrase: 'tomorrow' };
  if (/\b(today|tänään)\b/.test(t)) return { date: today, phrase: 'today' };
  if (/\bnext week\b|ensi viikolla/.test(t)) return { date: nextWeekday(0, today), phrase: 'next week (Monday)' };
  if ((m = t.match(/\b(\d{1,2})\.(\d{1,2})\.?/))) { const d = `2026-${String(+m[2]).padStart(2, '0')}-${String(+m[1]).padStart(2, '0')}`; return { date: d < today ? d.replace('2026', '2027') : d, phrase: m[0] }; }
  const mon = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  if ((m = t.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/)) || (m = t.match(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})/))) { const day = isNaN(+m[1]) ? +m[2] : +m[1]; const mo = isNaN(+m[1]) ? mon[m[1]] : mon[m[2]]; return { date: `2026-${String(mo).padStart(2, '0')}-${String(day).padStart(2, '0')}`, phrase: m[0] }; }
  for (const [name, wd] of Object.entries(WEEKDAYS)) { const re = new RegExp('\\b' + name + '(?:na|ina|ta)?\\b'); if (re.test(t)) { let d = nextWeekday(wd, today); if (new RegExp('(?:next|ensi) ' + name).test(t) && (new Date(d) - new Date(today)) / 864e5 < 6) d = addDays(d, 7); if ((m = t.match(/the (\d{1,2})(?:st|nd|rd|th)/))) { let x = today; for (let i = 0; i < 60; i++) { x = addDays(x, 1); if (+x.slice(8) === +m[1]) { d = x; break; } } } return { date: d, phrase: name }; } }
  if ((m = t.match(/the (\d{1,2})(?:st|nd|rd|th)/))) { let x = today; for (let i = 0; i < 60; i++) { x = addDays(x, 1); if (+x.slice(8) === +m[1]) return { date: x, phrase: m[0] }; } }
  return null;
}
const UNIT_MAP = { l: 'L', litre: 'L', litres: 'L', liter: 'L', liters: 'L', ltr: 'L', kg: 'kg', kilo: 'kg', kilos: 'kg', kilograms: 'kg', pcs: 'pcs', pieces: 'pcs', piece: 'pcs', units: 'pcs', kpl: 'pcs', litraa: 'L', kiloa: 'kg' };
function parseRequest(text) {
  const today = clock.today(); const nb = parseDate(text, today);
  const so = (text.match(/\b(SO-\d+)\b/i) || [])[1];
  const globalDiet = []; for (const [re, tag] of [[/lactose[- ]?free/i, 'lactose-free'], [/(milk|dairy)[- ]?free/i, 'milk-free'], [/nut[- ]?free/i, 'nut-free'], [/gluten[- ]?free/i, 'gluten-free']]) if (re.test(text)) globalDiet.push(tag);
  const body = text.replace(/(\d),(\d{3})\b/g, '$1$2').replace(/(\d)\.(\d{3})\b/g, '$1$2').replace(/\b(find|choose|pick)\b.*$/i, '');
  const clauses = body.split(/[,;:]|\.(?=\s|$)|\band\b|\bja\b|—|–/);
  const lines = []; let n = 0;
  for (let c of clauses) {
    const m = c.match(/(\d[\d,  ]*(?:\.\d+)?)\s*(litres?|liters?|ltr|l|kg|kilos?|kilograms|pcs|pieces?|units|kpl|litraa|kiloa)?\b\s*(?:of\s+)?([a-zåäö][a-zåäö &\-']+)/i);
    if (!m) continue;
    const qty = parseFloat(m[1].replace(/[,  ]/g, '')); let unit = m[2] ? UNIT_MAP[m[2].toLowerCase()] : null; let prod = m[3].trim();
    if (/^(guests?|people|persons|pax|covers|hengelle|henkeä|vierasta|minutes|min|days?|weeks?|%)/i.test(prod)) continue;
    prod = prod.replace(/\b(by|for|before|on|next|this|from|at|to)\b.*$/i, '').replace(/\b(we|i|need|please|order)\b/gi, '').trim();
    if (!prod) continue;
    if (!unit) unit = 'pcs';
    for (const d of globalDiet) if (!prod.toLowerCase().includes(d.replace('-', '')) && !prod.toLowerCase().includes(d)) prod = d + ' ' + prod;
    lines.push({ lineId: 'L' + (++n), text: prod, label: prod, qty, unit });
  }
  return { needBy: nb ? nb.date : addDays(today, 3), needByPhrase: nb ? nb.phrase : 'not stated — assumed in 3 days', assumed: !nb, standingOrderId: so ? so.toUpperCase() : null, lines, diet: globalDiet };
}

// ======================================================= planning wrapper
async function planRequest(bid, lines, needBy, opts = {}) {
  const buyer = S().buyers[bid]; const [mandate, mcheck] = await C.mandateCheck(bid);
  const signals = C.computeSignals(bid);
  const ctx = { buyer, mandate, profile: S().profiles[bid], signals, leftovers: opts.useLeftovers ? S().leftovers.filter(l => l.buyerId === bid) : [] };
  const out = lines.map(l => C.planLine(ctx, l, l.needBy || needBy, (opts.choices || {})[l.lineId], opts.usage));
  const offers = {}; const verifs = {};
  for (const l of out) for (const it of l.ranked.slice(0, opts.offerDepth || 4)) { if (!offers[it.gtin]) { const o = await C.issueOffer(it.gtin, l.lineNeedBy || needBy, bid); offers[it.gtin] = o; verifs[o.offerId] = await C.verifyOffer(o); } it.offerId = offers[it.gtin].offerId; }
  for (const l of out) for (const p of l.plans) for (const pl of p.lines) pl.offerId = offers[pl.gtin] ? offers[pl.gtin].offerId : null;
  const plans = C.combine(out);
  for (const p of plans) { p.planId = rid('PL'); p.policy = evaluate(bid, p.lines, out.map(l => ({ lineId: l.lineId, qty: l.qtyAfterLeftovers, needBy: l.lineNeedBy || needBy, label: l.label })), mandate, mcheck, signals, opts.policyExtra || {}); }
  return { lines: out, plans, offers, verifs, mandate, mcheck, signals };
}
function evaluate(bid, lines, requestLines, mandate, mcheck, signals, extra = {}) {
  const buyer = S().buyers[bid]; const ag = S().agents[agentOf(bid)];
  return C.policyEvaluate(Object.assign({ buyer, mandate, mandateCheck: mcheck, lines, requestLines, total: r2(sum(lines.map(l => l.lineTotal))), mtd: buyer.monthToDateEUR, profile: S().profiles[bid], signals, agentId: ag.id, killSwitch: { on: ag.killed, by: ag.killedBy } }, extra));
}
const choosePlan = plans => [...plans].sort((a, b) => C.RANK[a.policy.outcome] - C.RANK[b.policy.outcome] || b.coverage.pctByNeedBy - a.coverage.pctByNeedBy || a.total - b.total)[0];

// ======================================================= buyer agent loop
async function runAgent(text, opts = {}) {
  const bid = opts.buyerId || S().buyerId; const buyer = S().buyers[bid]; const ag = S().agents[agentOf(bid)];
  const traceId = opts.traceId || rid('TR'); const actor = agentActor(bid); const started = clock.now();
  ag.calls += 1; ag.lastSeen = clock.iso();
  const T = { traceId, buyerId: bid, agentId: ag.id, text, steps: [], startedAt: clock.iso(), toolCalls: 0, exceptions: { offersRequoted: 0, priceChanged: 0, insufficientStock: 0 }, channel: opts.channel || 'agent-api', usage: opts.usage || { type: 'adhoc' } };
  S().traces[traceId] = T;
  const step = (id, title, status, detail, data) => { const s = { id, title, status, detail, data }; T.steps.push(s); return s; };
  const parsed = opts.parsed || parseRequest(text); T.parsed = parsed;
  step('understand', 'Understood the request', 'done', `${parsed.lines.length} line${parsed.lines.length > 1 ? 's' : ''}, need-by ${dayLabel(parsed.needBy)}${parsed.assumed ? ' (assumed)' : ''}${parsed.standingOrderId ? ', standing order ' + parsed.standingOrderId : ''}`, parsed);
  if (!parsed.lines.length) { step('outcome', 'Could not find a quantity and product', 'error', 'Try e.g. "1,000 litres of lactose-free milk by Monday".'); T.outcome = 'ERROR'; return T; }
  // kill switch: Valio Aimo-side guardrail stops the agent before any work
  if (ag.killed) { const pol = evaluate(bid, [], [], null, { ok: true }, null); T.policy = pol; step('policy', 'Valio Aimo guardrail', 'block', pol.decisions.map(d => d.reason).join(' ')); await audit({ traceId, actor: 'system:policy', action: 'policy_decision', buyerId: bid, decision: 'BLOCK', ruleIds: ['V3'], reason: pol.decisions[0].reason }); T.outcome = 'BLOCK'; await closeProcess(T, 'blocked', {}); return T; }
  const [mandate, mcheck] = await C.mandateCheck(bid); T.toolCalls++;
  step('mandate', 'Checked the Intent Mandate', mcheck.ok ? 'done' : 'block', mcheck.ok ? `${mandate.mandateId} v${mandate.version} signed by ${mandate.issuedBy.name} — ${mcheck.detail}` : 'No valid mandate: ' + mcheck.detail, mandate);
  await audit({ traceId, actor, action: 'search', buyerId: bid, inputs: { lines: parsed.lines.map(l => ({ text: l.text, qty: l.qty, unit: l.unit })), needBy: parsed.needBy }, reason: parsed.lines.map(l => `${fq(l.qty, l.unit)} ${l.text}`).join('; ') });
  let pr = await planRequest(bid, parsed.lines, parsed.needBy, { choices: opts.choices, usage: opts.usage, policyExtra: soExtra(bid, parsed) }); T.toolCalls += 3;
  T.lines = pr.lines; T.plans = pr.plans; T.offers = pr.offers; T.verifs = pr.verifs;
  const searched = sum(pr.lines.map(l => l.searched)); const excl = sum(pr.lines.map(l => l.excluded.length));
  step('search', 'Searched the catalog', 'done', `${searched} candidate products across ${pr.lines.length} need${pr.lines.length > 1 ? 's' : ''} (L0 catalog, browse-only)`);
  step('filter', 'Applied hard filters', 'done', `${excl} excluded with a logged reason (diet, allergens, spec, delivery)`);
  await audit({ traceId, actor: 'system:gateway', action: 'candidates_filtered', buyerId: bid, inputs: { excluded: pr.lines.flatMap(l => l.excluded.map(e => ({ gtin: e.gtin, code: e.code }))) }, reason: pr.lines.flatMap(l => l.excluded.slice(0, 3).map(e => `${e.name}: ${e.reason}`)).join('; ') });
  const nOff = Object.keys(pr.offers).length; const nVer = Object.values(pr.verifs).filter(v => v.verified).length;
  step('offers', 'Received signed offers', nVer === nOff ? 'done' : 'warn', `${nOff} Offer Attestations (VC 2.0 / JWS ES256), ${nVer}/${nOff} passed all trust checks`);
  await audit({ traceId, actor, action: 'quote', buyerId: bid, refs: { offerIds: Object.values(pr.offers).map(o => o.offerId) }, reason: `${nOff} signed offers, valid 15 min` });
  step('rank', 'Ranked with your preferences', 'done', pr.lines.map(l => l.ranked.length ? `${l.label}: ${l.ranked[0].name} (${l.ranked[0].rankReason})` : `${l.label}: no eligible product`).join(' · '));
  const chosen = choosePlan(pr.plans);
  step('plan', 'Built fulfilment plans', pr.plans.length ? 'done' : 'error', pr.plans.length ? `${pr.plans.length} plan${pr.plans.length > 1 ? 's' : ''}; agent proposes ${chosen.label} (${chosen.policy.outcome})` : 'No plan possible');
  await audit({ traceId, actor, action: 'plan', buyerId: bid, refs: { planIds: pr.plans.map(p => p.planId) }, reason: pr.plans.map(p => `${p.label} ${p.summary} → ${p.policy.outcome}`).join(' | ') });
  if (!chosen) { T.outcome = 'ERROR'; return T; }
  T.chosenPlan = chosen.planId;
  for (const l of chosen.lines.filter(l => l.role === 'substitute')) await audit({ traceId, actor, action: 'substitution_proposed', buyerId: bid, refs: { gtin: l.gtin, for: l.substituteFor.gtin }, reason: `${l.name} for ${l.substituteFor.name} (${l.changeText}, ${l.priceDeltaPct >= 0 ? '+' : ''}${l.priceDeltaPct}%)` });
  if (opts.manualChoice) await audit({ traceId, actor: 'human:' + buyer.admin.name, action: 'manual_choice', buyerId: bid, refs: { agentPick: opts.manualChoice.agentPick, chosen: opts.manualChoice.chosen }, reason: `Chose ${BY_GTIN[opts.manualChoice.chosen].name} instead of the agent's pick (preference, not an error)` });
  // expired-offer drill: time passes and the supplier price moves before checkout
  if (opts.simulateDelay) {
    clock.advance(16); const g = chosen.lines[0].gtin; S().prices[g] = r2(S().prices[g] + 0.02);
    step('wait', 'Paused 16 minutes before checkout', 'warn', `Meanwhile the price of ${BY_GTIN[g].name} changed to ${money(S().prices[g])}/${BY_GTIN[g].unit}.`);
  }
  let res = await checkout(T, chosen, opts);
  if (res.error) {
    T.exceptions[res.error === 'price_changed' ? 'priceChanged' : 'offersRequoted']++;
    step('checkout', 'Checkout refused: ' + res.error, 'warn', res.detail);
    await audit({ traceId, actor: 'system:gateway', action: res.error, buyerId: bid, decision: null, reason: res.detail });
    pr = await planRequest(bid, parsed.lines, parsed.needBy, { choices: opts.choices, usage: opts.usage, policyExtra: soExtra(bid, parsed) }); T.toolCalls += 3; T.exceptions.offersRequoted++;
    await audit({ traceId, actor, action: 'requote', buyerId: bid, refs: { offerIds: Object.values(pr.offers).map(o => o.offerId) }, reason: 'Re-quoted at current prices; no price was changed silently' });
    T.lines = pr.lines; T.plans = pr.plans; Object.assign(T.offers, pr.offers); Object.assign(T.verifs, pr.verifs);
    const c2 = choosePlan(pr.plans); T.chosenPlan = c2.planId;
    step('requote', 'Re-quoted and re-planned', 'done', `New signed offers; ${c2.label} now ${money(c2.total)} (${c2.policy.outcome})`);
    res = await checkout(T, c2, opts);
  }
  T.timeToOrderMin = Math.max(1, Math.round((clock.now() - started) / 60000));
  return T;
}
function soExtra(bid, parsed) {
  if (!parsed.standingOrderId) return {}; const so = S().buyers[bid].standingOrders.find(s => s.id === parsed.standingOrderId); if (!so) return {};
  const wh = C.weeklyHistory(S().buyers[bid])[BY_KEY[so.productKey].gtin]; const line = parsed.lines[0];
  return { standingOrder: { id: so.id, qty: line ? line.qty : so.qty, median: wh ? wh.median8w : so.qty, unit: so.unit } };
}

// ======================================================= checkout → order / approval / block
async function checkout(T, plan, opts = {}) {
  const bid = T.buyerId; const buyer = S().buyers[bid];
  // checks 1–6 on every offer the plan relies on
  for (const l of plan.lines) {
    const o = S().offers[l.offerId]; if (!o) continue; const v = await C.verifyOffer(o, l.qty); T.verifs[o.offerId] = v;
    if (!v.verified) { const val = v.checks.find(c => c.id === 'validity'), rev = v.checks.find(c => c.id === 'reverify'); if (rev && !rev.ok && /price now/.test(rev.detail)) return { error: 'price_changed', detail: `${o.name}: ${rev.detail}. The gateway never charges a different price; the agent must re-quote.` }; if (val && !val.ok) return { error: 'offer_expired', detail: `${o.name}: offer ${val.detail}.` }; if (rev && !rev.ok) return { error: 'insufficient_stock', detail: rev.detail }; }
  }
  const [mandate, mcheck] = await C.mandateCheck(bid);
  const pol = evaluate(bid, plan.lines, (T.lines || []).map(l => ({ lineId: l.lineId, qty: l.qtyAfterLeftovers, needBy: l.lineNeedBy || T.parsed.needBy, label: l.label })), mandate, mcheck, C.computeSignals(bid), Object.assign(soExtra(bid, T.parsed), opts.policyExtra || {}));
  const co = { checkoutId: rid('CS'), traceId: T.traceId, buyerId: bid, planId: plan.planId, lines: clone(plan.lines), total: plan.total, policy: pol, createdAt: clock.iso(), status: pol.outcome === 'BLOCK' ? 'blocked' : pol.outcome === 'APPROVE' ? 'requires_approval' : 'ready', title: opts.title || T.text, kind: opts.kind || 'agent', eventId: opts.eventId || null };
  S().checkouts[co.checkoutId] = co; T.checkoutId = co.checkoutId; T.policy = pol; T.outcome = pol.outcome;
  T.steps.push({ id: 'policy', title: 'Policy engine decided', status: pol.outcome === 'BLOCK' ? 'block' : 'done', detail: `${pol.outcome}${pol.ruleIds.length ? ' — ' + pol.ruleIds.join(', ') : ''}. ${pol.summary}` });
  await audit({ traceId: T.traceId, actor: 'system:policy', action: 'policy_decision', buyerId: bid, decision: pol.outcome, ruleIds: pol.ruleIds, refs: { checkoutId: co.checkoutId, planId: plan.planId, mandateId: mandate && mandate.mandateId }, reason: pol.decisions.map(d => `${d.ruleId}: ${d.reason}`).join(' ') || 'No rule fired.' });
  if (co.status === 'blocked') { T.steps.push({ id: 'outcome', title: 'Blocked — nothing was ordered', status: 'block', detail: pol.decisions.filter(d => d.outcome === 'BLOCK').map(d => d.reason).join(' ') }); await audit({ traceId: T.traceId, actor: 'system:gateway', action: 'checkout_blocked', buyerId: bid, decision: 'BLOCK', ruleIds: pol.ruleIds, reason: 'Order not placed.' }); await closeProcess(T, 'blocked', { plan }); return { co }; }
  if (co.status === 'requires_approval') {
    const ap = { approvalId: rid('AP'), checkoutId: co.checkoutId, traceId: T.traceId, buyerId: bid, createdAt: clock.iso(), createdMs: Date.now(), status: 'pending', title: co.title, kind: co.kind, eventId: co.eventId, total: co.total, policy: pol, lines: co.lines, requestLines: (T.lines || []).map(l => ({ lineId: l.lineId, label: l.label, qty: l.qtyAfterLeftovers, unit: l.unit })), needBy: T.parsed.needBy, alternatives: (T.plans || []).filter(p => p.planId !== plan.planId).map(p => ({ label: p.label, summary: p.summary, outcome: p.policy.outcome, ruleIds: p.policy.ruleIds })) };
    S().approvals.unshift(ap); T.approvalId = ap.approvalId;
    T.steps.push({ id: 'outcome', title: 'Sent to one human approval', status: 'approve', detail: `${buyer.admin.name} gets one consolidated approval card (${pol.ruleIds.filter(r => pol.decisions.find(d => d.ruleId === r && d.outcome === 'APPROVE')).join(', ')}).` });
    await audit({ traceId: T.traceId, actor: 'system:gateway', action: 'approval_requested', buyerId: bid, decision: 'APPROVE', ruleIds: pol.ruleIds, refs: { approvalId: ap.approvalId, checkoutId: co.checkoutId }, reason: `Approval ${ap.approvalId} for ${money(co.total)} sent to ${buyer.approvers.map(a => a.name).join(' / ')}` });
    return { co, ap };
  }
  const order = await placeOrder(co, co.lines, T, null);
  T.steps.push({ id: 'outcome', title: pol.outcome === 'NOTIFY' ? 'Ordered — buyer notified' : 'Ordered automatically', status: 'done', detail: `${order.orderId} confirmed (${order.backendRef}), ${money(order.total)}. Signed order confirmation issued.` });
  if (pol.outcome === 'NOTIFY') { S().notifications.unshift({ id: rid('NT'), ts: clock.iso(), buyerId: bid, text: `${order.orderId}: ${pol.decisions.map(d => d.reason).join(' ')}`, traceId: T.traceId }); await audit({ traceId: T.traceId, actor: 'system:gateway', action: 'notified', buyerId: bid, decision: 'NOTIFY', ruleIds: pol.ruleIds, refs: { orderId: order.orderId }, reason: `Notification sent to ${buyer.admin.name}` }); }
  await closeProcess(T, 'ordered', { plan, order });
  return { co, order };
}
async function placeOrder(co, lines, T, approval) {
  const bid = co.buyerId; const be = C.BE.placeOrder({ lines });
  const order = { orderId: 'ORD-' + (24000 + S().orders.length + 1), checkoutId: co.checkoutId, traceId: co.traceId, buyerId: bid, lines: clone(lines), total: r2(sum(lines.map(l => l.lineTotal))), placedAt: clock.iso(), backendRef: be.backendOrderRef, status: 'confirmed', approval: approval ? { approvalId: approval.approvalId, approver: approval.decidedBy } : null, eventId: co.eventId };
  const cart = { type: 'OrderConfirmation', orderId: order.orderId, buyerId: bid, lines: lines.map(l => ({ gtin: l.gtin, cases: l.cases, qty: l.qty, unitPrice: l.unitPrice, offerId: l.offerId, deliveryDate: l.deliveryDate })), total: order.total, currency: 'EUR', mandateId: (C.mandateOf(bid) || {}).mandateId, approval: order.approval, issuedAt: order.placedAt };
  order.confirmation = await C.signJws(S().keys.gw, cart, 'order+jwt');
  S().orders.unshift(order); co.status = 'completed'; co.orderId = order.orderId;
  S().buyers[bid].monthToDateEUR = r2(S().buyers[bid].monthToDateEUR + order.total);
  await audit({ traceId: co.traceId, actor: 'system:gateway', action: 'order_placed', buyerId: bid, refs: { orderId: order.orderId, checkoutId: co.checkoutId, offerIds: lines.map(l => l.offerId).filter(Boolean) }, reason: `${order.orderId} ${money(order.total)}, ${lines.length} line${lines.length > 1 ? 's' : ''}, delivery ${[...new Set(lines.map(l => l.deliveryDate))].map(dayLabel).join(', ')}` });
  return order;
}
async function decideApproval(approvalId, d) {
  const ap = S().approvals.find(a => a.approvalId === approvalId); if (!ap || ap.status !== 'pending') return null;
  const co = S().checkouts[ap.checkoutId]; const who = d.approver; const actor = 'human:' + who.name;
  const kept = [], mods = []; let anyReject = false, anyModify = false;
  for (const l of ap.lines) {
    const a = (d.lines || {})[l.lineId] || { action: d.all || 'approve' };
    if (a.action === 'reject') { anyReject = true; mods.push({ gtin: l.gtin, field: 'rejected', from: l.cases, to: 0 }); await audit({ traceId: ap.traceId, actor, action: 'rejected', buyerId: ap.buyerId, refs: { approvalId, lineId: l.lineId, gtin: l.gtin }, decision: 'REJECT', reason: `${l.name}: ${d.reason || 'rejected by approver'}` }); continue; }
    if (a.action === 'modify' && a.cases !== l.cases) { anyModify = true; mods.push({ gtin: l.gtin, field: 'cases', from: l.cases, to: a.cases }); const nl = clone(l); nl.cases = a.cases; nl.qty = Math.round(a.cases * l.caseQty * 1000) / 1000; nl.lineTotal = r2(nl.qty * l.unitPrice); kept.push(nl); await audit({ traceId: ap.traceId, actor, action: 'modified', buyerId: ap.buyerId, refs: { approvalId, lineId: l.lineId }, decision: 'MODIFY', reason: `${l.name}: ${l.cases} → ${a.cases} cases (${d.reason || 'quantity corrected'})` }); continue; }
    kept.push(clone(l));
  }
  ap.decidedAt = clock.iso(); ap.latencyMin = Math.max(1, Math.round((Date.now() - ap.createdMs) / 60000)); ap.decidedBy = { id: who.id, name: who.name, role: who.role }; ap.reason = d.reason || '';
  ap.status = !kept.length ? 'rejected' : anyReject || anyModify ? 'partially_approved' : 'approved'; ap.modifications = mods;
  await audit({ traceId: ap.traceId, actor, action: ap.status === 'rejected' ? 'rejected' : ap.status === 'approved' ? 'approved' : 'partially_approved', buyerId: ap.buyerId, refs: { approvalId }, decision: ap.status.toUpperCase(), ruleIds: ap.policy.ruleIds, reason: `${who.name} (${who.role}) ${ap.status.replace('_', ' ')} ${kept.length}/${ap.lines.length} lines${d.reason ? ' — ' + d.reason : ''}` });
  let order = null;
  if (kept.length) {
    // fixed-price commitment: re-check offers; same price → re-issue, changed price → stop
    for (const l of kept) { if (Math.abs(C.BE.price(l.gtin) - l.unitPrice) > 1e-9) { ap.status = 'price_changed'; return { ap }; } }
    order = await placeOrder(co, kept, S().traces[ap.traceId], ap); ap.orderId = order.orderId;
  } else co.status = 'cancelled';
  const T = S().traces[ap.traceId];
  if (T) { T.approvalDecision = ap; T.steps.push({ id: 'human', title: `${who.name} ${ap.status.replace('_', ' ')}`, status: ap.status === 'rejected' ? 'block' : 'done', detail: order ? `${order.orderId} placed for ${money(order.total)}` : 'Nothing ordered' }); }
  if (T) await closeProcess(T, order ? (ap.status === 'approved' ? 'ordered' : 'partially_approved') : 'rejected', { plan: { lines: ap.lines, planId: co.planId, total: ap.total }, order, approval: ap });
  if (ap.kind === 'event' && ap.eventId) { const ev = S().events.find(e => e.eventId === ap.eventId); if (ev) { ev.orderIds = [...(ev.orderIds || []), ...(order ? [order.orderId] : [])]; ev.status = order ? 'ordered' : 'needs_attention'; } }
  return { ap, order };
}

// ======================================================= outcome store (ProcessRecord)
async function closeProcess(T, status, x) {
  const bid = T.buyerId; const buyer = S().buyers[bid]; const plan = x.plan || {}; const order = x.order; const ap = x.approval;
  const lines = (order ? order.lines : plan.lines || []);
  const subs = lines.filter(l => l.role === 'substitute').map(l => ({ fromGtin: l.substituteFor.gtin, toGtin: l.gtin, fromName: l.substituteFor.name, toName: l.name, category: l.category, changes: l.changes, priceDeltaPct: l.priceDeltaPct }));
  const reqQty = sum((T.lines || []).map(l => l.qty)); const ordQty = sum(lines.map(l => l.qty));
  const best = (T.lines || []).map(l => l.ranked && l.ranked.length ? Math.min(...l.ranked.map(r => r.unitPrice)) : null).filter(x => x != null);
  const sig = C.computeSignals(bid);
  const medDelta = lines.map(l => { const ps = C.productSignal(sig, l.gtin); return ps && ps.priceMedian ? (l.unitPrice - ps.priceMedian) / ps.priceMedian * 100 : null; }).filter(x => x != null);
  const certQty = sum(lines.filter(l => (l.certificates || []).length).map(l => l.qty));
  const rec = {
    processId: 'PR-' + T.traceId.slice(3), traceId: T.traceId, buyerId: bid, siteId: buyer.site.id, agentId: T.agentId, mandateId: (C.mandateOf(bid) || {}).mandateId, mandateVersion: (C.mandateOf(bid) || {}).version, profileVersion: S().profiles[bid].version, orderIds: order ? [order.orderId] : [],
    createdAt: T.startedAt, closedAt: clock.iso(), channel: T.channel, usageContext: T.usage,
    request: { excerpt: (T.text || '').length > 90 ? (T.text || '').slice(0, 88) + '…' : (T.text || ''), needBy: T.parsed && T.parsed.needBy, lines: (T.lines || []).map(l => ({ lineId: l.lineId, needGroup: l.need.needGroup, category: l.ranked[0] && l.ranked[0].category, kind: l.need.kind, spec: l.need.variants, qty: l.qty, unit: l.unit, constraints: { diet: l.need.diet, allergensExcluded: l.need.excludedAllergens, certs: l.need.certs } })) },
    outcome: { status, planId: plan.planId, planLabel: plan.label, strategy: plan.strategy, tier: lines[0] && lines[0].tier, coveragePct: plan.coverage ? plan.coverage.pct : null, qtyRequested: reqQty, qtyOrdered: ordQty, qtyDelivered: null, overageQty: r2(sum(lines.map(l => l.overage || 0))), totalEUR: order ? order.total : plan.total || 0, eurPerBaseUnit: new Set(lines.map(l => l.unit)).size === 1 && ordQty ? r2(sum(lines.map(l => l.lineTotal)) / ordQty) : null, deltaVsBestPct: best.length && lines.length && new Set(lines.map(l => l.unit)).size === 1 && ordQty ? r1((sum(lines.map(l => l.lineTotal)) / ordQty - Math.min(...best)) / Math.min(...best) * 100) : null, deltaVsMedianPct: medDelta.length ? r1(sum(medDelta) / medDelta.length) : null, needByMet: lines.length ? lines.every(l => !T.parsed || l.deliveryDate <= (T.parsed.needBy || '9999')) : null, plannedDelivery: lines.length ? lines.map(l => l.deliveryDate).sort().pop() : null, actualDelivery: null, splitCount: lines.length, substitutions: subs },
    lines: lines.map(l => ({ gtin: l.gtin, name: l.name, brand: l.brand, category: l.category, supplierId: l.supplierId, qty: l.qty, unit: l.unit, unitPrice: l.unitPrice, lineTotal: l.lineTotal, deliveryDate: l.deliveryDate, certificates: l.certificates || [] })),
    decision: { outcome: T.policy ? T.policy.outcome : null, ruleIds: T.policy ? T.policy.ruleIds : [], approvalRequired: !!ap || (T.policy && T.policy.outcome === 'APPROVE'), approvalLatencyMin: ap ? ap.latencyMin : null, approver: ap ? { id: ap.decidedBy.id, name: ap.decidedBy.name } : null, approverAction: ap ? (ap.status === 'approved' ? 'approve' : ap.status === 'rejected' ? 'reject' : (ap.modifications || []).some(m => m.field === 'cases') ? 'modify' : 'partial') : null, modifications: ap ? ap.modifications : [], manualCorrection: !!(ap && (ap.modifications || []).length), correctionTypes: ap ? [...new Set((ap.modifications || []).map(m => m.field === 'cases' ? 'qty' : 'product'))] : [], manualChoice: T.manualChoice || null, alternativesShown: (T.plans || []).length, chosenRank: plan.label ? +plan.label.slice(1) : null },
    exceptions: { offersRequoted: T.exceptions.offersRequoted, priceChanged: T.exceptions.priceChanged, insufficientStock: T.exceptions.insufficientStock, timeToOrderMin: order ? Math.max(1, Math.round((new Date(order.placedAt) - new Date(T.startedAt)) / 60000)) + (ap ? ap.latencyMin : 0) : null, toolCalls: T.toolCalls },
    feedback: null,
    sustainability: { certifiedSharePct: ordQty ? Math.round(certQty / ordQty * 100) : 0, certificates: [...new Set(lines.flatMap(l => l.certificates || []))] },
    consumption: null, live: true,
  };
  const i = S().processes.findIndex(p => p.processId === rec.processId); if (i >= 0) S().processes[i] = rec; else S().processes.push(rec);
  return rec;
}

// ======================================================= seeded 12-week history
function weekMonday(w) { return addDays('2026-11-09', -7 * w); }
function L(key, qty, price) { const p = BY_KEY[key]; const pr = price || p.unitPrice; return { gtin: p.gtin, name: p.name, brand: p.brand, category: p.category, supplierId: p.origin.supplierId, qty, unit: p.unit, unitPrice: pr, lineTotal: r2(qty * pr), deliveryDate: null, certificates: p.certificates.map(c => c.label) }; }
function mkRec(o) {
  const bid = o.bid, b = S().buyers[bid]; const date = o.date; const lines = o.lines.map(x => { const l = L(x[0], x[1], x[2]); l.deliveryDate = addDays(date, 2); return l; });
  const total = r2(sum(lines.map(l => l.lineTotal))); const q = sum(lines.map(l => l.qty));
  const subs = (o.subs || []).map(([f, t, d]) => { const pf = BY_KEY[f], pt = BY_KEY[t]; return { fromGtin: pf.gtin, toGtin: pt.gtin, fromName: pf.name, toName: pt.name, category: pt.category, changes: (pf.brand !== pt.brand ? ['brand switch'] : []).concat(pf.packSize !== pt.packSize ? ['pack size'] : []).concat(pf.kind !== pt.kind || pf.variant.join() !== pt.variant.join() ? ['spec change'] : []).concat(pf.allergens.join() !== pt.allergens.join() ? ['allergen profile'] : []), priceDeltaPct: d != null ? d : r1((pt.unitPrice - pf.unitPrice) / pf.unitPrice * 100) }; });
  const ap = o.approval; const certQ = sum(lines.filter(l => l.certificates.length).map(l => l.qty));
  const id = 'PR-H' + String(++_hist).padStart(4, '0');
  return {
    processId: id, traceId: 'TR-H' + String(_hist).padStart(4, '0'), buyerId: bid, siteId: b.site.id, agentId: b.agents[0].id, mandateId: b.mandate.mandateId, mandateVersion: 1, profileVersion: 1, orderIds: o.status === 'blocked' || o.status === 'rejected' ? [] : ['ORD-' + (21000 + _hist)],
    createdAt: C.isoTs(date, o.hour || 9, 10), closedAt: C.isoTs(date, (o.hour || 9) + 1, 0), channel: o.channel || 'agent-api', usageContext: o.usage || { type: o.so ? 'standing' : 'adhoc', standingOrderId: o.so || null },
    request: { excerpt: o.text, needBy: addDays(date, 2), lines: lines.map((l, i) => ({ lineId: 'L' + (i + 1), needGroup: C.needGroupId(BY_GTIN[l.gtin]), category: l.category, kind: BY_GTIN[l.gtin].kind, spec: BY_GTIN[l.gtin].variant, qty: l.qty, unit: l.unit, constraints: { diet: [], allergensExcluded: b.mandate.hardExclusions.allergens, certs: [] } })) },
    outcome: { status: o.status || 'delivered', planId: 'PL-H' + _hist, planLabel: o.plan || 'P1', strategy: o.strategy || (subs.length ? 'split_products' : 'single'), tier: o.tier || 'BEST', coveragePct: o.coverage || 100, qtyRequested: o.req || q, qtyOrdered: q, qtyDelivered: o.status === 'blocked' ? 0 : (o.fill != null ? r2(q * o.fill) : q), overageQty: o.over || 0, totalEUR: o.status === 'blocked' ? 0 : total, eurPerBaseUnit: new Set(lines.map(l => l.unit)).size === 1 ? r2(total / q) : null, deltaVsBestPct: o.dBest != null ? o.dBest : (subs.length ? r1(sum(subs.map(s => s.priceDeltaPct)) / subs.length / 2) : 0), deltaVsMedianPct: o.dMed != null ? o.dMed : 0, needByMet: o.late ? false : true, plannedDelivery: addDays(date, 2), actualDelivery: o.late ? addDays(date, 3) : addDays(date, 2), splitCount: lines.length, substitutions: subs },
    lines,
    decision: { outcome: o.outcome || 'AUTO', ruleIds: o.rules || [], approvalRequired: !!ap, approvalLatencyMin: ap ? ap[1] : null, approver: ap ? { id: ap[2].id, name: ap[2].name } : null, approverAction: ap ? ap[0] : null, modifications: o.mods || [], manualCorrection: !!(o.mods && o.mods.length), correctionTypes: o.mods && o.mods.length ? ['qty'] : [], manualChoice: o.choice ? { lineId: 'L1', agentPick: BY_KEY[o.choice[0]].gtin, chosen: BY_KEY[o.choice[1]].gtin, kind: 'preference' } : null, alternativesShown: o.alts || (subs.length ? 3 : 1), chosenRank: 1 },
    exceptions: { offersRequoted: o.requote || 0, priceChanged: o.pc || 0, insufficientStock: o.oos || 0, timeToOrderMin: o.status === 'blocked' ? null : (ap ? ap[1] : 0) + (o.tto || 2), toolCalls: o.calls || 6 },
    feedback: o.status === 'blocked' || o.status === 'rejected' ? null : { onTime: !o.late, lateGtins: o.late ? o.late : null, deliveredQty: o.fill != null ? r2(q * o.fill) : q, qualityIssue: !!o.quality, rating: o.rating || 4 + (_hist % 2), substituteAccepted: subs.length ? (o.accepted !== false) : null, note: o.note || null },
    sustainability: { certifiedSharePct: q ? Math.round(certQ / q * 100) : 0, certificates: [...new Set(lines.flatMap(l => l.certificates))] },
    consumption: o.consumption || null,
  };
}
let _hist = 0;
function eventConsumption(eventType, guests, actual, items, date) {
  // items: [need, key, perCoverPlanned, perCoverUsed, keptFrac, wasteReason, shortage]
  return items.map(([need, key, pcPlan, pcUsed, keptFrac, reason, shortage]) => {
    const p = BY_KEY[key]; const ordered = Math.ceil(pcPlan * guests / p.caseQty - 1e-9) * p.caseQty; const used = Math.min(ordered, r2(pcUsed * actual)); const left = r2(ordered - used); const kept = r2(left * (keptFrac || 0)); const wasted = r2(left - kept);
    return { need, gtin: p.gtin, name: p.name, unit: p.unit, ordered, carriedIn: 0, used, kept, redistributed: 0, wasted, wasteReason: wasted > 0 ? (reason || 'over-ordered') : null, shortage: shortage || 0, emergencyQty: shortage || 0, unitPrice: p.unitPrice, kgPerUnit: p.kgPerUnit, co2eKgPerKg: p.co2eKgPerKg, perCoverPlanned: pcPlan, perCoverActual: r2((used + (shortage || 0)) / actual * 1000) / 1000, caseOverage: r2(ordered - pcPlan * guests) };
  });
}
function seedHistory() {
  _hist = 0; const out = []; const H = 'BUY-POHJOLA', K = 'BUY-KAARI', S3 = 'BUY-KOULU';
  const bh = S().buyers[H], bk = S().buyers[K], bs = S().buyers[S3];
  const laura = bh.approvers[0], jari = bh.approvers[1], anna = bk.approvers[0], pekka = bk.approvers[1], sanna = bs.approvers[0];
  for (let w = 12; w >= 0; w--) {
    const mon = weekMonday(w), tue = addDays(mon, 1), wed = addDays(mon, 2), thu = addDays(mon, 3), fri = addDays(mon, 4), sat = addDays(mon, 5);
    const early = w >= 7;
    // ---- Hotel: standing milk order (Mon)
    if (w >= 1) {
      if ([10, 8, 5, 3, 1].includes(w)) out.push(mkRec({ bid: H, date: mon, so: 'SO-1001', text: 'Weekly standing order SO-1001: lactose-free milk 500 L', lines: [['milk_lf_semi_kaarna', 380], ['milk_lf_semi_maitokaari', 120]], subs: [['milk_lf_semi_kaarna', 'milk_lf_semi_maitokaari']], outcome: 'NOTIFY', rules: ['R4', 'R6'], strategy: 'split_products', alts: 3, accepted: true, oos: 1 }));
      else if ([9, 7].includes(w)) out.push(mkRec({ bid: H, date: mon, so: 'SO-1001', text: 'Weekly standing order SO-1001: lactose-free milk 500 L', lines: [['milk_lf_whole_tunturi', 500]], subs: [['milk_lf_semi_kaarna', 'milk_lf_whole_tunturi']], outcome: 'APPROVE', rules: ['R5'], approval: ['approve', w === 9 ? 26 : 19, laura], strategy: 'substitute', tier: 'GOOD', accepted: false, rating: 2, note: 'Whole milk not suitable for coffee service', oos: 1 }));
      else if (w === 2) out.push(mkRec({ bid: H, date: mon, so: 'SO-1001', text: 'Weekly standing order SO-1001: lactose-free milk 500 L', lines: [['milk_lf_whole_tunturi', 500]], subs: [['milk_lf_semi_kaarna', 'milk_lf_whole_tunturi']], outcome: 'APPROVE', rules: ['R5'], approval: ['approve', 14, laura], strategy: 'substitute', tier: 'GOOD', accepted: true, oos: 1 }));
      else out.push(mkRec({ bid: H, date: mon, so: 'SO-1001', text: 'Weekly standing order SO-1001: lactose-free milk 500 L', lines: [['milk_lf_semi_kaarna', 500]], outcome: 'AUTO' }));
    }
    // ---- Hotel: fish & produce (Thu) — salmon supplier late on some Mondays
    if (w >= 1) out.push(mkRec({ bid: H, date: thu, text: 'Fish & produce for the weekend: salmon, potatoes, cream', lines: [['salmon_fillet', 40], ['potatoes_new', 80], ['cream_whip_kaarna', 36]], outcome: [12, 11, 9].includes(w) ? 'APPROVE' : 'AUTO', rules: [12, 11, 9].includes(w) ? ['R2'] : [], approval: [12, 11, 9].includes(w) ? ['modify', 18, jari] : null, mods: [12, 11, 9].includes(w) ? [{ gtin: BY_KEY.salmon_fillet.gtin, field: 'cases', from: 10, to: 8 }] : null, late: [11, 8, 6, 3].includes(w) ? [BY_KEY.salmon_fillet.gtin] : null, rating: [8, 3].includes(w) ? 3 : 5, fill: [8].includes(w) ? 0.94 : 1 }));
    // ---- Hotel: cream for pastry — Maitokaari LF cream at +5–7 % approved every time
    if ([12, 11, 10, 9, 8, 6, 4, 3, 1].includes(w)) out.push(mkRec({ bid: H, date: tue, text: 'Pastry kitchen: 48 L whipping cream', lines: [['cream_whip_lf_maitokaari', 48, 4.55]], subs: [['cream_whip_kaarna', 'cream_whip_lf_maitokaari', [6.2, 5.8, 6.5, 6.9, 5.5, 6.1, 6.6, 5.9, 6.3][[12, 11, 10, 9, 8, 6, 4, 3, 1].indexOf(w)]]], outcome: 'APPROVE', rules: ['R5'], approval: [[12, 11, 10].includes(w) ? 'modify' : 'approve', [6, 4, 5, 3, 8, 4, 2, 5, 3][[12, 11, 10, 9, 8, 6, 4, 3, 1].indexOf(w)], w % 2 ? jari : laura], mods: [12, 11, 10].includes(w) ? [{ gtin: BY_KEY.cream_whip_lf_maitokaari.gtin, field: 'cases', from: 4, to: 3 }] : null, strategy: 'substitute', tier: 'BETTER', accepted: true }));
    if ([11, 9, 7, 5, 2].includes(w)) out.push(mkRec({ bid: H, date: wed, text: 'Breakfast service: 24 L whipping cream', lines: [['cream_whip_lf_maitokaari', 24]], choice: ['cream_whip_kaarna', 'cream_whip_lf_maitokaari'], outcome: 'AUTO' }));
    // ---- Hotel: events (galas improve after right-sizing in week 5)
    if ([11, 8, 5, 2].includes(w)) {
      const guests = [11, 8].includes(w) ? 160 : 170, actual = guests - 6; const improved = w <= 5;
      const cons = eventConsumption('gala', guests, actual, [
        ['salmon fillet', 'salmon_fillet', 0.099, 0.094, 0, 'prep/plate waste'], ['beef tenderloin', 'beef_tenderloin', 0.222, 0.215, 0.5, 'over-ordered'],
        ['whipping cream', 'cream_whip_kaarna', improved ? 0.125 : 0.155, 0.108, improved ? 0.6 : 0.2, 'over-ordered'], ['bread rolls', 'bread_rolls', improved ? 1.15 : 1.6, 1.08, 0.5, 'over-ordered'],
        ['potatoes', 'potatoes_new', 0.233, 0.21, 0.8, 'over-ordered'], ['dark chocolate', 'choc_dark_kaakaotalo', 0.037, 0.034, 1, null]], sat);
      const lines = cons.map(c => [BY_GTIN[c.gtin].key, c.ordered]);
      out.push(mkRec({ bid: H, date: addDays(sat, -3), text: `Autumn gala dinner for ${guests}`, channel: 'event-autopilot', usage: { type: 'event', eventType: 'gala', name: ['', '', 'Harvest gala', '', '', 'Wine-maker dinner', '', '', 'Corporate gala', '', '', 'Autumn gala'][w], date: sat, guestsExpected: guests, guestsActual: actual }, lines, outcome: improved ? 'NOTIFY' : 'APPROVE', rules: improved ? ['R13'] : ['R2'], approval: improved ? null : ['approve', 42, laura], consumption: cons, rating: 5 }));
    }
    if ([10, 6, 3].includes(w)) {
      const guests = 120, actual = 112;
      const cons = eventConsumption('breakfast', guests, actual, [['lactose-free milk', 'milk_lf_semi_kaarna', 0.25, 0.19, 0.9, 'over-ordered'], ['bread rolls', 'bread_rolls', 1.5, 1.2, 0.6, 'over-ordered'], ['eggs', 'eggs_free_range', 1.5, 1.35, 1, null], ['coffee', 'coffee_dark', 0.015, 0.014, 1, null]], wed);
      out.push(mkRec({ bid: H, date: addDays(wed, -2), text: `Conference breakfast for ${guests}`, channel: 'event-autopilot', usage: { type: 'event', eventType: 'breakfast', name: 'Conference breakfast', date: wed, guestsExpected: guests, guestsActual: actual }, lines: cons.map(c => [BY_GTIN[c.gtin].key, c.ordered]), outcome: 'AUTO', consumption: cons }));
    }
    if (w === 7) {
      const cons = eventConsumption('lunch', 90, 104, [['salmon fillet', 'salmon_fillet', 0.106, 0.106, 0, null, 2.1], ['potatoes', 'potatoes_new', 0.13, 0.13, 0, null], ['whipping cream', 'cream_whip_kaarna', 0.053, 0.05, 0.5, null]], thu);
      out.push(mkRec({ bid: H, date: addDays(thu, -2), text: 'Seminar lunch (salmon soup) for 90', channel: 'event-autopilot', usage: { type: 'event', eventType: 'lunch', name: 'Seminar lunch', date: thu, guestsExpected: 90, guestsActual: 104 }, lines: cons.map(c => [BY_GTIN[c.gtin].key, c.ordered]), outcome: 'AUTO', consumption: cons, note: '14 extra guests — ran out of salmon soup, emergency purchase 2 kg' }));
    }
    // ---- Hospital: weekly oat drink (Fri) — Friday stock-outs → soy
    if (w >= 1) {
      if ([11, 8, 6, 2].includes(w)) out.push(mkRec({ bid: K, date: fri, so: 'SO-2001', text: 'Standing order SO-2001: 240 L oat drink, milk- & nut-free', lines: [['soy_drink_soijanord', 240]], subs: [['oat_drink_kauraco', 'soy_drink_soijanord']], outcome: 'APPROVE', rules: ['R5'], approval: ['approve', [44, 38, 31, 29][[11, 8, 6, 2].indexOf(w)], anna], strategy: 'substitute', tier: 'BETTER', accepted: true, oos: 1 }));
      else if (w === 4) out.push(mkRec({ bid: K, date: fri, so: 'SO-2001', text: 'Standing order SO-2001: 240 L oat drink, milk- & nut-free', lines: [['pea_drink_hernelabs', 120], ['oat_drink_kauraco', 120]], subs: [['oat_drink_kauraco', 'pea_drink_hernelabs']], outcome: 'APPROVE', rules: ['R5', 'R6'], approval: ['approve', 52, pekka], strategy: 'split_products', accepted: false, rating: 2, note: 'Patients disliked the taste of pea drink', oos: 1 }));
      else out.push(mkRec({ bid: K, date: fri, so: 'SO-2001', text: 'Standing order SO-2001: 240 L oat drink, milk- & nut-free', lines: [['oat_drink_kauraco', 240]], outcome: 'AUTO' }));
      out.push(mkRec({ bid: K, date: tue, text: 'Ward kitchen: chicken, peeled potatoes, rice', lines: [['chicken_breast', 60], ['potatoes_peeled', 100], ['rice_jasmine', 50]], outcome: 'AUTO', late: w === 5 ? [BY_KEY.chicken_breast.gtin] : null }));
    }
    // ---- School: weekly skim milk standing order (Mon) with drift in the last weeks
    if (w >= 1) {
      const q = w >= 5 ? 600 : { 4: 640, 3: 700, 2: 730, 1: 740 }[w];
      out.push(mkRec({ bid: S3, date: mon, so: 'SO-3001', text: `Standing order SO-3001: ${q} L skimmed milk`, lines: [['milk_skim_kaarna', q]], outcome: q >= 720 ? 'APPROVE' : 'AUTO', rules: q >= 720 ? ['R10'] : [], approval: q >= 720 ? ['approve', 55 - w * 5, sanna] : null }));
      out.push(mkRec({ bid: S3, date: wed, text: 'Lunch week: gluten-free pasta, penne, carrots', lines: [['pasta_gf_aitta', 16], ['pasta_penne_aitta', 100], ['carrots', 120]], outcome: 'AUTO' }));
      if (w === 9) out.push(mkRec({ bid: S3, date: thu, text: 'Vegetarian Thursday: 40 kg falafel', lines: [['falafel_frozen', 40]], outcome: 'BLOCK', rules: ['R1'], status: 'blocked' }));
      if (w === 12) out.push(mkRec({ bid: S3, date: thu, text: 'Vegetarian Thursday: 40 kg plant mince', lines: [['plant_mince_hernelabs', 40]], outcome: 'NOTIFY', rules: ['R8'] }));
      else if (w < 12 && w !== 9) out.push(mkRec({ bid: S3, date: thu, text: 'Vegetarian Thursday: 40 kg plant mince', lines: [['plant_mince_hernelabs', 40]], outcome: 'AUTO' }));
    }
  }
  // the current week: a board dinner on Tue 10 Nov left reusable stock behind
  const cons = eventConsumption('gala', 60, 58, [['whipping cream', 'cream_whip_kaarna', 0.2, 0.0, 1, null], ['bread rolls', 'bread_rolls', 2.5, 0.0, 1, null], ['dark chocolate', 'choc_dark_kaakaotalo', 0.05, 0.008, 1, null]], '2026-11-10');
  cons[0].used = 0; cons[0].kept = 12; cons[0].ordered = 12; cons[0].wasted = 0; cons[0].perCoverActual = null; cons[1].ordered = 150; cons[1].used = 0; cons[1].kept = 150; cons[1].wasted = 0; cons[1].perCoverActual = null; cons[2].ordered = 2.5; cons[2].used = 0; cons[2].kept = 2.5; cons[2].wasted = 0; cons[2].perCoverActual = null;
  out.push(mkRec({ bid: H, date: '2026-11-08', text: 'Board dinner for 60 (spare stock kept)', channel: 'event-autopilot', usage: { type: 'event', eventType: 'board', name: 'Board dinner', date: '2026-11-10', guestsExpected: 60, guestsActual: 58 }, lines: [['cream_whip_kaarna', 12], ['bread_rolls', 150], ['choc_dark_kaakaotalo', 2.5]], outcome: 'AUTO', consumption: cons }));
  S().leftovers.push(
    { leftoverId: 'LO-0001', buyerId: H, siteId: bh.site.id, gtin: BY_KEY.cream_whip_kaarna.gtin, qty: 12, bestBefore: '2026-11-24', sourceLabel: 'Board dinner (Tue 10.11.)', status: 'available' },
    { leftoverId: 'LO-0002', buyerId: H, siteId: bh.site.id, gtin: BY_KEY.bread_rolls.gtin, qty: 150, bestBefore: '2027-01-15', sourceLabel: 'Board dinner (frozen)', status: 'available' },
    { leftoverId: 'LO-0003', buyerId: H, siteId: bh.site.id, gtin: BY_KEY.choc_dark_kaakaotalo.gtin, qty: 2.5, bestBefore: '2027-05-01', sourceLabel: 'Board dinner', status: 'available' },
    { leftoverId: 'LO-0004', buyerId: H, siteId: bh.site.id, gtin: BY_KEY.milk_lf_semi_kaarna.gtin, qty: 30, bestBefore: '2026-11-17', sourceLabel: 'Breakfast service', status: 'available' });
  out.sort((a, b) => a.createdAt < b.createdAt ? -1 : 1);
  return out;
}
async function seedAudit(recs) {
  for (const r of recs) {
    const a = 'agent:' + r.agentId.split(':')[1];
    await audit({ ts: r.createdAt, traceId: r.traceId, actor: a, action: 'plan', buyerId: r.buyerId, reason: r.request.excerpt });
    await audit({ ts: r.createdAt, traceId: r.traceId, actor: 'system:policy', action: 'policy_decision', buyerId: r.buyerId, decision: r.decision.outcome, ruleIds: r.decision.ruleIds, reason: r.decision.ruleIds.length ? r.decision.ruleIds.map(id => id + ' ' + C.RULES[id].title).join('; ') : 'No rule fired.' });
    if (r.decision.approver) await audit({ ts: r.closedAt, traceId: r.traceId, actor: 'human:' + r.decision.approver.name, action: r.decision.approverAction === 'reject' ? 'rejected' : 'approved', buyerId: r.buyerId, decision: r.decision.approverAction.toUpperCase(), reason: `after ${r.decision.approvalLatencyMin} min` });
    if (r.orderIds.length) await audit({ ts: r.closedAt, traceId: r.traceId, actor: 'system:gateway', action: 'order_placed', buyerId: r.buyerId, refs: { orderId: r.orderIds[0] }, reason: `${money(r.outcome.totalEUR)}` });
    if (r.consumption) await audit({ ts: r.closedAt, traceId: r.traceId, actor: 'human:Jari Lehtonen', action: 'reconciliation_recorded', buyerId: r.buyerId, reason: `utilisation ${Math.round(utilisation(r.consumption) * 100)}%` });
  }
}

// ======================================================= insights: KPIs, recommendations, waste
const closedRecs = bid => S().processes.filter(r => r.buyerId === bid);
const weekOf = iso => { const d = iso.slice(0, 10); let m = d; while (C.weekday(m) !== 0) m = addDays(m, -1); return m; };
function kpis(bid) {
  const recs = closedRecs(bid); const weeks = []; for (let w = 11; w >= 0; w--) weeks.push(weekMonday(w));
  const by = Object.fromEntries(weeks.map(w => [w, []])); for (const r of recs) { const wk = weekOf(r.createdAt); if (by[wk]) by[wk].push(r); }
  const metric = rs => {
    const decided = rs.filter(r => r.decision.outcome); const auton = decided.filter(r => ['AUTO', 'NOTIFY'].includes(r.decision.outcome));
    const fb = rs.filter(r => r.feedback); const subs = rs.flatMap(r => (r.outcome.substitutions || []).map(() => r)).filter(r => r.feedback && r.feedback.substituteAccepted != null);
    const lat = rs.map(r => r.decision.approvalLatencyMin).filter(x => x != null);
    const qty = sum(rs.map(r => r.outcome.qtyOrdered || 0)); const cert = sum(rs.map(r => (r.outcome.qtyOrdered || 0) * (r.sustainability.certifiedSharePct || 0) / 100));
    const tto = rs.map(r => r.exceptions.timeToOrderMin).filter(x => x != null);
    const corr = rs.filter(r => r.decision.manualCorrection).length;
    const pvm = rs.map(r => r.outcome.deltaVsMedianPct).filter(x => x != null);
    const exc = rs.map(r => (r.exceptions.offersRequoted || 0) + (r.exceptions.priceChanged || 0) + (r.exceptions.insufficientStock || 0)); const ord = rs.filter(r => r.orderIds.length); const cons = rs.filter(r => r.consumption).flatMap(r => r.consumption); const consO = sum(cons.map(c => c.ordered + (c.carriedIn || 0)));
    return { topChoiceRate: ord.length ? ord.filter(r => r.decision.chosenRank === 1).length / ord.length : null, exceptionsPerProcess: rs.length ? sum(exc) / rs.length : null, coverage: rs.filter(r => r.outcome.coveragePct != null).length ? sum(rs.filter(r => r.outcome.coveragePct != null).map(r => r.outcome.coveragePct / 100)) / rs.filter(r => r.outcome.coveragePct != null).length : null, roundingOverage: sum(rs.map(r => r.outcome.overageQty || 0)), utilisation: consO ? sum(cons.map(c => c.used)) / consO : null, wasteEUR: cons.length ? sum(cons.map(c => c.wasted * c.unitPrice)) : null, wasteRate: consO ? sum(cons.map(c => c.wasted)) / consO : null, n: rs.length, autonomousRate: decided.length ? auton.length / decided.length : null, manualCorrectionRate: rs.length ? corr / rs.length : null, needByHitRate: fb.length ? fb.filter(r => r.feedback.onTime).length / fb.length : null, fillRate: fb.length ? sum(fb.map(r => Math.min(1, (r.feedback.deliveredQty || 0) / (r.outcome.qtyOrdered || 1)))) / fb.length : null, timeToOrderMin: tto.length ? sum(tto) / tto.length : null, approvalP50: median(lat), approvalP90: quant(lat, .9), priceVsMedianPct: pvm.length ? sum(pvm) / pvm.length : null, substitutionAcceptance: subs.length ? subs.filter(r => r.feedback.substituteAccepted).length / subs.length : null, certifiedShare: qty ? cert / qty : null, spend: sum(rs.map(r => r.outcome.totalEUR || 0)) };
  };
  const series = weeks.map(w => ({ week: w, ...metric(by[w]) }));
  const cur = metric(recs.filter(r => r.createdAt.slice(0, 10) >= weekMonday(3))), prev = metric(recs.filter(r => r.createdAt.slice(0, 10) >= weekMonday(7) && r.createdAt.slice(0, 10) < weekMonday(3)));
  const b = S().buyers[bid]; const m = C.mandateOf(bid);
  return { series, current: cur, previous: prev, all: metric(recs), budget: { mtd: b.monthToDateEUR, perMonth: m ? m.limits.perMonthEUR : null } };
}
function recommendations(bid) {
  const sig = C.computeSignals(bid); const m = C.mandateOf(bid); const prof = S().profiles[bid]; const b = S().buyers[bid]; const recs = []; const applied = S().recs[bid] || {};
  const per = sig.period.from ? `${dayLabel(sig.period.from)} – ${dayLabel(sig.period.to)}` : '';
  const add = r => { r.status = applied[r.id] ? 'applied' : 'open'; recs.push(r); };
  // 1 silent in-tolerance swaps for a category (NOTIFY R4 acknowledged)
  const r4 = sig.rules.find(r => r.ruleId === 'R4'); if (r4 && m) for (const [cat, n] of Object.entries(r4.categories)) { if (n >= 4 && r4.acknowledged / r4.fired >= 0.9 && !(m.substitution.silentCategories || []).includes(cat)) add({ id: 'silent-' + cat, kind: 'mandate', priority: 1, title: `Let in-tolerance ${cat} swaps run silently`, detail: `You acknowledged ${r4.acknowledged} of ${r4.fired} brand-switch notifications (R4) without changing anything, and the kitchen accepted every swap.`, impact: `${r4.fired} past orders would have been fully autonomous (AUTO instead of NOTIFY), no notification to review.`, evidence: { n: r4.fired, period: per, processIds: r4.processIds.slice(-8) }, action: { type: 'mandate', label: 'Update mandate', patch: { 'substitution.silentCategories': [...(m.substitution.silentCategories || []), cat] } } }); }
  // 2 raise price tolerance (R5 approvals at small deltas)
  const r5 = sig.rules.find(r => r.ruleId === 'R5'); if (r5 && m) { const small = S().processes.filter(r => r.buyerId === bid && r.decision.ruleIds.includes('R5') && r.outcome.substitutions.length && r.outcome.substitutions.every(s => s.priceDeltaPct > m.substitution.maxPriceDeltaPct && s.priceDeltaPct <= 7 && s.changes.every(c => !['allergen profile', 'category change'].includes(c)))); const ok = small.filter(r => r.decision.approverAction === 'approve'); if (small.length >= 4 && ok.length / small.length >= 0.9 && m.substitution.maxPriceDeltaPct < 7) { const lat = median(small.map(r => r.decision.approvalLatencyMin)); add({ id: 'delta-7', kind: 'mandate', priority: 2, title: `Raise substitution tolerance to 7 %`, detail: `${ok.length} of ${small.length} approvals for same-spec swaps priced ${m.substitution.maxPriceDeltaPct}–7 % above the usual product were approved unchanged (median ${Math.round(lat)} min).`, impact: `Would have auto-approved ${ok.length} of ${small.length} approvals, saving ~${Math.round(sum(small.map(r => r.decision.approvalLatencyMin)))} min of approver time.`, evidence: { n: small.length, period: per, processIds: small.map(r => r.processId).slice(-8) }, action: { type: 'mandate', label: 'Update mandate', patch: { 'substitution.maxPriceDeltaPct': 7 } } }); } }
  // 3 block repeatedly rejected swaps
  for (const p of sig.substitutionPairs) if (p.rejected >= 2 && m && !(m.substitution.blockedPairs || []).some(x => x[0] === p.fromGtin && x[1] === p.toGtin)) add({ id: 'block-' + p.toGtin, kind: 'mandate', priority: 3, title: `Stop proposing ${BY_GTIN[p.toGtin].brand} ${BY_GTIN[p.toGtin].kind === 'milk' ? 'whole milk' : ''} as a swap`.replace(/\s+/g, ' '), detail: `The kitchen rejected ${p.toName} as a substitute for ${p.fromName} ${p.rejected} of ${p.n} times.`, impact: 'The agent will choose a split or a later delivery instead of this swap.', evidence: { n: p.n, period: per, processIds: p.processIds }, action: { type: 'mandate', label: 'Block this swap', patch: { 'substitution.blockedPairs': [...(m.substitution.blockedPairs || []), [p.fromGtin, p.toGtin]] } } });
  // 4 late supplier
  for (const p of sig.products) if (p.onTimeN >= 6 && p.onTimeRate < 0.8) { const alt = C.P.find(x => x.kind === BY_GTIN[p.gtin].kind && x.gtin !== p.gtin && x.origin.supplierId !== p.supplierId); add({ id: 'late-' + p.gtin, kind: 'preferences', priority: 2, title: `${p.brand} delivered late ${p.onTimeN - p.onTime} of ${p.onTimeN} times`, detail: `${p.name} (supplier ${p.supplierId}) arrived on time only ${Math.round(p.onTimeRate * 100)} % of the time for you. ${alt ? alt.name + ' (' + alt.brand + ') is on time ' + Math.round(alt.onTimeRate * 100) + ' % across Valio Aimo.' : ''}`, impact: 'Ranking already uses your experienced on-time rate; also preferring the alternative lifts the weekend need-by hit rate.', evidence: { n: p.onTimeN, period: per, processIds: p.processIds.slice(-8) }, action: { type: 'preferences', label: 'Prefer the alternative', patch: { addFilter: { field: 'supplier', op: 'exclude', values: [p.supplierId], mode: 'preferred' } } }, context: 'Late deliveries clustered on ' + 'weekend deliveries: ' + [...new Set(S().processes.filter(r => r.buyerId === bid && r.feedback && r.feedback.lateGtins && r.feedback.lateGtins.includes(p.gtin)).map(r => dayContext(b.site.id, addDays(r.createdAt.slice(0, 10), 2)).text.split(' · ').slice(0, 1).concat(dayContext(b.site.id, addDays(r.createdAt.slice(0, 10), 2)).tempC <= 2 ? ['near-freezing'] : []).join(' ')))].join('; ') }); }
  // 5 favourites from manual choices
  for (const c of sig.manualChoices) if (c.n >= 3 && !prof.favourites.includes(c.chosen)) add({ id: 'fav-' + c.chosen, kind: 'preferences', priority: 3, title: `Add ${c.chosenBrand} to favourites?`, detail: `You chose ${c.chosenName} over the agent's pick (${c.agentPickName}) ${c.n} times. These were preference choices, not error corrections.`, impact: 'The agent will rank it first when available (+0.05 favourite bonus) and stop asking you to switch.', evidence: { n: c.n, period: per, processIds: c.processIds }, action: { type: 'preferences', label: 'Add to favourites', patch: { favourite: c.chosen } } });
  // 6 standing-order drift
  for (const so of b.standingOrders) { const g = BY_KEY[so.productKey].gtin; const rs = S().processes.filter(r => r.buyerId === bid && r.usageContext && r.usageContext.standingOrderId === so.id).slice(-4); const qs = rs.map(r => r.outcome.qtyOrdered); const md = median(qs); if (qs.length >= 3 && md > so.qty * 1.15) add({ id: 'so-' + so.id, kind: 'standing', priority: 1, title: `Update standing order ${so.id} to ${fq(Math.round(md / 10) * 10, so.unit)}`, detail: `The last ${qs.length} weeks averaged ${fq(md, so.unit)} vs the standing quantity ${fq(so.qty, so.unit)} (+${Math.round((md / so.qty - 1) * 100)} %). Each renewal is paused for approval by R10.`, impact: `Removes ${rs.filter(r => r.decision.ruleIds.includes('R10')).length} weekly approvals (median ${Math.round(median(rs.map(r => r.decision.approvalLatencyMin).filter(x => x != null)) || 0)} min each).`, evidence: { n: qs.length, period: per, processIds: rs.map(r => r.processId) }, action: { type: 'standing', label: 'Update standing order', patch: { soId: so.id, qty: Math.round(md / 10) * 10 } }, context: dayContext(b.site.id, rs[rs.length - 1].createdAt.slice(0, 10)).text }); }
  // 7 stock-outs on a weekday → order earlier
  const oos = S().processes.filter(r => r.buyerId === bid && r.exceptions.insufficientStock && r.usageContext && r.usageContext.standingOrderId);
  const byDay = {}; for (const r of oos) { const k = r.usageContext.standingOrderId + '|' + C.weekday(r.createdAt.slice(0, 10)); (byDay[k] = byDay[k] || []).push(r); }
  for (const [k, rs] of Object.entries(byDay)) { const [soId, wd] = k.split('|'); const so = b.standingOrders.find(s => s.id === soId); if (rs.length >= 4 && so && so.weekday === 'Friday' && so.weekday === ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][+wd]) add({ id: 'cutoff-' + soId, kind: 'standing', priority: 1, title: `Order ${BY_KEY[so.productKey].name.split(',')[0].toLowerCase()} by Thursday's cut-off`, detail: `${so.id} hit stock-outs on ${['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays'][+wd]} ${rs.length} of 12 weeks, each forcing a substitute and an approval.`, impact: `Moving the standing order one day earlier avoids ~${rs.length} substitutions per quarter and their approvals (median ${Math.round(median(rs.map(r => r.decision.approvalLatencyMin).filter(x => x != null)) || 0)} min).`, evidence: { n: rs.length, period: per, processIds: rs.map(r => r.processId) }, action: { type: 'standing', label: 'Move to Thursday', patch: { soId, weekday: 'Thursday' } }, context: 'Fridays: ' + dayContext(b.site.id, rs[rs.length - 1].createdAt.slice(0, 10)).text + ' — weekend admissions peak while supplier stock is lowest' }); }
  // 8 event right-sizing (informational; the Autopilot applies it with evidence)
  for (const pc of sig.perCover) if (pc.n >= 2 && pc.perCoverPlannedMedian && pc.perCoverActualMedian / pc.perCoverPlannedMedian < 0.88) add({ id: 'pc-' + pc.eventType + '-' + pc.need, kind: 'events', priority: 4, title: `${pc.eventType === 'gala' ? 'Galas' : pc.eventType.charAt(0).toUpperCase() + pc.eventType.slice(1) + 's'} use ${fq(pc.perCoverActualMedian, pc.unit)}/guest of ${pc.need}, not ${fq(pc.perCoverPlannedMedian, pc.unit)}`, detail: `Measured over the last ${Math.min(3, pc.n)} reconciled events (${pc.dates.slice(-3).map(d => dayLabel(d)).join(', ')}).`, impact: 'Event Autopilot already right-sizes this line next time and flags the change under R13.', evidence: { n: pc.n, period: per, processIds: pc.processIds.slice(-3) }, action: { type: 'info', label: 'Applied by Autopilot' }, context: pc.eventType === 'breakfast' ? 'Conference breakfasts run at ~93% of booked covers (no-shows)' : 'Plated galas: actual covers ran 4–6 below expected' });
  return recs.sort((a, b) => a.priority - b.priority);
}
async function applyRecommendation(bid, recId, byName) {
  const rec = recommendations(bid).find(r => r.id === recId); if (!rec || rec.status === 'applied') return null;
  const b = S().buyers[bid]; const who = b.approvers.find(a => a.name === byName) || b.admin;
  if (rec.action.type === 'mandate') {
    const m = clone(C.mandateOf(bid)); for (const [path, v] of Object.entries(rec.action.patch)) { const [a, k] = path.split('.'); m[a][k] = v; }
    m.version += 1; delete m.issuedBy; delete m.validFrom; delete m.validUntil; delete m.type; delete m.buyerId; delete m.preferenceProfile;
    const signed = await C.signMandate(bid, m, who); await C.registerMandate(bid, signed, `v${m.version}: ${rec.title} (recommendation ${rec.id}, evidence n=${rec.evidence.n})`, who.name);
  } else if (rec.action.type === 'preferences') {
    const pf = S().profiles[bid]; if (rec.action.patch.favourite) pf.favourites.push(rec.action.patch.favourite); if (rec.action.patch.addFilter) pf.org.filters.push(rec.action.patch.addFilter); pf.version += 1;
    await audit({ actor: 'human:' + who.name, action: 'preferences_updated', buyerId: bid, refs: { profileId: pf.profileId, version: pf.version }, reason: `v${pf.version}: ${rec.title}` });
  } else if (rec.action.type === 'standing') {
    const so = b.standingOrders.find(s => s.id === rec.action.patch.soId); if (rec.action.patch.qty) so.qty = rec.action.patch.qty; if (rec.action.patch.weekday) so.weekday = rec.action.patch.weekday;
    if (rec.action.patch.qty) { const g = BY_KEY[so.productKey].key; const h = b.history[g]; if (h) { h.splice(0, 4); h.push(so.qty, so.qty, so.qty, so.qty); } }
  }
  S().recs[bid] = S().recs[bid] || {}; S().recs[bid][recId] = clock.iso();
  await audit({ actor: 'human:' + who.name, action: 'recommendation_applied', buyerId: bid, refs: { recommendationId: recId }, reason: rec.title + ' — evidence: ' + rec.evidence.n + ' processes, ' + rec.evidence.period });
  return rec;
}
// ---- consumption & waste
const utilisation = cons => { const o = sum(cons.map(c => c.ordered + (c.carriedIn || 0))); return o ? sum(cons.map(c => Math.min(c.used, c.ordered + (c.carriedIn || 0)))) / o : 1; };
const lineKg = (c, q) => q * (c.kgPerUnit || 1);
function eventMetrics(cons) {
  const val = (c, q) => q * c.unitPrice;
  const t = { orderedEUR: sum(cons.map(c => val(c, c.ordered))), usedEUR: sum(cons.map(c => val(c, c.used))), reusedEUR: sum(cons.map(c => val(c, c.kept + c.redistributed))), wastedEUR: sum(cons.map(c => val(c, c.wasted))), wastedKg: sum(cons.map(c => lineKg(c, c.wasted))), reusedKg: sum(cons.map(c => lineKg(c, c.kept + c.redistributed))), co2eKg: sum(cons.map(c => lineKg(c, c.wasted) * (c.co2eKgPerKg || 1))), shortages: cons.filter(c => c.shortage > 0).length, caseOverageEUR: sum(cons.map(c => val(c, Math.max(0, c.caseOverage || 0)))) };
  t.utilisation = utilisation(cons); t.wasteRate = t.orderedEUR ? t.wastedEUR / t.orderedEUR : 0; t.perfect = t.utilisation >= 0.95 && !t.shortages;
  const fa = cons.filter(c => c.perCoverPlanned && c.perCoverActual); t.mape = fa.length ? sum(fa.map(c => Math.abs(c.perCoverPlanned - c.perCoverActual) / c.perCoverActual)) / fa.length : null;
  return t;
}
function wasteInsights(bid) {
  const recs = S().processes.filter(r => (!bid || r.buyerId === bid) && r.consumption && r.consumption.some(c => c.perCoverActual != null || c.used > 0));
  const rows = recs.map(r => ({ processId: r.processId, date: (r.usageContext.date || r.createdAt).slice(0, 10), name: r.usageContext.name || r.request.excerpt, eventType: r.usageContext.eventType, guests: r.usageContext.guestsActual, m: eventMetrics(r.consumption), cons: r.consumption, live: r.live })).sort((a, b) => a.date < b.date ? -1 : 1);
  const prod = {}; for (const r of rows) for (const c of r.cons) { const e = prod[c.gtin] = prod[c.gtin] || { gtin: c.gtin, name: c.name, unit: c.unit, wasted: 0, wastedEUR: 0, ordered: 0, n: 0 }; e.wasted += c.wasted; e.wastedEUR += c.wasted * c.unitPrice; e.ordered += c.ordered; e.n++; }
  const savings = rows.filter(r => r.eventType === 'gala' && r.date >= weekMonday(5)).map(r => sum(r.cons.filter(c => /cream|roll/i.test(c.name)).map(c => ((c.need === 'whipping cream' ? 0.155 : c.need === 'bread rolls' ? 1.6 : c.perCoverPlanned) - c.perCoverPlanned) * (r.guests || 160) * c.unitPrice)));
  const shortages = rows.flatMap(r => r.cons.filter(c => c.shortage > 0).map(c => ({ date: r.date, event: r.name, name: c.name, shortage: c.shortage, unit: c.unit, emergencyQty: c.emergencyQty })));
  const leftovers = S().leftovers.filter(l => (!bid || l.buyerId === bid) && l.status === 'available').map(l => ({ ...l, name: BY_GTIN[l.gtin].name, unit: BY_GTIN[l.gtin].unit, daysLeft: Math.round((new Date(l.bestBefore) - new Date(clock.today())) / 864e5) })).sort((a, b) => a.daysLeft - b.daysLeft);
  return { rows, topWasted: Object.values(prod).filter(p => p.wasted > 0).sort((a, b) => b.wastedEUR - a.wastedEUR).slice(0, 6), shortages, savingsEUR: sum(savings.filter(x => x > 0)), leftovers, totals: { wastedEUR: sum(rows.map(r => r.m.wastedEUR)), wastedKg: sum(rows.map(r => r.m.wastedKg)), co2eKg: sum(rows.map(r => r.m.co2eKg)), reusedEUR: sum(rows.map(r => r.m.reusedEUR)), utilisation: rows.length ? sum(rows.map(r => r.m.utilisation)) / rows.length : null } };
}


// ======================================================= outcome labels (label_definition v1) & day context (site_day_context)
const LABEL_DEFS = Object.fromEntries(((C.D.seed || {}).label_definition || []).map(l => [l.label_code, l]));
const METRIC_DEFS = Object.fromEntries(((C.D.seed || {}).metric_definition || []).map(m => [m.metric_code, m]));
function lineUsageLabel(c) { const avail = c.ordered + (c.carriedIn || 0); if (!avail) return null; if (c.shortage > 0 || c.emergencyQty > 0) return 'under_ordered'; if ((c.wasted + c.kept) / avail > 0.10) return 'over_ordered'; const u = c.used / avail; if (u >= 0.9 && u <= 1.0001) return 'right_sized'; return null; }
function labelsFor(r) {
  const L = []; const d = r.decision || {}, x = r.exceptions || {}, fb = r.feedback;
  if (r.consumption && r.consumption.some(c => c.used > 0 || c.wasted > 0)) { const m = eventMetrics(r.consumption); if (m.perfect) L.push('perfect_order'); const ll = r.consumption.map(lineUsageLabel); for (const k of ['over_ordered', 'under_ordered']) if (ll.includes(k)) L.push(k); if (!m.perfect && ll.length && ll.every(k => k === 'right_sized')) L.push('right_sized'); }
  if (['AUTO', 'NOTIFY'].includes(d.outcome)) L.push('autonomous');
  if (d.manualCorrection) L.push('corrected');
  if (d.chosenRank === 1 && r.orderIds && r.orderIds.length) L.push('top_choice');
  if (!(x.offersRequoted || x.priceChanged || x.insufficientStock)) L.push('exception_free');
  if (fb && fb.onTime === false) L.push('late_delivery');
  if (r.outcome && r.outcome.deltaVsMedianPct != null && r.outcome.deltaVsMedianPct <= 0 && r.orderIds && r.orderIds.length) L.push('price_good');
  if (r.outcome && r.outcome.substitutions.length && fb) { if (fb.substituteAccepted === false || (fb.rating && fb.rating <= 2)) L.push('bad_substitute'); else if (fb.substituteAccepted && (fb.rating || 0) >= 4) L.push('good_substitute'); }
  return L;
}
const HOLIDAYS = { '2026-10-31': 'All Saints’ Day', '2026-11-08': 'Father’s Day', '2026-12-06': 'Independence Day', '2026-12-24': 'Christmas Eve' };
function dayContext(siteId, date) {
  const wd = C.weekday(date); const seed = +date.replace(/-/g, '') % 97; const rng = C.mulberry32(seed + siteId.length);
  const ctx = { date, weekday: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][wd], holiday: HOLIDAYS[date] || null };
  const month = +date.slice(5, 7); ctx.tempC = Math.round((month >= 11 ? 1.5 : month === 10 ? 6 : 11) + (rng() - 0.5) * 6); ctx.rainPct = Math.round(35 + rng() * 50);
  if (siteId.includes('POH')) { ctx.occupancyPct = Math.round([62, 66, 70, 74, 88, 93, 71][wd] + (rng() - 0.5) * 6); if (date >= '2026-11-19' && date <= '2026-11-21') ctx.localEvent = 'Trade fair at the convention centre (≈ 9,000 visitors)'; }
  if (siteId.includes('KAARI')) ctx.occupancyPct = Math.round([92, 93, 94, 95, 97, 90, 89][wd] + (rng() - 0.5) * 3);
  if (siteId.includes('KOULU')) { ctx.covers = date >= '2026-10-19' ? 805 : 740; ctx.note = date >= '2026-10-19' ? 'New preparatory class joined on 19.10. (+65 pupils)' : null; }
  ctx.text = [ctx.weekday + (ctx.holiday ? ' · ' + ctx.holiday : ''), ctx.occupancyPct ? `occupancy ${ctx.occupancyPct}%` : null, ctx.covers ? `${ctx.covers} pupils` : null, `${ctx.tempC}°C, rain ${ctx.rainPct}%`, ctx.localEvent, ctx.note].filter(Boolean).join(' · ');
  return ctx;
}

// ======================================================= Event Autopilot
const NUMW = { one: 1, a: 1, an: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, twelve: 12, yksi: 1, kaksi: 2, kolme: 3, neljä: 4, viisi: 5, kuusi: 6, seitsemän: 7, kahdeksan: 8, yhdeksän: 9, kymmenen: 10 };
const ALLERGY_WORDS = { nut: 'nuts', nuts: 'nuts', 'tree nut': 'nuts', peanut: 'peanuts', egg: 'eggs', fish: 'fish', shellfish: 'crustaceans', crustacean: 'crustaceans', milk: 'milk', dairy: 'milk', sesame: 'sesame', soy: 'soybeans', celery: 'celery', mustard: 'mustard', gluten: 'cereals_gluten', pähkinä: 'nuts', maapähkinä: 'peanuts', kala: 'fish', kananmuna: 'eggs', maito: 'milk', seesami: 'sesame' };
const EVENT_TYPES = [[/pikkujoulu|christmas party|little christmas/i, 'christmas_party', 'Pikkujoulut (Christmas party)', 'buffet'], [/gala/i, 'gala', 'Gala dinner', 'plated'], [/wedding|häät/i, 'wedding', 'Wedding dinner', 'plated'], [/conference|seminar|seminaari/i, 'conference', 'Conference', 'buffet'], [/breakfast|aamiainen/i, 'breakfast', 'Breakfast', 'buffet'], [/lunch|lounas/i, 'lunch', 'Lunch', 'buffet'], [/birthday|syntymäpäiv/i, 'birthday', 'Birthday party', 'buffet'], [/dinner|illallinen/i, 'dinner', 'Dinner', 'plated']];
function parseBrief(text) {
  const today = clock.today(); const t = text.toLowerCase(); const assumptions = []; let question = null;
  const et = EVENT_TYPES.find(e => e[0].test(text)) || [null, 'event', 'Event', 'buffet'];
  const nameM = text.match(/^\s*([A-ZÅÄÖ][^,:.\d]{2,40}?)(?=\s+(?:on|for|this|next|ensi|tänä|maanantaina|tiistaina|keskiviikkona|torstaina|perjantaina|lauantaina|sunnuntaina|huomenna|\d)|[,:])/);
  const name = nameM ? nameM[1].trim() : et[2];
  const nd = parseDate(text, today); let date = nd ? nd.date : null;
  if (!date) { question = 'Which date is the event?'; date = addDays(today, 7); assumptions.push(`Date not stated — assumed ${dayLabel(date)}; please confirm.`); }
  const gm = text.match(/(\d[\d ,]*)\s*(guests|people|persons|pax|covers|hengelle|henkeä|henkilölle|henkilöä|vieraalle|vierasta|hlölle|hlö)/i) || text.match(/for\s+(\d+)/i);
  let guests = gm ? parseInt(gm[1].replace(/[ ,]/g, ''), 10) : null;
  if (!guests) { if (!question) question = 'How many guests?'; guests = 100; assumptions.push('Guest count not stated — assumed 100.'); }
  let style = /buffet|seisova|noutopöytä/i.test(text) ? 'buffet' : /plated|seated|served|pöytiin/i.test(text) ? 'plated' : et[3];
  if (!/buffet|seisova|noutopöytä|plated|seated|served/i.test(text)) assumptions.push(`Service style assumed ${style} for a ${et[2].toLowerCase()}.`);
  const num = s => NUMW[s] || parseInt(s, 10);
  const diet = { vegan: 0, vegetarian: 0, gluten_free: 0, lactose_free: 0 }; const allergies = {}; let m;
  const dre = /(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|yksi|kaksi|kolme|neljä|viisi|kuusi|seitsemän|kahdeksan|yhdeksän|kymmenen)\s+(vegans?|vegaania|vegaanit|vegaani|vegetarians?|kasvissyöjää|kasvissyöjä|gluten[- ]free|gluteenitonta|gluteenittomia|gluteeniton|coeliacs?|keliaakikkoa|keliaakikko|lactose[- ]free|laktoositonta|laktoosittomia|laktoositon)/gi;
  while ((m = dre.exec(text))) { const n = num(m[1].toLowerCase()); const w = m[2].toLowerCase(); if (/vegan|vegaani/.test(w)) diet.vegan += n; else if (/vegetarian|kasvis/.test(w)) diet.vegetarian += n; else if (/gluten|coeliac|keliaak|glutee/.test(w)) diet.gluten_free += n; else diet.lactose_free += n; }
  const are = /(\d+|one|a|an|two|three|four|five|yksi|kaksi|kolme|neljä|viisi)?\s*(tree nut|peanut|nut|egg|fish|shellfish|crustacean|milk|dairy|sesame|soy|celery|mustard|gluten|maapähkinä|pähkinä|kala|kananmuna|maito|seesami)[- ]?(?:allerg(?:y|ies|ic)|allergia|allergikkoa|allergikko|allerginen)/gi;
  while ((m = are.exec(text))) { const a = ALLERGY_WORDS[m[2].toLowerCase()]; allergies[a] = (allergies[a] || 0) + (m[1] ? num(m[1].toLowerCase()) || 1 : 1); }
  // dishes: match recipe aliases, longest first; remember unmatched menu words
  const services = []; const dishes = []; const used = new Set();
  const breakfastM = text.match(/breakfast for (\d+)([^.,;]*)/i) || text.match(/aamiainen (\d+)/i);
  const mainText = breakfastM ? text.replace(breakfastM[0], ' ') : text;
  const aliasList = RECIPES.flatMap(r => r.aliases.map(a => [a, r])).sort((a, b) => b[0].length - a[0].length);
  let rest = ' ' + mainText.toLowerCase() + ' ';
  for (const [alias, r] of aliasList) { if (r.id === 'breakfast_buffet' && breakfastM) continue; const re = new RegExp('[^a-zåäö]' + alias.replace(/[-]/g, '[- ]') + '(?:[a-zåäö]{0,3})(?=[^a-zåäö])', 'i'); if (re.test(rest)) { if (!used.has(r.id)) { used.add(r.id); dishes.push({ recipeId: r.id, name: r.name, said: alias, match: 'exact' }); } if (alias !== 'laatikot' && alias !== 'laatikko') rest = rest.replace(re, ' '); } }
  if (/laatik/.test(t)) { for (const id of ['lanttulaatikko', 'porkkanalaatikko']) if (!used.has(id)) { used.add(id); dishes.push({ recipeId: id, name: RBY[id].name, said: 'laatikot', match: 'expanded' }); } }
  // unknown dish words after a colon / list → nearest template
  const listPart = (mainText.split(/[:]/)[1] || '').split(/[.]/)[0];
  for (const raw of listPart.split(/,|\band\b|\bwith\b|\bja\b/)) { const w = raw.trim().toLowerCase(); if (!w || w.length < 4 || /\d|guest|vegan|gluten|allerg|morning|aamu/.test(w)) continue; if (aliasList.some(([a]) => w.includes(a))) continue; const words = w.split(/\s+/); const best = RECIPES.map(r => [r, words.filter(x => x.length > 3 && (r.name.toLowerCase().includes(x) || r.aliases.some(a => a.includes(x)))).length]).sort((a, b) => b[1] - a[1])[0]; if (best && best[1] > 0 && !used.has(best[0].id)) { used.add(best[0].id); dishes.push({ recipeId: best[0].id, name: best[0].name, said: w, match: 'nearest' }); assumptions.push(`"${w}" is not in the recipe book — mapped to the nearest template "${best[0].name}". Check it.`); } else if (w.split(' ').length <= 4) assumptions.push(`"${w}" not recognised — skipped.`); }
  const CO = { starter: 0, snack: 1, main: 2, side: 3, dessert: 4, drinks: 5, breakfast: 6 }; dishes.sort((a, b) => (CO[RBY[a.recipeId].course] ?? 9) - (CO[RBY[b.recipeId].course] ?? 9));
  if (!dishes.length) { dishes.push({ recipeId: 'coffee_service', name: RBY.coffee_service.name, said: '', match: 'default' }); assumptions.push('No dishes recognised — added coffee service only.'); }
  if (!dishes.some(d => d.recipeId === 'bread_basket') && style === 'plated' && et[1] !== 'breakfast') { dishes.push({ recipeId: 'bread_basket', name: RBY.bread_basket.name, said: '', match: 'added' }); assumptions.push('Added a bread basket (standard for plated dinners).'); }
  if (!dishes.some(d => d.recipeId === 'coffee_service') && ['gala', 'wedding', 'dinner', 'christmas_party', 'conference'].includes(et[1])) { dishes.push({ recipeId: 'coffee_service', name: RBY.coffee_service.name, said: '', match: 'added' }); assumptions.push('Added coffee & milk service after the meal.'); }
  services.push({ id: 'main', name: name, date, time: /lunch|lounas/i.test(text) ? '12:00' : '18:00', guests, style, dishes });
  if (breakfastM) { const bg = parseInt(breakfastM[1], 10); const bd = /next morning|following morning|seuraavana aamuna/i.test(text) ? addDays(date, 1) : date; services.push({ id: 'breakfast', name: 'Breakfast', date: bd, time: '07:00', guests: bg, style: 'buffet', dishes: [{ recipeId: 'breakfast_buffet', name: RBY.breakfast_buffet.name, said: 'breakfast', match: 'exact' }] }); }
  if (Object.values(diet).every(x => !x) && !Object.keys(allergies).length) assumptions.push('No dietary needs mentioned — none assumed.');
  const site = S().buyers[S().buyerId].site; const lang = /[äö]|hengelle|henkilölle|vieraalle|pikkujoulu|perjantai|lauantai|ensi /i.test(text) ? 'fi' : 'en'; return { briefId: rid('EB'), lang, context: dayContext(site.id, date), text, name, eventType: et[1], eventTypeLabel: et[2], date, guests, style, diet, allergies, services, assumptions, question, site: S().buyers[S().buyerId].site };
}
function dietGroups(brief, svc) {
  const g = []; const d = brief.diet;
  if (d.vegan) g.push({ key: 'vegan', label: `${d.vegan} vegan`, n: d.vegan, diet: ['vegan'], excl: [] });
  if (d.vegetarian) g.push({ key: 'vegetarian', label: `${d.vegetarian} vegetarian`, n: d.vegetarian, diet: ['vegetarian'], excl: [] });
  if (d.gluten_free) g.push({ key: 'gluten_free', label: `${d.gluten_free} gluten-free`, n: d.gluten_free, diet: [], excl: ['cereals_gluten'] });
  for (const [a, n] of Object.entries(brief.allergies)) g.push({ key: a, label: `${n} ${a === 'nuts' ? 'nut' : C.ALLERGEN_LABELS[a].toLowerCase()} allerg${n > 1 ? 'ies' : 'y'}`, n, diet: a === 'nuts' || a === 'peanuts' ? ['nut_free'] : a === 'milk' ? ['milk_free'] : [], excl: [a], allergy: true });
  const scale = svc.guests / brief.guests; return svc.id === 'main' ? g : g.map(x => ({ ...x, n: Math.round(x.n * scale) })).filter(x => x.n > 0);
}
function needsVariant(r, grp) { const al = new Set([...(r.allergens || []), ...(r.mayContain || [])]); if (grp.key === 'vegan') return !r.diet.includes('vegan'); if (grp.key === 'vegetarian') return !r.diet.includes('vegetarian') && !r.diet.includes('vegan'); if (grp.key === 'gluten_free') return !r.diet.includes('gluten_free'); if (grp.allergy) return al.has(grp.key) || (grp.key === 'nuts' && r.id === 'choc_mousse'); return false; }
function learnedFactor(bid, eventType, need) {
  const sig = C.computeSignals(bid); const pc = sig.perCover.filter(x => x.need === need && (x.eventType === eventType || (eventType === 'christmas_party' && x.eventType === 'gala')));
  const p = pc.find(x => x.eventType === eventType) || pc[0]; if (!p || p.n < 2 || !p.perCoverPlannedMedian) return null;
  const recent = p.actual.slice(-3), plannedRecent = p.planned.slice(-3); const f = median(recent) / median(plannedRecent.length ? plannedRecent : p.planned);
  if (Math.abs(1 - f) < 0.05) return null;
  return { factor: Math.max(0.6, Math.min(1.15, f)), n: Math.min(3, p.n), dates: p.dates.slice(-3), actual: median(recent), planned: median(plannedRecent), processIds: p.processIds.slice(-3), unit: p.unit, eventType: p.eventType };
}
async function planEvent(brief, opts = {}) {
  const bid = opts.buyerId || S().buyerId; const traceId = opts.traceId || rid('TR'); const buyer = S().buyers[bid];
  const ev = opts.event || { eventId: rid('EVT'), buyerId: bid, createdAt: clock.iso(), status: 'planning', orderIds: [], history: [] };
  ev.brief = brief; ev.traceId = traceId; ev.name = brief.name; ev.date = brief.date; ev.guests = brief.guests;
  if (!opts.event) S().events.unshift(ev);
  await audit({ traceId, actor: 'agent:' + agentOf(bid).split(':')[1], action: 'event_intake', buyerId: bid, inputs: { guests: brief.guests, date: brief.date, dishes: brief.services.flatMap(s => s.dishes.map(d => d.recipeId)), diet: brief.diet, allergies: brief.allergies }, reason: `${brief.name}, ${dayLabel(brief.date)}, ${brief.guests} guests, ${brief.services.reduce((a, s) => a + s.dishes.length, 0)} dishes` });
  // 3–4: recipes → ingredients, scaled, dietary split, right-sized by history
  const menu = []; const ing = {};
  for (const svc of brief.services) {
    const groups = dietGroups(brief, svc); const buffer = STYLE_BUFFER[svc.style] || 0.05;
    for (const d of svc.dishes) {
      const r = RBY[d.recipeId]; let std = svc.guests; const variants = {};
      for (const g of groups) { if (needsVariant(r, g)) { const vid = r.variants[g.key] || (g.allergy ? r.variants[g.key] : null); if (vid) { std -= g.n; const v = variants[vid] = variants[vid] || { recipe: RBY[vid], n: 0, groups: [], diet: new Set(), excl: new Set() }; v.n += g.n; v.groups.push(g.label); g.diet.forEach(x => v.diet.add(x)); g.excl.forEach(x => v.excl.add(x)); } else menu.push({ warn: `${r.name} has no safe variant for ${g.label} — handle manually.` }); } }
      const portions = [{ recipe: r, n: Math.max(0, std), groups: ['standard'], diet: new Set(), excl: new Set() }, ...Object.values(variants)];
      menu.push({ service: svc.id, serviceName: svc.name, date: svc.date, dish: d, recipe: r, portions: portions.map(p => ({ recipeId: p.recipe.id, name: p.recipe.name, n: p.n, groups: p.groups })) });
      for (const p of portions) { if (!p.n) continue; for (const [need, qpp, unit, yld, label] of p.recipe.ing) {
        const key = need;
        const base = p.n * qpp / (yld || 1); const e = ing[key] = ing[key] || { key, need, label, unit, constraints: { diet: [], excl: [] }, baseline: 0, buffered: 0, sources: [], dates: new Set() };
        for (const x of [...p.diet].filter(x => x !== 'vegetarian')) if (!e.constraints.diet.includes(x)) e.constraints.diet.push(x);
        for (const x of p.excl) if (!e.constraints.excl.includes(x)) e.constraints.excl.push(x);
        e.baseline += base; e.buffered += base * (1 + buffer); e.sources.push({ dish: p.recipe.name, service: svc.name, portions: p.n, perPortion: qpp, unit, groups: p.groups }); e.dates.add(svc.date);
      } }
    }
  }
  const lines = []; let n = 0;
  for (const e of Object.values(ing)) {
    if (e.sources.some(s => s.groups.includes('standard'))) e.constraints.diet = e.constraints.diet.filter(d => d !== 'vegan');
    const lf = learnedFactor(bid, brief.eventType, e.need);
    const planned = e.buffered * (lf ? lf.factor : 1);
    const firstDate = [...e.dates].sort()[0];
    const rn = C.resolveNeed(e.need); const sample = C.BY_GTIN[rn.candidates.find(g => C.BY_GTIN[g].kind === rn.kind)] || {};
    const fresh = (sample.shelfLifeDays || 365) <= 7 && !/frozen/i.test(sample.name || '');
    const needBy = addDays(brief.date, fresh ? -1 : -2);
    const txt = [...e.constraints.diet.map(d => C.DIET_LABELS[d]), e.need].join(' ');
    e.why = { history: lf ? `${lf.n} past ${lf.eventType} events used ${fq(lf.actual, e.unit)}/guest vs ${fq(lf.planned, e.unit)} planned → ×${lf.factor.toFixed(2)}` : null, lf };
    lines.push({ lineId: 'I' + (++n), text: txt, label: e.label + (e.constraints.diet.length || e.constraints.excl.length ? ' (' + [...e.constraints.diet.map(d => C.DIET_LABELS[d]), ...e.constraints.excl.map(a => 'no ' + C.ALLERGEN_LABELS[a].toLowerCase())].join(', ') + ')' : ''), qty: Math.round(planned * 1000) / 1000, unit: e.unit, needBy, lineNeedBy: needBy, useLeftovers: true, allowPacks: true, diet: e.constraints.diet, excludeAllergens: e.constraints.excl, qtyAdjustment: lf ? { baseline: Math.round(e.buffered * 1000) / 1000, planned: Math.round(planned * 1000) / 1000, why: `${lf.n} past ${lf.eventType} events used ${fq(lf.actual, e.unit)}/guest`, label: e.need.charAt(0).toUpperCase() + e.need.slice(1) } : null, ing: e });
  }
  // 5–7: net leftovers, source with preferences, signed offers, timing
  const pr = await planRequest(bid, lines.map(l => ({ ...l })), addDays(brief.date, -1), { useLeftovers: true, usage: { type: 'event', date: brief.date }, offerDepth: 2 });
  pr.lines.forEach((pl, i) => { pl.lineNeedBy = lines[i].needBy; pl.ing = lines[i].ing; });
  const basket = []; const unsourced = [];
  for (const pl of pr.lines) {
    const plan = pl.plans[0]; if (!plan) { if (pl.qtyAfterLeftovers <= 0) continue; unsourced.push({ label: pl.label, reason: pl.excluded[0] ? pl.excluded[0].reason : 'no product' }); continue; }
    for (const l of plan.lines) { l.diet = pl.ing.constraints.diet; l.excludeAllergens = pl.ing.constraints.excl; l.why = { sources: pl.ing.sources, baseline: pl.ing.baseline, history: pl.ing.why.history, leftovers: pl.notices.filter(x => x.type === 'leftover' && x.applied).map(x => x.text), preference: (pl.ranked.find(r => r.gtin === l.gtin) || {}).rankReason, reasons: (pl.ranked.find(r => r.gtin === l.gtin) || {}).reasons || [], tradeoff: (pl.ranked.find(r => r.gtin === l.gtin) || {}).tradeoff, need: pl.qtyAfterLeftovers, leftoverQty: pl.qty - pl.qtyAfterLeftovers }; l.qtyAdjustment = pl.qtyAdjustment && pl.plans[0].lines[0] === l ? pl.qtyAdjustment : null; const share = l.qty / sum(plan.lines.map(x => x.qty)); l.expectedUse = r2(pl.ing.baseline * (pl.ing.why.lf ? pl.ing.why.lf.factor : 1) * share * 1000) / 1000; l.carriedIn = r2((pl.qty - pl.qtyAfterLeftovers) * share * 1000) / 1000; l.ingNeed = pl.ing.need; l.perGuestPlanned = r2(pl.ing.baseline / brief.guests * 10000) / 10000; basket.push(l); }
  }
  const total = r2(sum(basket.map(l => l.lineTotal)));
  const requestLines = pr.lines.map(l => ({ lineId: l.lineId, qty: l.qtyAfterLeftovers, needBy: l.lineNeedBy, label: l.label })).filter(l => l.qty > 0);
  const [mandate, mcheck] = await C.mandateCheck(bid);
  const pol = evaluate(bid, basket, requestLines, mandate, mcheck, pr.signals, { event: { guests: brief.guests, name: brief.name } });
  // allergen safety panel
  const groups = dietGroups(brief, brief.services[0]); const safety = groups.map(g => {
    const dishesFor = menu.filter(m => m.recipe).map(m => { const p = m.portions.find(x => x.groups.includes(g.label)) || m.portions[0]; return { dish: m.dish.name, serves: p.name, variant: p.recipeId !== m.recipe.id }; });
    const risky = basket.filter(l => (l.excludeAllergens || []).length && g.excl.some(a => (l.excludeAllergens || []).includes(a))).filter(l => { const pp = C.BY_GTIN[l.gtin]; return g.excl.some(a => pp.allergens.includes(a) || pp.mayContain.includes(a)); });
    return { group: g.label, key: g.key, dishes: dishesFor, safe: !risky.length, checkedLines: basket.filter(l => g.excl.some(a => (l.excludeAllergens || []).includes(a)) || g.diet.some(d => (l.diet || []).includes(d))).length };
  });
  // deliveries & prep timeline
  const deliveries = {}; for (const l of basket) (deliveries[l.deliveryDate] = deliveries[l.deliveryDate] || []).push(l);
  const tl = {}; const put = (d, t, kind) => (tl[d] = tl[d] || []).push({ text: t, kind });
  for (const [d, ls] of Object.entries(deliveries)) put(d, `Delivery: ${ls.length} lines (${ls.some(l => (C.BY_GTIN[l.gtin].shelfLifeDays || 365) <= 7) ? 'fresh' : 'dry & frozen'})`, 'delivery');
  const seen = new Set(); for (const m of menu.filter(x => x.recipe)) for (const p of m.portions) { const r = RBY[p.recipeId]; for (const [off, task] of r.prep || []) { const k = task + off + m.date; if (seen.has(k) || !p.n) continue; seen.add(k); put(addDays(m.date, off), `${task}${p.recipeId !== m.recipe.id ? ' (' + p.n + ' portions for ' + p.groups.join(' + ') + ')' : ''}`, 'prep'); } }
  for (const s of brief.services) put(s.date, `${s.name}: ${s.guests} guests at ${s.time}`, 'service');
  put(addDays(brief.services[brief.services.length - 1].date, 1), 'Reconcile leftovers (one tap, prefilled)', 'reconcile');
  const timeline = Object.entries(tl).sort((a, b) => a[0] < b[0] ? -1 : 1).map(([d, items]) => ({ date: d, rel: relDay(d, brief.date), items }));
  const leftoversChecked = S().leftovers.filter(l => l.buyerId === bid && l.status === 'available').length;
  const netted = pr.lines.flatMap(l => l.notices.filter(x => x.type === 'leftover' && x.applied));
  const nOffers = Object.keys(pr.offers).length;
  const did = { dishes: brief.services.reduce((a, s) => a + s.dishes.length, 0), recipes: menu.filter(m => m.recipe).reduce((a, m) => a + m.portions.filter(p => p.n).length, 0), ingredients: pr.lines.length, searched: sum(pr.lines.map(l => l.searched)), offers: nOffers, verified: Object.values(pr.verifs).filter(v => v.verified).length, allergenChecks: basket.length * Math.max(1, groups.length), leftoversChecked, leftoversNetted: netted.length, deliveries: Object.keys(deliveries).length, rightSized: basket.filter(l => l.qtyAdjustment).length, approvals: pol.outcome === 'APPROVE' ? 1 : 0 };
  did.minutesSaved = Math.round(did.searched * 1.5 + did.offers * 1 + did.ingredients * 2 + did.allergenChecks * 0.2 + did.leftoversChecked * 1.5 + 20 + (pol.outcome === 'APPROVE' ? 5 : 15));
  const result = { eventId: ev.eventId, traceId, brief, menu, ingredients: Object.values(ing), lines: pr.lines, basket, unsourced, total, perGuest: r2(total / brief.guests), target: mandate && mandate.limits.perGuestEUR, policy: pol, safety, deliveries, timeline, did, verifs: pr.verifs, offers: pr.offers };
  ev.plan = result; ev.status = 'planned';
  await audit({ traceId, actor: 'agent:' + agentOf(bid).split(':')[1], action: 'event_planned', buyerId: bid, refs: { eventId: ev.eventId, offerIds: Object.values(pr.offers).map(o => o.offerId).slice(0, 12) }, reason: `${basket.length} lines, ${money(total)} (${money(result.perGuest)}/guest), ${Object.keys(deliveries).length} deliveries; ${did.rightSized} right-sized from history; ${did.leftoversNetted} leftovers netted` });
  await audit({ traceId, actor: 'system:policy', action: 'policy_decision', buyerId: bid, decision: pol.outcome, ruleIds: pol.ruleIds, refs: { eventId: ev.eventId }, reason: pol.decisions.map(d => `${d.ruleId}: ${d.reason}`).join(' ') || 'No rule fired.' });
  return result;
}
const relDay = (d, ev) => { const n = Math.round((new Date(d) - new Date(ev)) / 864e5); return n === 0 ? 'D-day' : n < 0 ? `D${n}` : `D+${n}`; };
async function orderEvent(eventId, opts = {}) {
  const ev = S().events.find(e => e.eventId === eventId); const pl = ev.plan; const bid = ev.buyerId;
  let lines = pl.basket; let title = `${ev.name} — ${ev.guests} guests`;
  if (opts.delta) { lines = opts.delta; title = `${ev.name} — top-up to ${ev.guests} guests`; }
  if (!lines.length) return { nothing: true };
  const T = { traceId: pl.traceId, buyerId: bid, agentId: agentOf(bid), text: title, steps: [], startedAt: ev.createdAt, toolCalls: 8, exceptions: { offersRequoted: 0, priceChanged: 0, insufficientStock: 0 }, channel: 'event-autopilot', usage: { type: 'event', eventType: ev.brief.eventType, name: ev.name, date: ev.date, guestsExpected: ev.guests, eventId }, parsed: { needBy: addDays(ev.date, -1) }, lines: opts.delta ? [] : pl.lines, plans: [], verifs: pl.verifs, offers: pl.offers };
  S().traces[T.traceId] = T;
  const plan = { planId: rid('PL'), label: 'P1', strategy: 'event_basket', lines: clone(lines), total: r2(sum(lines.map(l => l.lineTotal))), coverage: { pct: 100, pctByNeedBy: 100 } };
  T.plans = [plan];
  const res = await checkout(T, plan, { kind: 'event', eventId, title, policyExtra: { event: { guests: ev.guests, name: ev.name }, total: opts.delta ? pl.total : undefined } });
  if (res.order) { ev.orderIds.push(res.order.orderId); ev.status = 'ordered'; ev.orderedLines = mergeOrdered(ev.orderedLines, res.order.lines); }
  else if (res.ap) ev.status = 'awaiting_approval';
  else if (res.co && res.co.status === 'blocked') ev.status = 'blocked';
  return res;
}
function mergeOrdered(prev, lines) { const m = {}; for (const l of [...(prev || []), ...lines]) { const k = l.gtin + '|' + l.deliveryDate; if (m[k]) { m[k].cases += l.cases; m[k].qty = r2(m[k].qty + l.qty); m[k].lineTotal = r2(m[k].lineTotal + l.lineTotal); } else m[k] = clone(l); } return Object.values(m); }
async function rescaleEvent(eventId, guests) {
  const ev = S().events.find(e => e.eventId === eventId); const old = ev.plan; const prevGuests = ev.guests;
  const brief = clone(old.brief); const f = guests / brief.guests; brief.guests = guests; brief.services = brief.services.map(s => ({ ...s, guests: s.id === 'main' ? guests : s.guests }));
  // what is already ordered for this event is ours: put it back while re-planning, so the delta is computed on the same products
  const ordered = ev.orderedLines || []; for (const l of ordered) S().stock[l.gtin] += l.qty;
  const np = await planEvent(brief, { event: ev, traceId: old.traceId, buyerId: ev.buyerId });
  for (const l of ordered) S().stock[l.gtin] -= l.qty;
  const prevQ = {}, newQ = {}; for (const l of (ev.orderedLines || old.basket)) prevQ[l.gtin] = r2((prevQ[l.gtin] || 0) + l.qty); for (const l of np.basket) newQ[l.gtin] = r2((newQ[l.gtin] || 0) + l.qty);
  const delta = []; const diff = [];
  for (const g of new Set([...Object.keys(prevQ), ...Object.keys(newQ)])) { const was = prevQ[g] || 0, now = newQ[g] || 0; const p = C.BY_GTIN[g]; diff.push({ gtin: g, name: p.name, unit: p.unit, was, now, d: r2(now - was) }); if (now > was + 1e-9) { const l = np.basket.find(x => x.gtin === g); const dl = clone(l); dl.cases = Math.ceil((now - was) / l.caseQty - 1e-9); dl.qty = r2(dl.cases * l.caseQty); dl.lineTotal = r2(dl.qty * l.unitPrice); dl.lineId = l.lineId + '-T'; dl.qtyAdjustment = null; delta.push(dl); } }
  await audit({ traceId: old.traceId, actor: 'human:' + S().buyers[ev.buyerId].approvers[1].name, action: 'event_rescaled', buyerId: ev.buyerId, refs: { eventId }, reason: `Guests ${prevGuests} → ${guests} (×${f.toFixed(2)}): ${diff.filter(d => d.d).length} lines change, top-up ${money(sum(delta.map(d => d.lineTotal)))}` });
  ev.lastDelta = { from: prevGuests, to: guests, diff: diff.filter(d => d.d !== 0), delta, deltaTotal: r2(sum(delta.map(d => d.lineTotal))) };
  return { plan: np, delta: ev.lastDelta };
}
function predictReconciliation(eventId) {
  const ev = S().events.find(e => e.eventId === eventId); const lines = ev.orderedLines || ev.plan.basket;
  const agg = {};
  for (const l of lines) { const a = agg[l.gtin] = agg[l.gtin] || { gtin: l.gtin, name: l.name, unit: l.unit, ordered: 0, carriedIn: 0, unitPrice: l.unitPrice, expectedUse: 0, need: l.ingNeed || l.name, perGuestPlanned: l.perGuestPlanned || null }; a.ordered = r2(a.ordered + l.qty); a.expectedUse = r2(a.expectedUse + (l.expectedUse != null ? l.expectedUse * (ev.guests / ev.plan.brief.guests) : l.qty)); a.carriedIn = r2(a.carriedIn + (l.carriedIn || 0)); }
  return Object.values(agg).map(a => { const p = C.BY_GTIN[a.gtin]; const avail = r2(a.ordered + a.carriedIn); const used = Math.min(avail, a.expectedUse); const left = r2(avail - used); const keep = (p.shelfLifeDays || 365) > 7; return { ...a, used: r2(used), kept: keep ? left : 0, redistributed: 0, wasted: keep ? 0 : left, wasteReason: keep ? null : left > 0 ? 'prep/plate waste' : null, shortage: 0, bestBefore: addDays(ev.date, Math.min(p.shelfLifeDays || 365, 400)) }; });
}
async function reconcileEvent(eventId, entries, actualGuests, byName) {
  const ev = S().events.find(e => e.eventId === eventId); const bid = ev.buyerId;
  const errors = []; for (const e of entries) { if (e.used + e.kept + e.redistributed + e.wasted > e.ordered + e.carriedIn + 1e-6) errors.push(`${e.name}: used + leftover + wasted exceeds ordered + carried-in`); if ([e.used, e.kept, e.redistributed, e.wasted, e.shortage].some(x => x < 0)) errors.push(`${e.name}: negative quantity`); }
  if (errors.length) return { errors };
  const cons = entries.map(e => { const p = C.BY_GTIN[e.gtin]; const bl = (ev.orderedLines || ev.plan.basket).find(l => l.gtin === e.gtin) || {}; const pcPlan = bl.perGuestPlanned || null; return { need: bl.ingNeed || p.name, gtin: e.gtin, name: p.name, unit: p.unit, ordered: e.ordered, carriedIn: e.carriedIn, used: e.used, kept: e.kept, redistributed: e.redistributed, wasted: e.wasted, wasteReason: e.wasted > 0 ? e.wasteReason || 'over-ordered' : null, shortage: e.shortage, emergencyQty: e.shortage, unitPrice: e.unitPrice, kgPerUnit: p.kgPerUnit, co2eKgPerKg: p.co2eKgPerKg, perCoverPlanned: pcPlan, perCoverActual: actualGuests ? r2((e.used + e.shortage) / actualGuests * 1000) / 1000 : null, caseOverage: 0 }; });
  ev.reconciliation = { at: clock.iso(), by: byName, actualGuests, consumption: cons, metrics: eventMetrics(cons) }; ev.status = 'reconciled';
  for (const lo of S().leftovers) if (lo.buyerId === bid && ev.plan.basket.some(l => (l.why && l.why.leftovers || []).some(t => t.includes(C.BY_GTIN[lo.gtin].name)))) lo.status = 'used';
  for (const c of cons) if (c.kept > 0) S().leftovers.push({ leftoverId: rid('LO'), buyerId: bid, siteId: S().buyers[bid].site.id, gtin: c.gtin, qty: c.kept, bestBefore: entries.find(e => e.gtin === c.gtin).bestBefore, sourceLabel: `${ev.name} (${dayLabel(ev.date)})`, status: 'available' });
  const rec = S().processes.find(p => p.traceId === ev.traceId);
  if (rec) { rec.consumption = cons; rec.usageContext = { ...rec.usageContext, eventType: ev.brief.eventType, name: ev.name, date: ev.date, guestsExpected: ev.guests, guestsActual: actualGuests }; rec.outcome.status = 'reconciled'; rec.feedback = rec.feedback || { onTime: true, deliveredQty: rec.outcome.qtyOrdered, qualityIssue: false, rating: 5, substituteAccepted: rec.outcome.substitutions.length ? true : null }; }
  await audit({ traceId: ev.traceId, actor: 'human:' + byName, action: 'reconciliation_recorded', buyerId: bid, refs: { eventId }, reason: `utilisation ${Math.round(ev.reconciliation.metrics.utilisation * 100)}%, waste ${money(ev.reconciliation.metrics.wastedEUR)}, reused ${money(ev.reconciliation.metrics.reusedEUR)}` });
  return { reconciliation: ev.reconciliation, advice: eventAdvice(ev) };
}
function eventAdvice(ev) {
  const r = ev.reconciliation; if (!r) return []; const out = [];
  for (const c of r.consumption) { const avail = c.ordered + c.carriedIn; if (avail && c.wasted / avail > 0.1) out.push(`${c.name}: ${Math.round(c.wasted / avail * 100)} % wasted — next time plan ${fq(c.perCoverActual, c.unit)}/guest instead of ${fq(c.perCoverPlanned || 0, c.unit)}.`); if (c.shortage > 0) out.push(`${c.name}: ran short by ${fq(c.shortage, c.unit)} — add a ${Math.round(c.shortage / Math.max(1, c.used) * 100 + 5)} % buffer for this dish.`); if (avail && (c.kept + c.redistributed) / avail > 0.15) out.push(`${c.name}: ${fq(c.kept + c.redistributed, c.unit)} reused — the Autopilot will net it against the next order.`); }
  if (!out.length) out.push('Perfect order: everything ordered was used. The Autopilot keeps these quantities.');
  return out;
}

// ======================================================= Valio Aimo ops (aggregate only)
function opsSummary() {
  const recs = S().processes; const mix = { AUTO: 0, NOTIFY: 0, APPROVE: 0, BLOCK: 0 }; for (const r of recs) if (r.decision.outcome) mix[r.decision.outcome]++;
  const lat = recs.map(r => r.decision.approvalLatencyMin).filter(x => x != null);
  const agents = Object.values(S().agents).map(a => { const rs = recs.filter(r => r.agentId === a.id); return { ...a, buyer: S().buyers[a.buyerId].name, requests: rs.length + a.calls * 0, live: rs.filter(r => r.live).length, blocked: rs.filter(r => r.decision.outcome === 'BLOCK').length, spend: sum(rs.map(r => r.outcome.totalEUR || 0)) }; });
  const cats = {}; for (const r of recs) for (const l of r.lines || []) { const c = cats[l.category] = cats[l.category] || { category: l.category, qtyOrdered: 0, qtyDelivered: 0, orders: 0, weekly: {} }; c.orders++; c.qtyOrdered += l.qty; const f = r.outcome.qtyOrdered ? (r.outcome.qtyDelivered || r.outcome.qtyOrdered) / r.outcome.qtyOrdered : 1; c.qtyDelivered += l.qty * f; const wk = weekOf(r.createdAt); c.weekly[wk] = (c.weekly[wk] || 0) + l.lineTotal; }
  const subsByProduct = {}; for (const r of recs) for (const s of r.outcome.substitutions || []) { const e = subsByProduct[s.fromGtin] = subsByProduct[s.fromGtin] || { gtin: s.fromGtin, name: s.fromName, n: 0, buyers: new Set() }; e.n++; e.buyers.add(r.buyerId); }
  const over = {}; for (const r of recs) for (const c of r.consumption || []) { const e = over[c.gtin] = over[c.gtin] || { gtin: c.gtin, name: c.name, unit: c.unit, caseQty: C.BY_GTIN[c.gtin].caseQty, overage: 0, wasted: 0, n: 0 }; e.overage += Math.max(0, c.caseOverage || 0); e.wasted += c.wasted; e.n++; }
  const blocked = recs.filter(r => r.decision.outcome === 'BLOCK').map(r => ({ date: r.createdAt.slice(0, 10), buyer: S().buyers[r.buyerId].name, agent: r.agentId, rules: r.decision.ruleIds, text: r.request.excerpt }));
  const weeks = []; for (let w = 11; w >= 0; w--) weeks.push(weekMonday(w));
  const wa = weeks.map(w => { const rs = recs.filter(r => weekOf(r.createdAt) === w); return { week: w, n: rs.length, auto: rs.filter(r => ['AUTO', 'NOTIFY'].includes(r.decision.outcome)).length }; });
  return { mix, total: recs.length, approvalP50: median(lat), approvalP90: quant(lat, .9), agents, categories: Object.values(cats).map(c => ({ ...c, fillRate: c.qtyOrdered ? c.qtyDelivered / c.qtyOrdered : 1, series: weeks.map(w => c.weekly[w] || 0) })).sort((a, b) => b.orders - a.orders), stockoutSubs: Object.values(subsByProduct).map(e => ({ ...e, buyers: e.buyers.size })).sort((a, b) => b.n - a.n).slice(0, 5), packOverage: Object.values(over).filter(e => e.overage > 0 || e.wasted > 0).sort((a, b) => b.wasted - a.wasted).slice(0, 5), blocked, weekly: wa, waste: wasteInsights(null).totals };
}
async function setKill(agentId, on, by) { const a = S().agents[agentId]; a.killed = on; a.killedBy = by; await audit({ actor: 'human:' + by, action: 'kill_switch', buyerId: a.buyerId, refs: { agentId }, decision: on ? 'SUSPENDED' : 'RESUMED', reason: `${a.name} ${on ? 'suspended' : 'resumed'} by Valio Aimo operations` }); }

// ======================================================= boot & scenes
async function boot() {
  C.S = C.baseState(); const st = C.S; clock.skewMin = 0;
  st.keys.gw = await C.genKey('gw-2026-11'); st.keys.buyers = {};
  for (const bid of Object.keys(st.buyers)) st.keys.buyers[bid] = await C.genKey('buyer-' + bid.toLowerCase());
  st.processes = seedHistory(); await seedAudit(st.processes);
  for (const bid of Object.keys(st.buyers)) { const b = st.buyers[bid]; await C.registerMandate(bid, await C.signMandate(bid, b.mandate)); }
  return st;
}
const milkStock = (st, a) => { st.stock[BY_KEY.milk_lf_semi_kaarna.gtin] = a; st.stock[BY_KEY.milk_lf_semi_maitokaari.gtin] = 800; st.stock[BY_KEY.milk_lf_whole_tunturi.gtin] = 1200; st.inbound[BY_KEY.milk_lf_semi_kaarna.gtin] = [{ inDays: 5, qty: 800 }]; st.prices[BY_KEY.milk_lf_semi_kaarna.gtin] = 1.29; };
const SCENES = {
  S1: { buyer: 'BUY-POHJOLA', text: 'I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability.', setup: st => milkStock(st, 1200) },
  S2: { buyer: 'BUY-POHJOLA', text: 'I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability.', setup: st => milkStock(st, 640) },
  S3: { buyer: 'BUY-POHJOLA', text: 'Last-minute event tomorrow for 220 guests: 50 kg salmon fillet, 30 kg beef tenderloin, 40 L whipping cream, 80 kg potatoes, 30 kg frozen strawberries and 18 kg Emmental cheese.', setup: st => { for (const k of ['salmon_fillet', 'beef_tenderloin', 'cream_whip_kaarna', 'potatoes_new', 'strawberries_frozen', 'cheese_emmental_tunturi']) st.stock[BY_KEY[k].gtin] = Math.max(st.stock[BY_KEY[k].gtin], BY_KEY[k].stock); } },
  S4: { buyer: 'BUY-KAARI', text: 'We need 240 litres of oat drink by Tuesday, milk-free and nut-free for the wards.', setup: () => {} },
  S5: { buyer: 'BUY-POHJOLA', text: 'Renew standing order SO-1001 for next week: 610 litres lactose-free milk.', setup: st => milkStock(st, 1200) },
  X1: { buyer: 'BUY-POHJOLA', text: 'I need 1,000 litres of lactose-free milk by Monday.', setup: st => milkStock(st, 1200), opts: { simulateDelay: true } },
};
const GALA = 'Gala dinner on Saturday the 21st for 180 guests: salmon starter, beef tenderloin with potato gratin, chocolate mousse, breakfast for 60 the next morning. 12 vegans, 8 gluten-free, one nut allergy.';
const PIKKUJOULU = 'Pikkujoulut perjantaina 120 hengelle, kinkku, laatikot, rosolli ja riisipuuro. 6 vegaania.';
async function runScene(id) {
  const sc = SCENES[id]; const st = C.S; sc.setup(st); st.buyerId = sc.buyer;
  return runAgent(sc.text, Object.assign({ buyerId: sc.buyer }, sc.opts || {}));
}
async function forceLines(bid, items, needBy, title) {
  // explicit lines (e.g. "force almond drink") — the gateway still evaluates every rule
  const T = { traceId: rid('TR'), buyerId: bid, agentId: agentOf(bid), text: title, steps: [], startedAt: clock.iso(), toolCalls: 2, exceptions: { offersRequoted: 0, priceChanged: 0, insufficientStock: 0 }, channel: 'agent-api', usage: { type: 'adhoc' }, parsed: { needBy }, lines: [], plans: [], verifs: {}, offers: {} };
  S().traces[T.traceId] = T; const lines = [];
  for (const [g, qty] of items) { const p = BY_GTIN[g]; const o = await C.issueOffer(g, needBy, bid); T.offers[g] = o; const cases = Math.ceil(qty / p.caseQty - 1e-9); lines.push({ lineId: 'F' + lines.length, requestLineId: 'F', gtin: g, name: p.name, brand: p.brand, category: p.category, unit: p.unit, caseQty: p.caseQty, cases, qty: cases * p.caseQty, unitPrice: C.BE.price(g), lineTotal: r2(cases * p.caseQty * C.BE.price(g)), deliveryDate: needBy, role: 'primary', offerId: o.offerId, certificates: p.certificates.map(c => c.label), supplierId: p.origin.supplierId, overage: 0 }); }
  T.steps.push({ id: 'understand', title: 'Agent forced explicit lines', status: 'warn', detail: lines.map(l => `${fq(l.qty, l.unit)} ${l.name}`).join(', ') });
  const plan = { planId: rid('PL'), label: 'P1', lines, total: r2(sum(lines.map(l => l.lineTotal))), coverage: { pct: 100, pctByNeedBy: 100 } }; T.plans = [plan];
  await checkout(T, plan, {}); return T;
}

G.AimoFlows = { labelsFor, lineUsageLabel, dayContext, LABEL_DEFS, METRIC_DEFS, parseRequest, parseDate, planRequest, runAgent, checkout, decideApproval, closeProcess, kpis, recommendations, applyRecommendation, wasteInsights, eventMetrics, utilisation, parseBrief, planEvent, orderEvent, rescaleEvent, predictReconciliation, reconcileEvent, eventAdvice, opsSummary, setKill, boot, runScene, forceLines, SCENES, GALA, PIKKUJOULU, RECIPES, RBY, weekMonday, choosePlan, evaluate };
})(typeof window !== 'undefined' ? window : globalThis);
