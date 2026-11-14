/* Aimo Agent Gateway — client-side engine (port of gateway/*.py for the self-contained demo).
 * Deterministic: planner, policy, trust (WebCrypto ES256), audit hash chain (SHA-256),
 * outcome store, learning signals, recommendations, Event Autopilot, consumption & waste.
 * Synthetic data only. */
(function (G) {
'use strict';
const D = G.AIMO_DATA;
const P = D.catalog.products;
const BY_GTIN = Object.fromEntries(P.map(p => [p.gtin, p]));
const BY_KEY = Object.fromEntries(P.map(p => [p.key, p]));
const ALLERGENS = D.catalog.allergens;
const RULES = Object.fromEntries(D.rules.rules.map(r => [r.id, r]));
const RANK = { AUTO: 0, NOTIFY: 1, APPROVE: 2, BLOCK: 3 };
const TIERS = ['BEST', 'BETTER', 'GOOD'];
const enc = new TextEncoder();

// ---------------------------------------------------------------- utils
const clone = o => JSON.parse(JSON.stringify(o));
const r2 = x => Math.round((x + 1e-9) * 100) / 100;
const r1 = x => Math.round(x * 10) / 10;
const sum = a => a.reduce((s, x) => s + x, 0);
const median = a => { const v = [...a].sort((x, y) => x - y); if (!v.length) return null; const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
const quant = (a, q) => { const v = [...a].sort((x, y) => x - y); if (!v.length) return null; const i = (v.length - 1) * q, lo = Math.floor(i), hi = Math.min(lo + 1, v.length - 1); return v[lo] + (v[hi] - v[lo]) * (i - lo); };
const money = x => '€' + Number(x).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money0 = x => '€' + Math.round(x).toLocaleString('en-GB');
const fq = (q, u) => (Math.abs(q - Math.round(q)) < 1e-9 ? Math.round(q).toLocaleString('en-GB') : (+q).toLocaleString('en-GB', { maximumFractionDigits: Math.abs(q) < 10 ? 2 : 1 })) + (u ? ' ' + u : '');
const render = (t, v) => t.replace(/\{(\w+)\}/g, (m, k) => (k in v ? String(v[k]) : m));
let _id = 0;
const rid = (p) => p + '-' + (Date.now().toString(36).slice(-4) + (++_id).toString(36)).toUpperCase();
function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function canonical(o) {
  if (o === null || typeof o !== 'object') return JSON.stringify(o);
  if (Array.isArray(o)) return '[' + o.map(canonical).join(',') + ']';
  return '{' + Object.keys(o).sort().map(k => JSON.stringify(k) + ':' + canonical(o[k])).join(',') + '}';
}
const b64u = buf => { let s = ''; const b = new Uint8Array(buf); for (const x of b) s += String.fromCharCode(x); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
const b64uStr = s => b64u(enc.encode(s));
const b64uDec = s => { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; };
const subtle = G.crypto && G.crypto.subtle;
async function sha256hex(s) { const h = await subtle.digest('SHA-256', enc.encode(s)); return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join(''); }

// ---------------------------------------------------------------- clock (demo clock: Fri 13 Nov 2026 09:00 EET)
const ANCHOR = Date.UTC(2026, 10, 13, 7, 0, 0);
const t0 = Date.now();
const clock = {
  skewMin: 0,
  now() { return new Date(ANCHOR + (Date.now() - t0) + this.skewMin * 60000); },
  iso(d) { return (d || this.now()).toISOString().replace(/\.\d+Z$/, 'Z'); },
  today() { return new Date(this.now().getTime() + 2 * 3600e3).toISOString().slice(0, 10); },
  advance(min) { this.skewMin += min; },
};
const addDays = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const weekday = iso => (new Date(iso + 'T12:00:00Z').getUTCDay() + 6) % 7; // 0 = Mon
const WD = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const dayLabel = iso => { const d = new Date(iso + 'T12:00:00Z'); return WD[weekday(iso)].slice(0, 3) + ' ' + d.getUTCDate() + '.' + (d.getUTCMonth() + 1) + '.'; };
const deliveryDay = iso => weekday(iso) === 6 ? addDays(iso, 1) : iso;
const isoTs = (dateIso, hh = 9, mm = 0) => dateIso + 'T' + String(hh - 2).padStart(2, '0') + ':' + String(mm).padStart(2, '0') + ':00Z';

// ---------------------------------------------------------------- catalog & need resolution
const KIND_LABELS = { milk: 'milk', cream: 'cream', butter: 'butter', cheese: 'cheese', yogurt: 'yogurt', quark: 'quark', sour_cream: 'sour cream', eggs: 'eggs', plant_drink: 'plant-based drink', plant_cream: 'plant cream', plant_yogurt: 'plant yogurt', tofu: 'tofu', plant_protein: 'plant protein', spread: 'spread', pasta: 'pasta', rice: 'rice', cereal: 'cereal', flour: 'flour', oil: 'oil', sugar: 'sugar', coffee: 'coffee', tea: 'tea', canned: 'canned goods', pulses: 'pulses', condiment: 'condiment', seeds: 'seeds', salt: 'salt', dried_fruit: 'dried fruit', potato: 'potatoes', root_veg: 'root vegetables', onion: 'onions', tomato: 'tomatoes', cucumber: 'cucumbers', salad: 'salad', celery: 'celery', mushroom: 'mushrooms', fruit: 'fruit', berries: 'berries', beef: 'beef', chicken: 'chicken', pork: 'pork', cold_cuts: 'cold cuts', game: 'game', sausage: 'sausages', salmon: 'salmon', trout: 'trout', cod: 'cod', herring: 'herring', pikeperch: 'pike-perch', shellfish: 'shellfish', bread: 'bread', pastry: 'pastry', nut_butter: 'nut butter', chocolate: 'chocolate', ham_whole: 'whole ham', beetroot: 'beetroot', pickles: 'pickles', herbs: 'herbs' };
const DIET_PATTERNS = [[/lactose[- ]?free|laktoositon/g, 'lactose_free'], [/(?:milk|dairy)[- ]?free|maidoton/g, 'milk_free'], [/nut[- ]?free|pähkinätön/g, 'nut_free'], [/gluten[- ]?free|gluteeniton/g, 'gluten_free'], [/egg[- ]?free|munaton/g, 'egg_free'], [/\bvegan\b|vegaani/g, 'vegan'], [/\bvegetarian\b/g, 'vegetarian']];
const CERT_PATTERNS = [[/\borganic\b|\bluomu\b/g, 'EU Organic'], [/\bmsc\b/g, 'MSC'], [/\bfairtrade\b/g, 'Fairtrade']];
const DIET_LABELS = { lactose_free: 'lactose-free', milk_free: 'milk-free', nut_free: 'nut-free', gluten_free: 'gluten-free', egg_free: 'egg-free', vegan: 'vegan', vegetarian: 'vegetarian' };
const ALLERGEN_LABELS = { cereals_gluten: 'Gluten', crustaceans: 'Crustaceans', eggs: 'Eggs', fish: 'Fish', peanuts: 'Peanuts', soybeans: 'Soy', milk: 'Milk', nuts: 'Tree nuts', celery: 'Celery', mustard: 'Mustard', sesame: 'Sesame', sulphites: 'Sulphites', lupin: 'Lupin', molluscs: 'Molluscs' };
function normTok(t) { t = t.toLowerCase(); if (t.length > 4 && t.endsWith('ies')) return t.slice(0, -3) + 'y'; if (t.length > 4 && t.endsWith('oes')) return t.slice(0, -2); if (t.length > 3 && t.endsWith('s') && !t.endsWith('ss')) return t.slice(0, -1); return t; }
const tokens = s => (s.toLowerCase().match(/[a-zåäö0-9]+/g) || []).map(normTok);
const contains = (seq, sub) => { const n = sub.length; if (!n) return false; for (let i = 0; i + n <= seq.length; i++) { let ok = true; for (let j = 0; j < n; j++) if (seq[i + j] !== sub[j]) { ok = false; break; } if (ok) return true; } return false; };
const needGroupId = p => p.kind + ':' + [...p.variant].sort().join('+');
const needGroupLabel = g => { const [k, v] = g.split(':'); const w = (v ? v.split('+') : []).filter(Boolean).map(x => x.replace(/_/g, '-')); const s = [...w, KIND_LABELS[k] || k].join(' '); return s.charAt(0).toUpperCase() + s.slice(1); };
const digitalLink = p => 'https://id.gs1.org/01/' + p.gtin;
const _needCache = {};
function resolveNeed(text) {
  if (_needCache[text]) return clone(_needCache[text]);
  let t = text.toLowerCase(); const diet = [], certs = [];
  for (const [re, tag] of DIET_PATTERNS) { re.lastIndex = 0; if (re.test(t)) { diet.push(tag); t = t.replace(re, ' '); } }
  for (const [re, l] of CERT_PATTERNS) { re.lastIndex = 0; if (re.test(t)) { certs.push(l); t = t.replace(re, ' '); } }
  const toks = tokens(t); const kindScore = {}; const matched = {};
  for (const p of P) {
    let s = 0;
    for (const kw of [...p.keywords, KIND_LABELS[p.kind] || p.kind]) { const kt = tokens(kw); if (contains(toks, kt)) s += kt.join(' ').length; }
    if (s) { matched[p.gtin] = s; kindScore[p.kind] = Math.max(kindScore[p.kind] || 0, s); }
  }
  let res;
  if (!Object.keys(kindScore).length) res = { kind: null, variants: [], diet, certs, candidates: [], text };
  else {
    const kind = Object.entries(kindScore).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))[0][0];
    let variants = new Set();
    for (const p of P) { if (p.kind !== kind) continue; for (const v of p.variant) { if (diet.includes(v) || v === 'lactose_free' || v === 'gluten_free') continue; if (contains(toks, tokens(v.replace(/_/g, ' ')))) variants.add(v); } }
    const vs = [...variants].sort();
    variants = vs.filter(v => !vs.some(w => w !== v && v.split('_').every(x => w.split('_').includes(x)) && v.split('_').length < w.split('_').length));
    const cands = Object.entries(matched).sort((a, b) => b[1] - a[1]).map(e => e[0]);
    for (const p of P) if (p.kind === kind && !(p.gtin in matched)) cands.push(p.gtin);
    res = { kind, kindLabel: KIND_LABELS[kind] || kind, variants, diet, certs, candidates: cands, text };
  }
  _needCache[text] = res; return clone(res);
}
function searchCatalog(q) {
  if (!q || !q.trim()) return P.slice();
  const r = resolveNeed(q); const set = new Set(r.candidates);
  const ql = q.toLowerCase();
  const extra = P.filter(p => !set.has(p.gtin) && (p.name.toLowerCase().includes(ql) || p.brand.toLowerCase().includes(ql) || p.gtin.includes(ql)));
  return [...r.candidates.map(g => BY_GTIN[g]), ...extra];
}

// ---------------------------------------------------------------- preferences
const CRITERIA = ['spec', 'price', 'delivery', 'quality', 'sustainability', 'brand', 'packFit', 'learned'];
const CRITERIA_LABELS = { spec: 'Spec match', price: 'Price per unit', delivery: 'Delivery reliability', quality: 'Quality', sustainability: 'Sustainability & origin', brand: 'Brand preference', packFit: 'Pack-size fit', learned: 'Learned from history' };
const PRESETS = {
  balanced: { spec: .40, price: .30, delivery: .20, quality: 0, sustainability: .03, brand: .04, packFit: 0, learned: .03 },
  lowest_price: { spec: .30, price: .50, delivery: .10, quality: 0, sustainability: 0, brand: 0, packFit: .05, learned: .05 },
  premium_quality: { spec: .30, price: .10, delivery: .15, quality: .30, sustainability: .05, brand: .05, packFit: 0, learned: .05 },
  domestic_sustainable: { spec: .30, price: .15, delivery: .15, quality: .05, sustainability: .30, brand: 0, packFit: .05, learned: 0 },
  fastest_delivery: { spec: .30, price: .15, delivery: .45, quality: .05, sustainability: 0, brand: 0, packFit: 0, learned: .05 },
};
const PRESET_LABELS = { balanced: 'Balanced', lowest_price: 'Lowest price', premium_quality: 'Premium quality', domestic_sustainable: 'Domestic & sustainable', fastest_delivery: 'Fastest delivery', custom: 'Custom' };
const PREFERRED_BONUS = 0.03, FAVOURITE_BONUS = 0.05;
function defaultProfile(bid) { return { profileId: 'PREF-' + bid.split('-').pop(), buyerId: bid, version: 1, org: { preset: 'balanced', weights: { ...PRESETS.balanced }, filters: [] }, sites: {}, categories: {}, favourites: [], neverBuy: { gtins: [], brands: [] }, needGroups: {}, lists: [], filterViolationOutcome: 'APPROVE' }; }
function normaliseW(w) { const o = {}; let s = 0; for (const c of CRITERIA) { o[c] = Math.max(0, +(w[c] || 0)); s += o[c]; } s = s || 1; for (const c of CRITERIA) o[c] = Math.round(o[c] / s * 10000) / 10000; return o; }
function effectiveProfile(profile, category, siteId) {
  let eff = clone(profile.org); let scope = 'org';
  if (siteId && profile.sites[siteId]) { Object.assign(eff, clone(profile.sites[siteId])); scope = 'site:' + siteId; }
  if (category && profile.categories[category]) { Object.assign(eff, clone(profile.categories[category])); scope = 'category:' + category; }
  if (!eff.weights) eff.weights = { ...(PRESETS[eff.preset] || PRESETS.balanced) };
  eff.weights = normaliseW(eff.weights); eff.filters = eff.filters || []; eff.scope = scope; return eff;
}
function filterCheck(f, p) {
  const vals = f.values || [], op = f.op || 'include', v = f.value;
  switch (f.field) {
    case 'maxUnitPrice': return [p.unitPrice <= +v, `Price ≤ €${(+v).toFixed(2)}/${p.unit}`];
    case 'minQuality': return [p.qualityGrade >= +v, `Quality ≥ ${(+v).toFixed(1)}`];
    case 'maxLeadTime': return [p.leadTimeDays <= +v, `Lead time ≤ ${+v} d`];
    case 'brand': { const h = vals.includes(p.brand); return [op === 'include' ? h : !h, `Brand ${op === 'include' ? 'in' : 'not'}: ${vals.join(', ')}`]; }
    case 'supplier': { const h = vals.includes(p.origin.supplierId); return [op === 'include' ? h : !h, `Supplier ${op === 'include' ? 'in' : 'not'}: ${vals.join(', ')}`]; }
    case 'certificate': { const l = new Set(p.certificates.map(c => c.label)); return [vals.some(x => l.has(x)), `Certificate: ${vals.join(', ')}`]; }
    case 'origin': { const h = vals.includes(p.origin.country); return [op === 'include' ? h : !h, (vals.length === 1 && vals[0] === 'FI') ? 'Domestic (FI)' : `Origin: ${vals.join(', ')}`]; }
    case 'packSize': return [vals.some(x => Math.abs(p.packSize - +x) < 1e-9), `Pack size: ${vals.join(', ')}`];
  }
  return [true, f.field];
}
function applyFilters(eff, p) { const failed = [], bonus = []; for (const f of eff.filters || []) { const [ok, label] = filterCheck(f, p); if (f.mode === 'required' && !ok) failed.push(label); else if (f.mode === 'preferred' && ok) bonus.push(label); } return [failed, bonus]; }
function neverBuy(profile, p) { const nb = profile.neverBuy || {}; if ((nb.gtins || []).includes(p.gtin)) return 'Never-buy list (product)'; if ((nb.brands || []).includes(p.brand)) return `Never-buy list (brand ${p.brand})`; return null; }
function sustainabilityScore(p, todayIso) { let s = p.origin.country === 'FI' ? 0.4 : 0; const l = new Set(p.certificates.filter(c => c.validUntil >= todayIso).map(c => c.label)); if (l.has('EU Organic')) s += 0.3; if ([...l].some(x => x !== 'EU Organic')) s += 0.2; if (['A', 'B'].includes(p.carbonClass)) s += 0.1; return Math.min(1, Math.round(s * 10000) / 10000); }

// ---------------------------------------------------------------- state
let S = null;
function baseState() {
  const buyers = Object.fromEntries(D.buyers.buyers.map(b => [b.id, clone(b)]));
  // event budgets (per event & per guest) for the Event Autopilot
  buyers['BUY-POHJOLA'].mandate.limits.perEventEUR = 3300; buyers['BUY-POHJOLA'].mandate.limits.perGuestEUR = 26;
  buyers['BUY-KAARI'].mandate.limits.perEventEUR = 2500; buyers['BUY-KAARI'].mandate.limits.perGuestEUR = 15;
  buyers['BUY-KOULU'].mandate.limits.perEventEUR = 3000; buyers['BUY-KOULU'].mandate.limits.perGuestEUR = 8;
  return {
    buyerId: 'BUY-POHJOLA', buyers,
    stock: Object.fromEntries(P.map(p => [p.gtin, p.stock])),
    inbound: Object.fromEntries(P.map(p => [p.gtin, clone(p.inbound)])),
    prices: Object.fromEntries(P.map(p => [p.gtin, p.unitPrice])),
    profiles: Object.fromEntries(Object.keys(buyers).map(b => [b, defaultProfile(b)])),
    mandates: {}, offers: {}, revoked: {}, audit: [], tampered: null,
    processes: [], traces: {}, checkouts: {}, approvals: [], orders: [], events: [], leftovers: [], recs: {},
    agents: Object.fromEntries(Object.values(buyers).map(b => [b.agents[0].id, { id: b.agents[0].id, name: b.agents[0].name, buyerId: b.id, killed: false, calls: 0, lastSeen: null }])),
    notifications: [], keys: {},
  };
}

// ---------------------------------------------------------------- backend (fixtures)
const BE = {
  price: g => S.prices[g],
  earliest: g => deliveryDay(addDays(clock.today(), BY_GTIN[g].leadTimeDays)),
  schedule(g) { const out = []; const e = BE.earliest(g); if (S.stock[g] > 0) out.push({ date: e, qty: S.stock[g] }); for (const ib of S.inbound[g]) if (ib.qty > 0) { let d = deliveryDay(addDays(clock.today(), ib.inDays)); if (d < e) d = e; out.push({ date: d, qty: ib.qty }); } return out; },
  availableBy(g, by) { return sum(BE.schedule(g).filter(s => s.date <= by).map(s => s.qty)); },
  placeOrder(order) { for (const ln of order.lines) { let take = Math.min(S.stock[ln.gtin], ln.qty); S.stock[ln.gtin] -= take; let rest = ln.qty - take; for (const ib of S.inbound[ln.gtin]) { if (rest <= 0) break; const t = Math.min(ib.qty, rest); ib.qty -= t; rest -= t; } } return { backendOrderRef: 'AIMO-SO-' + (880000 + S.orders.length + 1), status: 'confirmed' }; },
};

// ---------------------------------------------------------------- crypto: keys, JWS
async function genKey(kid) { const k = await subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']); const jwk = await subtle.exportKey('jwk', k.publicKey); return { kid, privateKey: k.privateKey, publicKey: k.publicKey, jwk: { kty: 'EC', crv: 'P-256', alg: 'ES256', use: 'sig', kid, x: jwk.x, y: jwk.y } }; }
async function signJws(key, payload, typ) { const h = b64uStr(JSON.stringify({ alg: 'ES256', kid: key.kid, typ })); const p = b64uStr(JSON.stringify(payload)); const sig = await subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key.privateKey, enc.encode(h + '.' + p)); return h + '.' + p + '.' + b64u(sig); }
async function verifyJws(token, jwks) {
  try {
    const [h, p, s] = token.split('.'); const header = JSON.parse(new TextDecoder().decode(b64uDec(h)));
    if (header.alg !== 'ES256') return { ok: false, detail: 'unsupported alg' };
    const jwk = jwks.find(k => k.kid === header.kid); if (!jwk) return { ok: false, detail: 'unknown kid ' + header.kid };
    const key = await subtle.importKey('jwk', { kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y, ext: true }, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    const ok = await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, b64uDec(s), enc.encode(h + '.' + p));
    if (!ok) return { ok: false, detail: 'signature does not verify against JWKS' };
    return { ok: true, payload: JSON.parse(new TextDecoder().decode(b64uDec(p))), detail: `ES256 signature valid (kid ${header.kid})` };
  } catch (e) { return { ok: false, detail: 'malformed JWS' }; }
}
const jwks = () => ({ keys: [S.keys.gw.jwk] });
const decodeJws = t => { try { const [h, p] = t.split('.'); return { header: JSON.parse(new TextDecoder().decode(b64uDec(h))), payload: JSON.parse(new TextDecoder().decode(b64uDec(p))) }; } catch (e) { return null; } };

// ---------------------------------------------------------------- audit ledger
const ACTION_TEXT = { search: 'searched the catalog', quote: 'received signed offers', plan: 'built fulfilment plans', candidates_filtered: 'filtered out unsuitable products', policy_decision: 'decided', approval_requested: 'requested human approval', approved: 'approved', rejected: 'rejected', modified: 'modified and approved', order_placed: 'placed the order', notified: 'notified the buyer', substitution_proposed: 'proposed a substitution', offer_expired: 'found an expired offer', price_changed: 'detected a price change', requote: 're-quoted offers', checkout_created: 'opened a checkout session', checkout_blocked: 'blocked the checkout', mandate_registered: 'registered a signed Intent Mandate', mandate_updated: 'updated the Intent Mandate', preferences_updated: 'updated the preference profile', manual_choice: 'chose a different product', kill_switch: 'changed the agent kill switch', standing_order_paused: 'paused standing-order auto-renew', event_intake: 'understood the event brief', event_planned: 'planned the event basket', event_rescaled: 're-scaled the event basket', reconciliation_recorded: 'recorded consumption after the event', delivery_feedback: 'recorded delivery feedback', recommendation_applied: 'applied a recommendation', data_exported: 'exported buyer data', data_deleted: 'deleted buyer data', offer_verified: 'verified a signed offer' };
const GENESIS = '0'.repeat(64);
async function evHash(ev) { const b = { ...ev }; delete b.hash; return sha256hex(canonical(b)); }
async function audit(a) {
  const prev = S.audit.length ? S.audit[S.audit.length - 1].hash : GENESIS;
  const ev = { seq: S.audit.length + 1, eventId: 'EV-' + (100000 + S.audit.length + 1), ts: a.ts || clock.iso(), traceId: a.traceId || null, buyerId: a.buyerId || null, actor: a.actor, action: a.action, inputs: a.inputs || {}, refs: a.refs || {}, decision: a.decision || null, ruleIds: a.ruleIds || [], reason: a.reason || '', prevHash: prev };
  ev.hash = await evHash(ev); S.audit.push(ev); return ev;
}
async function auditVerify() {
  let prev = GENESIS; let n = 0;
  for (const ev of S.audit) { n++; if (ev.prevHash !== prev) return { ok: false, checked: n, brokenAt: ev.seq, detail: `Event ${ev.seq}: prevHash does not link to event ${ev.seq - 1}` }; const h = await evHash(ev); if (h !== ev.hash) return { ok: false, checked: n, brokenAt: ev.seq, detail: `Event ${ev.seq}: content no longer matches its SHA-256 hash (edited after it was written)` }; prev = ev.hash; }
  return { ok: true, checked: n, head: prev, detail: `${n} events, chain intact` };
}
function tamper() { const ev = [...S.audit].reverse().find(e => e.action === 'policy_decision' && e.decision && e.decision !== 'AUTO') || S.audit[S.audit.length - 1]; S.tampered = { seq: ev.seq, original: clone(ev) }; ev.decision = 'AUTO'; ev.reason = ev.reason + ' (edited)'; return ev.seq; }
function untamper() { if (!S.tampered) return; const i = S.audit.findIndex(e => e.seq === S.tampered.seq); S.audit[i] = S.tampered.original; S.tampered = null; }
function sentence(ev) {
  const [kind, who] = ev.actor.includes(':') ? [ev.actor.split(':')[0], ev.actor.split(':').slice(1).join(':')] : ['', ev.actor];
  const whoL = kind === 'agent' ? 'Agent ' + who : kind === 'human' ? who : kind === 'system' ? (who === 'policy' ? 'Policy engine' : 'Gateway') : who;
  let s = whoL + ' ' + (ACTION_TEXT[ev.action] || ev.action.replace(/_/g, ' '));
  if (ev.decision) s += ': ' + ev.decision; return s;
}

// ---------------------------------------------------------------- mandates (signed by named human)
async function signMandate(bid, body, by) {
  const b = S.buyers[bid]; const now = clock.now();
  const m = clone(body); const admin = by || b.admin;
  Object.assign(m, { type: 'IntentMandate', buyerId: bid, issuedBy: { id: admin.id, name: admin.name, role: admin.role }, validFrom: clock.iso(now), validUntil: clock.iso(new Date(now.getTime() + (body.validDays || 90) * 864e5)), preferenceProfile: { id: S.profiles[bid].profileId, version: S.profiles[bid].version } });
  const jws = await signJws(S.keys.buyers[bid], m, 'mandate+jwt');
  return { mandate: m, jws };
}
async function registerMandate(bid, signed, reason, actorName) {
  const v = await verifyJws(signed.jws, [S.keys.buyers[bid].jwk]);
  if (!v.ok || canonical(v.payload) !== canonical(signed.mandate)) return { ok: false, detail: v.ok ? 'mandate body differs from signed payload' : v.detail };
  const prev = S.mandates[bid]; const versions = prev ? [...prev.versions, prev.current] : [];
  S.mandates[bid] = { current: signed, versions };
  await audit({ actor: 'human:' + (actorName || signed.mandate.issuedBy.name), action: prev ? 'mandate_updated' : 'mandate_registered', buyerId: bid, refs: { mandateId: signed.mandate.mandateId, version: signed.mandate.version }, reason: reason || `Intent Mandate v${signed.mandate.version} signed (ES256)` });
  return { ok: true, detail: v.detail };
}
async function mandateCheck(bid) {
  const s = S.mandates[bid]; if (!s) return [null, { ok: false, detail: 'missing' }];
  const v = await verifyJws(s.current.jws, [S.keys.buyers[bid].jwk]);
  if (!v.ok) return [null, { ok: false, detail: 'unsigned or signature invalid' }];
  if (clock.iso() > v.payload.validUntil) return [v.payload, { ok: false, detail: 'expired ' + v.payload.validUntil }];
  return [v.payload, { ok: true, detail: v.detail }];
}
const mandateOf = bid => S.mandates[bid] && S.mandates[bid].current.mandate;

// ---------------------------------------------------------------- trust: offers
const PRICE_TTL = 15, STOCK_TTL = 5;
const CHECKS = [['signature', 'Signature valid (ES256 vs JWKS)'], ['validity', 'Within validity window (price 15 min)'], ['freshness', 'Availability fresh (≤ 5 min) & confident'], ['binding', 'GTIN / SKU / unit / price match the signed claim'], ['status', 'Not revoked (status list)'], ['reverify', 'Live re-check: price & stock still hold']];
const BOUND = ['offerId', 'gtin', 'aimoSku', 'unit', 'packSize', 'unitsPerCase', 'unitPrice', 'currency'];
async function issueOffer(gtin, needBy, bid) {
  const p = BY_GTIN[gtin]; const now = clock.now(); const sched = BE.schedule(gtin); const stockNow = S.stock[gtin];
  const by = needBy || (sched[0] && sched[0].date); const qtyBy = by ? BE.availableBy(gtin, by) : stockNow; const inb = Math.max(0, qtyBy - stockNow);
  const conf = qtyBy <= 0 ? 0 : Math.round((Math.min(stockNow, qtyBy) * 0.97 + inb * 0.8) / qtyBy * 100) / 100;
  const today = clock.today(); const certs = p.certificates.map(c => ({ ...c, valid: c.validUntil >= today }));
  const subject = { offerId: rid('OF'), gtin, aimoSku: p.aimoSku, name: p.name, brand: p.brand, category: p.category, unit: p.unit, packSize: p.packSize, unitsPerCase: p.unitsPerCase, caseQty: p.caseQty, unitPrice: BE.price(gtin), currency: 'EUR', priceBasis: p.priceBasis, availability: { qtyAvailable: qtyBy, byDate: by || null, asOf: clock.iso(now), confidence: conf, schedule: sched }, delivery: { earliestDate: BE.earliest(gtin), cutoff: '14:00 EET, day before delivery', onTimeRate: p.onTimeRate }, origin: p.origin, attributes: { allergens: p.allergens, mayContain: p.mayContain, diet: p.diet }, certificates: certs, validFrom: clock.iso(now), validUntil: clock.iso(new Date(now.getTime() + PRICE_TTL * 60000)), digitalLink: digitalLink(p), trustLevel: certs.length && certs.every(c => c.valid) ? 'L2' : 'L1' };
  const vc = { '@context': ['https://www.w3.org/ns/credentials/v2', 'https://gateway.aimo.example/ns/offer/v1'], id: 'urn:aimo:offer:' + subject.offerId, type: ['VerifiableCredential', 'OfferAttestation'], issuer: 'did:web:gateway.aimo.example', validFrom: subject.validFrom, validUntil: subject.validUntil, credentialSubject: subject, credentialStatus: { id: 'https://gateway.aimo.example/v1/offers/status#' + subject.offerId, type: 'BitstringStatusListEntry', statusPurpose: 'revocation' } };
  const jws = await signJws(S.keys.gw, vc, 'vc+jwt');
  const offer = { ...subject, buyerId: bid, proof: { type: 'JsonWebSignature', format: 'vc+jwt', alg: 'ES256', kid: S.keys.gw.kid, jws } };
  S.offers[offer.offerId] = offer; return offer;
}
async function verifyOffer(offer, qty) {
  const now = clock.now(); const res = {};
  const v = await verifyJws((offer.proof || {}).jws || '', jwks().keys); res.signature = [v.ok, v.detail];
  const subj = v.ok ? v.payload.credentialSubject : {};
  if (v.ok) {
    const left = (new Date(subj.validUntil) - now) / 1000;
    res.validity = [left > 0, left > 0 ? `valid for ${Math.floor(left / 60)} min ${Math.floor(left % 60)} s` : `expired ${Math.floor(-left / 60)} min ago`];
    const age = (now - new Date(subj.availability.asOf)) / 1000; const conf = subj.availability.confidence;
    res.freshness = [age <= STOCK_TTL * 60 && conf >= 0.8, `stock read ${Math.floor(age / 60)} min ago, confidence ${conf.toFixed(2)}` + (age <= STOCK_TTL * 60 ? '' : ' — stale, live re-check required')];
    const mism = BOUND.filter(f => subj[f] !== offer[f]);
    res.binding = [!mism.length, mism.length ? `presented ${mism.join(', ')} differ from the signed claim` : 'presented fields match the signed payload'];
    const cur = BE.price(subj.gtin); const by = subj.availability.byDate || clock.today(); const avail = BE.availableBy(subj.gtin, by); const issues = [];
    if (Math.abs(cur - subj.unitPrice) > 1e-9) issues.push(`price now €${cur.toFixed(2)} (offer €${subj.unitPrice.toFixed(2)})`);
    if (qty && avail + 1e-9 < qty) issues.push(`only ${fq(avail, subj.unit)} available by ${by}`);
    res.reverify = [!issues.length, issues.length ? issues.join('; ') : 'price and stock confirmed live'];
  } else { for (const k of ['validity', 'freshness', 'binding', 'reverify']) res[k] = [false, 'not evaluated: signature failed']; }
  res.status = [!S.revoked[offer.offerId], S.revoked[offer.offerId] ? 'revoked: ' + S.revoked[offer.offerId] : 'not revoked'];
  const checks = CHECKS.map(([id, label]) => ({ id, label, ok: res[id][0], detail: res[id][1] }));
  return { offerId: offer.offerId, verified: checks.filter(c => c.id !== 'freshness').every(c => c.ok), checks, trustLevel: v.ok ? subj.trustLevel : 'L0' };
}

// ---------------------------------------------------------------- learning signals (from ProcessRecords)
function weeklyHistory(buyer) { const out = {}; for (const [key, weeks] of Object.entries(buyer.history || {})) { const p = BY_KEY[key]; const nz = weeks.filter(w => w > 0); if (p && nz.length) out[p.gtin] = { median8w: median(nz), weeks, nonZeroWeeks: nz.length }; } return out; }
function habitual(buyer, kind) { let best = null, vol = 0; for (const [key, weeks] of Object.entries(buyer.history || {})) { const p = BY_KEY[key]; if (p && p.kind === kind && sum(weeks) > vol) { best = p; vol = sum(weeks); } } return best; }
const _sigCache = {};
function computeSignals(bid) {
  const key = bid + ':' + S.processes.length + ':' + S.processes.filter(r => r.feedback).length;
  if (_sigCache[key]) return _sigCache[key];
  const buyer = S.buyers[bid]; const recs = S.processes.filter(r => r.buyerId === bid);
  const pairs = {}, changes = {}, products = {}, brands = {}, choices = {}, rules = {}, percover = {};
  for (const r of recs) {
    const fb = r.feedback || {}, dec = r.decision || {}; const rej = new Set((dec.modifications || []).filter(m => m.field === 'rejected').map(m => m.gtin));
    for (const s of r.outcome.substitutions || []) {
      const k = s.fromGtin + '>' + s.toGtin; const e = pairs[k] = pairs[k] || { fromGtin: s.fromGtin, toGtin: s.toGtin, fromName: s.fromName, toName: s.toName, n: 0, accepted: 0, rejected: 0, processIds: [] };
      let acc = fb.substituteAccepted; if (rej.has(s.toGtin) || r.outcome.status === 'rejected') acc = false; if (acc === undefined || acc === null) continue;
      e.n++; acc ? e.accepted++ : e.rejected++; e.processIds.push(r.processId);
      for (const c of s.changes || []) { const ce = changes[c] = changes[c] || { change: c, n: 0, accepted: 0 }; ce.n++; if (acc) ce.accepted++; }
    }
    if (['ordered', 'delivered', 'reconciled', 'partially_approved'].includes(r.outcome.status)) {
      for (const ln of r.lines || []) {
        const e = products[ln.gtin] = products[ln.gtin] || { gtin: ln.gtin, name: ln.name, brand: ln.brand, category: ln.category, supplierId: ln.supplierId, orders: 0, qtys: [], prices: [], onTimeN: 0, onTime: 0, fillN: 0, fillSum: 0, ratings: [], processIds: [] };
        e.orders++; e.qtys.push(ln.qty); e.prices.push(ln.unitPrice); e.processIds.push(r.processId);
        const lt = (fb.lateGtins || null); if (fb.onTime !== undefined && fb.onTime !== null) { e.onTimeN++; const ok = lt ? !lt.includes(ln.gtin) : fb.onTime; if (ok) e.onTime++; }
        if (fb.deliveredQty !== undefined && fb.deliveredQty !== null && r.outcome.qtyOrdered) { e.fillN++; e.fillSum += Math.min(1, fb.deliveredQty / r.outcome.qtyOrdered); }
        if (fb.rating) e.ratings.push(fb.rating);
        brands[ln.brand] = brands[ln.brand] || { brand: ln.brand, orders: 0 }; brands[ln.brand].orders++;
      }
    }
    if (dec.manualChoice) { const mc = dec.manualChoice; const k = mc.agentPick + '>' + mc.chosen; const e = choices[k] = choices[k] || { agentPick: mc.agentPick, chosen: mc.chosen, chosenName: BY_GTIN[mc.chosen].name, chosenBrand: BY_GTIN[mc.chosen].brand, agentPickName: BY_GTIN[mc.agentPick].name, n: 0, processIds: [] }; e.n++; e.processIds.push(r.processId); }
    for (const id of dec.ruleIds || []) {
      const e = rules[id] = rules[id] || { ruleId: id, fired: 0, approved: 0, rejected: 0, modified: 0, acknowledged: 0, latencies: [], deltas: [], processIds: [], categories: {} };
      e.fired++; e.processIds.push(r.processId);
      const act = dec.approverAction;
      if (act === 'approve') e.approved++; else if (act === 'reject') e.rejected++; else if (act === 'modify' || act === 'partial') e.modified++;
      else if (dec.outcome === 'NOTIFY' && !dec.manualCorrection && fb.substituteAccepted !== false) e.acknowledged++;
      if (dec.approvalLatencyMin != null) e.latencies.push(dec.approvalLatencyMin);
      for (const s of r.outcome.substitutions || []) e.deltas.push(s.priceDeltaPct);
      for (const ln of r.lines || []) e.categories[ln.category] = (e.categories[ln.category] || 0) + 1;
    }
    for (const c of r.consumption || []) {
      if (c.perCoverActual == null) continue; const k = (r.usageContext && r.usageContext.eventType) + '|' + c.need;
      const e = percover[k] = percover[k] || { eventType: r.usageContext && r.usageContext.eventType, need: c.need, name: c.name, unit: c.unit, planned: [], actual: [], dates: [], processIds: [] };
      e.planned.push(c.perCoverPlanned); e.actual.push(c.perCoverActual); e.dates.push(r.createdAt.slice(0, 10)); e.processIds.push(r.processId);
    }
  }
  const rate = (a, n) => n ? Math.round(a / n * 1000) / 1000 : null;
  const outPairs = Object.values(pairs).filter(e => e.n).map(e => ({ ...e, rate: rate(e.accepted, e.n), learnedValue: e.n >= 2 ? Math.round((0.5 + 0.5 * (2 * rate(e.accepted, e.n) - 1)) * 1000) / 1000 : 0.5 }));
  const wh = weeklyHistory(buyer);
  const outProducts = Object.values(products).map(e => ({ gtin: e.gtin, name: e.name, brand: e.brand, category: e.category, supplierId: e.supplierId, orders: e.orders, qtyMedian: median(e.qtys), qtyIQR: [quant(e.qtys, .25), quant(e.qtys, .75)], priceMedian: median(e.prices), priceLast: e.prices[e.prices.length - 1], prices: e.prices.slice(-12), onTime: e.onTime, onTimeN: e.onTimeN, onTimeRate: rate(e.onTime, e.onTimeN), fillRate: e.fillN ? Math.round(e.fillSum / e.fillN * 1000) / 1000 : null, avgRating: e.ratings.length ? Math.round(sum(e.ratings) / e.ratings.length * 100) / 100 : null, weeklyMedian8w: wh[e.gtin] ? wh[e.gtin].median8w : null, processIds: e.processIds.slice(-12) }));
  for (const [g, h] of Object.entries(wh)) if (!products[g]) { const p = BY_GTIN[g]; outProducts.push({ gtin: g, name: p.name, brand: p.brand, category: p.category, supplierId: p.origin.supplierId, orders: h.nonZeroWeeks, weeklyMedian8w: h.median8w, onTimeRate: null, onTimeN: 0, fillRate: null, avgRating: null, priceMedian: null, qtyMedian: h.median8w, qtyIQR: [null, null], processIds: [] }); }
  const outRules = Object.values(rules).map(e => ({ ...e, medianLatencyMin: median(e.latencies), p90LatencyMin: quant(e.latencies, .9) }));
  const outPc = Object.values(percover).map(e => ({ ...e, n: e.actual.length, perCoverActualMedian: median(e.actual.slice(-3)), perCoverPlannedMedian: median(e.planned.filter(x => x != null)) }));
  const dates = recs.map(r => r.createdAt).sort();
  const res = { buyerId: bid, period: { from: dates[0] && dates[0].slice(0, 10), to: dates.length && dates[dates.length - 1].slice(0, 10), processes: recs.length }, substitutionPairs: outPairs.sort((a, b) => b.n - a.n), changeTypes: Object.values(changes).map(e => ({ ...e, rate: rate(e.accepted, e.n) })), products: outProducts.sort((a, b) => b.orders - a.orders), brands: Object.values(brands).sort((a, b) => b.orders - a.orders), manualChoices: Object.values(choices).sort((a, b) => b.n - a.n), rules: outRules.sort((a, b) => a.ruleId.localeCompare(b.ruleId, 'en', { numeric: true })), perCover: outPc };
  _sigCache[key] = res; return res;
}
const productSignal = (sig, g) => sig ? sig.products.find(p => p.gtin === g) : null;
const pairSignal = (sig, a, b) => sig ? sig.substitutionPairs.find(p => p.fromGtin === a && p.toGtin === b) : null;
const everOrdered = (buyer, sig, g) => !!weeklyHistory(buyer)[g] || !!(productSignal(sig, g) || {}).orders;

// ---------------------------------------------------------------- planner
const variantText = vs => vs.map(v => v.replace(/_/g, '-')).join(', ') || 'standard';
function specDiff(p, prim) { if (p.kind !== prim.kind) return `${KIND_LABELS[p.kind] || p.kind} instead of ${KIND_LABELS[prim.kind] || prim.kind}`; const a = p.variant.filter(v => !prim.variant.includes(v)), b = prim.variant.filter(v => !p.variant.includes(v)); return `${variantText(a)} instead of ${variantText(b)}`; }
function substitutionMeta(p, prim) { const ch = []; if (p.brand !== prim.brand) ch.push('brand switch'); if (Math.abs(p.packSize - prim.packSize) > 1e-9) ch.push('pack size'); if ([...p.variant].sort().join() !== [...prim.variant].sort().join() || p.kind !== prim.kind) ch.push('spec change'); if ([...p.allergens, ...p.mayContain].sort().join() !== [...prim.allergens, ...prim.mayContain].sort().join()) ch.push('allergen profile'); if (p.category !== prim.category) ch.push('category change'); const d = prim.unitPrice ? (BE.price(p.gtin) - BE.price(prim.gtin)) / BE.price(prim.gtin) * 100 : 0; return { changes: ch, priceDeltaPct: r1(d) }; }
function describeChanges(p, prim, ch) { const o = []; for (const c of ch) { if (c === 'brand switch') o.push('brand ' + p.brand); else if (c === 'pack size') o.push(`${p.packSize} ${p.unit} packs`); else if (c === 'spec change') o.push(specDiff(p, prim)); else if (c === 'allergen profile') { const add = [...new Set([...p.allergens, ...p.mayContain])].filter(a => ![...prim.allergens, ...prim.mayContain].includes(a)); o.push(add.length ? 'adds allergen ' + add.join('/') : 'different allergen profile'); } else if (c === 'category change') o.push('category ' + p.category); } return o.join(', ') || 'same spec'; }

function planLine(ctx, req, needBy, choice, usage) {
  const { buyer, mandate, profile, signals } = ctx; const today = clock.today();
  const need = resolveNeed(req.text);
  const exclAll = new Set([...(mandate ? mandate.hardExclusions.allergens : []), ...(req.excludeAllergens || [])]);
  const dietReq = new Set([...need.diet, ...(mandate ? mandate.hardExclusions.diet : []), ...(req.diet || [])]);
  const hab = need.kind ? habitual(buyer, need.kind) : null;
  const qtyReq = +req.qty; const unitReq = req.unit || null; const notices = [];
  let leftoverUsed = 0;
  for (const lo of (ctx.leftovers || [])) {
    const lp = BY_GTIN[lo.gtin];
    if (lo.status === 'available' && need.kind && lp.kind === need.kind && need.variants.every(v => lp.variant.includes(v)) && need.diet.every(d => lp.diet.includes(d)) && lo.bestBefore >= needBy && lo.qty > 0) {
      const n = { type: 'leftover', leftoverId: lo.leftoverId, gtin: lo.gtin, qty: lo.qty, text: `${fq(lo.qty, lp.unit)} of ${lp.name} left from ${lo.sourceLabel || 'an earlier order'} (best-before ${dayLabel(lo.bestBefore)}).` };
      if (req.useLeftovers) { const use = Math.min(lo.qty, qtyReq - leftoverUsed); if (use > 0) { leftoverUsed += use; n.applied = use; n.text += ` Using ${fq(use, lp.unit)} first.`; } }
      notices.push(n);
    }
  }
  const qty = Math.max(0, qtyReq - leftoverUsed);
  const eligible = [], relaxed = [], excluded = [];
  for (const g of need.candidates) {
    const p = BY_GTIN[g]; let reason = null, code = null;
    const badAll = [...new Set([...p.allergens, ...p.mayContain])].filter(a => exclAll.has(a)).sort();
    const eff = effectiveProfile(profile, p.category, (buyer.site || {}).id);
    const [failed] = applyFilters(eff, p); const nb = neverBuy(profile, p);
    const blocked = mandate ? (mandate.substitution.blockedPairs || []) : [];
    if (need.kind && p.kind !== need.kind) { code = 'kind'; reason = `Not ${need.kindLabel} — it is ${KIND_LABELS[p.kind] || p.kind}`; }
    else if (badAll.length) { const c = badAll.filter(a => p.allergens.includes(a)), m = badAll.filter(a => !p.allergens.includes(a)); code = 'allergen'; reason = (c.length ? 'Contains ' + c.map(a => ALLERGEN_LABELS[a]).join(', ') : 'May contain ' + m.map(a => ALLERGEN_LABELS[a]).join(', ')) + (req.excludeAllergens && req.excludeAllergens.some(a => badAll.includes(a)) ? ' (guest allergy)' : ' (excluded by mandate)'); }
    else if ([...dietReq].some(d => !p.diet.includes(d))) { code = 'diet'; reason = 'Not ' + [...dietReq].filter(d => !p.diet.includes(d)).map(d => DIET_LABELS[d] || d).join(' / '); }
    else if (need.certs.length && !need.certs.every(c => p.certificates.some(x => x.label === c))) { code = 'certificate'; reason = 'Missing certificate ' + need.certs.join(', '); }
    else if (nb) { code = 'never_buy'; reason = nb; }
    else if (failed.length) { code = 'filter'; reason = 'Required filter: ' + failed.join('; '); }
    else if (unitReq && p.unit !== unitReq) { code = 'unit'; reason = `Sold per ${p.unit}, request is in ${unitReq}`; }
    else if (hab && blocked.some(b => b[0] === hab.gtin && b[1] === g)) { code = 'blocked_swap'; reason = `Swap from ${hab.name} blocked by mandate (kitchen rejected it)`; }
    else if (!BE.schedule(g).length) { code = 'out_of_stock'; reason = 'Out of stock, no inbound supply'; }
    if (reason) { excluded.push({ gtin: g, name: p.name, brand: p.brand, code, reason, unitPrice: BE.price(g), unit: p.unit, availByNeedBy: BE.availableBy(g, needBy) }); continue; }
    const miss = need.variants.filter(v => !p.variant.includes(v));
    (miss.length ? relaxed : eligible).push({ p, group: needGroupId(p), eff, specRelaxed: !!miss.length, missingVariant: miss });
  }
  const strictCover = sum(eligible.map(i => BE.availableBy(i.p.gtin, needBy)));
  if (strictCover < qty && relaxed.length) { notices.push({ type: 'relaxed', text: `Not enough ${variantText(need.variants)} ${need.kindLabel} by ${dayLabel(needBy)} (${fq(strictCover, unitReq || '')}); also considering other ${need.kindLabel} as substitutes.` }); eligible.push(...relaxed); }
  else for (const i of relaxed) excluded.push({ gtin: i.p.gtin, name: i.p.name, brand: i.p.brand, code: 'spec', reason: `Not ${variantText(i.missingVariant)} (fallback only if needed)`, unitPrice: BE.price(i.p.gtin), unit: i.p.unit, availByNeedBy: BE.availableBy(i.p.gtin, needBy) });
  const prices = eligible.map(i => BE.price(i.p.gtin)); const minPrice = prices.length ? Math.min(...prices) : 0;
  const prefBrands = new Set(mandate ? mandate.preferredBrands : []); const favs = new Set(profile.favourites || []);
  const ranked = [];
  for (const i of eligible) {
    const p = i.p, eff = i.eff, g = p.gtin, w = eff.weights; const price = BE.price(g); const avail = BE.availableBy(g, needBy); const sched = BE.schedule(g); const ps = productSignal(signals, g); const reasons = [];
    const spec = i.specRelaxed ? 0.4 : (hab && !hab.variant.every(v => p.variant.includes(v)) ? 0.7 : 1.0);
    let ontime = p.onTimeRate; if (ps && ps.onTimeN >= 3 && ps.onTimeRate != null) { ontime = ps.onTimeRate; reasons.push({ kind: 'learned', text: `On time ${ps.onTime}/${ps.onTimeN} for you (history)` }); }
    const cover = qty ? Math.min(1, avail / qty) : 1; const delivery = ontime * cover;
    let quality = (p.qualityGrade - 1) / 4; if (ps && ps.avgRating) quality = (quality + (ps.avgRating - 1) / 4) / 2;
    const sust = sustainabilityScore(p, today); const brand = prefBrands.has(p.brand) ? 1 : 0;
    const caseOver = qty ? Math.ceil(qty / p.caseQty - 1e-9) * p.caseQty - qty : 0; const packMode = !!req.allowPacks && qty > 0 && p.unitsPerCase > 1 && caseOver > Math.max(0.1 * qty, p.packSize); const ou = packMode ? p.packSize : p.caseQty;
    const fullCases = qty ? Math.ceil(qty / ou - 1e-9) : 0; const over = fullCases * ou - qty; const packFit = qty ? Math.max(0, 1 - (over / qty) * 10) : 1;
    let learned = 0.5, ltxt = null;
    if (hab && hab.gtin === g) { const whh = weeklyHistory(buyer)[g]; learned = 1; ltxt = whh ? `Your usual product (${fq(whh.median8w, p.unit)}/week)` : 'Your usual product'; }
    else { const pr = hab ? pairSignal(signals, hab.gtin, g) : null; if (pr && pr.n >= 2) { learned = pr.learnedValue; ltxt = `Kitchen ${pr.rate >= 0.5 ? 'accepted' : 'rejected'} this swap ${pr.rate >= 0.5 ? pr.accepted : pr.rejected}/${pr.n} times`; } const mc = signals ? signals.manualChoices.find(m => m.chosen === g && m.n >= 2) : null; if (mc && learned < 0.9) { learned = 0.9; ltxt = `You picked this over the agent's choice ${mc.n} times`; } }
    const values = { spec, price: price ? minPrice / price : 0, delivery, quality, sustainability: sust, brand, packFit, learned };
    const breakdown = CRITERIA.map(c => ({ criterion: c, label: CRITERIA_LABELS[c], weight: w[c], value: Math.round(values[c] * 10000) / 10000, contribution: Math.round(w[c] * values[c] * 10000) / 10000 }));
    if (ltxt) { const dl = Math.round(w.learned * (learned - 0.5) * 1000) / 1000; reasons.push({ kind: 'learned', text: `${ltxt} (${dl >= 0 ? '+' : ''}${dl.toFixed(3)})` }); }
    const bonuses = []; const [, prefOk] = applyFilters(eff, p); for (const l of prefOk) bonuses.push({ label: l + ' preferred', value: PREFERRED_BONUS }); if (favs.has(g)) bonuses.push({ label: 'Favourite', value: FAVOURITE_BONUS });
    const score = Math.round((sum(breakdown.map(b => b.contribution)) + sum(bonuses.map(b => b.value))) * 10000) / 10000;
    if (usage && usage.date && sched.length && addDays(sched[0].date, p.shelfLifeDays || 365) < addDays(usage.date, 1)) reasons.push({ kind: 'risk', text: `Shelf-life risk: ${p.shelfLifeDays} d vs use on ${dayLabel(usage.date)}` });
    ranked.push({ gtin: g, name: p.name, brand: p.brand, category: p.category, kind: p.kind, needGroup: i.group, unit: p.unit, packSize: p.packSize, unitsPerCase: p.unitsPerCase, caseQty: ou, orderUnit: packMode ? 'pack' : 'case', unitPrice: price, availByNeedBy: avail, schedule: sched, earliest: sched.length ? sched[0].date : null, lateOnly: avail <= 0, specRelaxed: i.specRelaxed, certificates: p.certificates.map(c => c.label), origin: p.origin, qualityGrade: p.qualityGrade, allergens: p.allergens, mayContain: p.mayContain, diet: p.diet, score, breakdown, bonuses, reasons, favourite: favs.has(g), scope: eff.scope, preset: eff.preset, fullCases, fullOverage: Math.round(over * 1000) / 1000, onTimeRate: ontime });
  }
  const ngp = profile.needGroups || {};
  const okey = it => { if (choice && it.gtin === choice) return [0, 0]; const np = ngp[it.needGroup] || {}; if (!it.lateOnly && np.pinned === it.gtin) return [1, 0]; const fb = np.fallback || []; if (!it.lateOnly && fb.includes(it.gtin)) return [2, fb.indexOf(it.gtin)]; return [3, 0]; };
  ranked.sort((a, b) => { const ka = okey(a), kb = okey(b); return ka[0] - kb[0] || ka[1] - kb[1] || (a.specRelaxed - b.specRelaxed) || b.score - a.score; });
  ranked.forEach((it, idx) => { const k = okey(it); it.rank = idx + 1; it.tier = idx < 3 ? TIERS[idx] : 'ALSO'; it.rankReason = { 0: 'Your choice', 1: 'Pinned default', 2: `Fallback #${k[1] + 1}`, 3: idx === 0 ? 'Highest score' : 'Score' }[k[0]]; });
  const prim = ranked.length ? BY_GTIN[ranked[0].gtin] : null;
  for (const it of ranked) { it._short = it.availByNeedBy < qty; it.tradeoff = tradeoff(it, ranked[0], BY_GTIN[it.gtin], prim, needBy); Object.assign(it, prim && it.gtin !== prim.gtin ? substitutionMeta(BY_GTIN[it.gtin], prim) : { changes: [], priceDeltaPct: 0 }); }
  const favAvail = ranked.find(it => it.favourite && !it.lateOnly);
  const line = { lineId: req.lineId, text: req.text, label: req.label || req.text, qty: qtyReq, qtyAfterLeftovers: qty, unit: unitReq || (prim ? prim.unit : null), need: { kind: need.kind, kindLabel: need.kindLabel, variants: need.variants, diet: [...dietReq].sort(), certs: need.certs, excludedAllergens: [...exclAll].sort(), needGroup: ranked.length ? ranked[0].needGroup : null, needGroupLabel: ranked.length ? needGroupLabel(ranked[0].needGroup) : null }, habitualGtin: hab ? hab.gtin : null, primaryGtin: prim ? prim.gtin : null, manualChoice: choice || null, favouriteAvailable: favAvail ? favAvail.gtin : null, ranked, excluded, notices, searched: need.candidates.length, qtyAdjustment: req.qtyAdjustment || null };
  line.plans = buildPlans(line, needBy, qty);
  return line;
}
function tradeoff(it, best, p, prim, needBy) {
  if (it === best) { const bits = []; if (['Pinned default', 'Your choice'].includes(it.rankReason)) bits.push(it.rankReason.toLowerCase()); bits.push(...[...it.breakdown].sort((a, b) => b.contribution - a.contribution).slice(0, 2).map(b => b.label.toLowerCase())); const cover = it.lateOnly ? 'available only after the need-by date' : it._short ? `only ${fq(it.availByNeedBy, it.unit)} by ${dayLabel(needBy)} (partial)` : 'covers the full quantity'; return `Top pick: ${bits.join(', ')}; ${cover}.`; }
  const d = []; if (Math.abs(it.availByNeedBy - best.availByNeedBy) > 1e-9) d.push(`${fq(it.availByNeedBy, it.unit)} by ${dayLabel(needBy)} vs ${fq(best.availByNeedBy, best.unit)}`);
  const dp = best.unitPrice ? (it.unitPrice - best.unitPrice) / best.unitPrice * 100 : 0; if (Math.abs(dp) >= 0.05) d.push(`${dp > 0 ? '+' : '−'}${Math.abs(dp).toFixed(1)}% per ${it.unit}`);
  if (it.brand !== best.brand) d.push(`other brand (${it.brand})`); if (Math.abs(it.packSize - best.packSize) > 1e-9) d.push(`${it.packSize} ${it.unit} packs`);
  if (prim && ([...p.variant].sort().join() !== [...prim.variant].sort().join() || p.kind !== prim.kind)) d.push(specDiff(p, prim));
  if (it.lateOnly && it.earliest) d.push('first delivery ' + dayLabel(it.earliest));
  const s = d.slice(0, 4).join(', ') || 'similar on all criteria'; return s.charAt(0).toUpperCase() + s.slice(1) + '.';
}
function mkLine(line, it, cases, qtyNeeded, delivery, primGtin, idx) {
  const p = BY_GTIN[it.gtin]; const qty = Math.round(cases * it.caseQty * 1000) / 1000; const over = Math.round(Math.max(0, qty - qtyNeeded) * 1000) / 1000; const prim = BY_GTIN[primGtin]; const sub = it.gtin !== primGtin; const meta = sub ? substitutionMeta(p, prim) : { changes: [], priceDeltaPct: 0 };
  return { lineId: `${line.lineId}-${idx}`, requestLineId: line.lineId, requestLabel: line.label, offerId: null, gtin: it.gtin, name: it.name, brand: it.brand, category: it.category, kind: it.kind, unit: it.unit, packSize: it.packSize, unitsPerCase: it.unitsPerCase, caseQty: it.caseQty, orderUnit: it.orderUnit || 'case', cases, qty, overage: over, unitPrice: it.unitPrice, lineTotal: r2(qty * it.unitPrice), deliveryDate: delivery, role: sub ? 'substitute' : 'primary', substituteFor: sub ? { gtin: prim.gtin, name: prim.name } : null, changes: meta.changes, priceDeltaPct: meta.priceDeltaPct, changeText: sub ? describeChanges(p, prim, meta.changes) : '', tier: it.tier, rank: it.rank, certificates: it.certificates, supplierId: p.origin.supplierId, roundingNote: `${cases} ${it.orderUnit === 'pack' ? 'pack' : 'case'}${cases > 1 ? 's' : ''} × ${fq(it.caseQty, it.unit)} = ${fq(qty, it.unit)}` + (over > 1e-9 ? ` (+${fq(over, it.unit)} over)` : ''), qtyAdjustment: line.qtyAdjustment || null, favouriteAvailable: line.favouriteAvailable };
}
const deliverOn = (it, needBy) => it.earliest <= needBy ? needBy : it.earliest;
function buildPlans(line, needBy, qty) {
  const R = line.ranked; if (!R.length || qty <= 0) return [];
  const prim = R[0], pg = prim.gtin, plans = [];
  const finish = (strategy, title, lines) => { const by = sum(lines.filter(l => l.deliveryDate <= needBy).map(l => l.qty)); const tot = sum(lines.map(l => l.qty)); return { strategy, title, lines, total: r2(sum(lines.map(l => l.lineTotal))), coverage: { requested: qty, byNeedBy: Math.min(by, qty), total: tot, pct: r1(Math.min(1, tot / qty) * 100), pctByNeedBy: r1(Math.min(1, by / qty) * 100) }, deliveryDates: [...new Set(lines.map(l => l.deliveryDate))].sort(), splitCount: lines.length, overage: r2(sum(lines.map(l => l.overage))) }; };
  const same = (a, b) => JSON.stringify(a.lines.map(l => [l.gtin, l.cases, l.deliveryDate])) === JSON.stringify(b.lines.map(l => [l.gtin, l.cases, l.deliveryDate]));
  if (prim.availByNeedBy >= qty) { plans.push(finish('single', `${prim.brand} — full quantity`, [mkLine(line, prim, prim.fullCases, qty, deliverOn(prim, needBy), pg, 1)])); return labelPlans(plans, needBy); }
  let lines = [], rest = qty, idx = 1;
  for (const it of R) { if (rest <= 1e-9) break; if (it.lateOnly) continue; const maxc = Math.floor(it.availByNeedBy / it.caseQty + 1e-9), needc = Math.ceil(rest / it.caseQty - 1e-9), c = Math.min(maxc, needc); if (c <= 0) continue; lines.push(mkLine(line, it, c, rest, deliverOn(it, needBy), pg, idx++)); rest -= c * it.caseQty; }
  if (lines.length) { let strat = lines.length > 1 ? 'split_products' : (lines[0].gtin === pg ? 'single' : 'substitute'); let title = lines.length > 1 ? 'Split across products' : `${lines[0].brand} — ${rest > 1e-9 ? 'partial' : 'full quantity'}`; if (rest > 1e-9) { if (lines.length === 1) { strat = 'partial'; title = 'Partial — best available by need-by'; } else title = 'Split across products (partial)'; } plans.push(finish(strat, title, lines)); }
  for (const it of R.slice(1)) { if (it.lateOnly || it.availByNeedBy < qty) continue; const c = finish('substitute', `Substitute — ${it.brand}, full quantity`, [mkLine(line, it, it.fullCases, qty, deliverOn(it, needBy), pg, 1)]); if (!plans.some(p => same(c, p))) plans.push(c); break; }
  if (sum(prim.schedule.map(s => s.qty)) >= qty) {
    lines = []; rest = qty; idx = 1;
    for (const s of prim.schedule) { if (rest <= 1e-9) break; const maxc = Math.floor(s.qty / prim.caseQty + 1e-9), needc = Math.ceil(rest / prim.caseQty - 1e-9), c = Math.min(maxc, needc); if (c <= 0) continue; lines.push(mkLine(line, prim, c, rest, s.date <= needBy ? needBy : s.date, pg, idx++)); rest -= c * prim.caseQty; }
    const c = finish('split_dates', `${prim.brand} — split across delivery dates`, lines);
    if ((lines.length > 1 || (lines.length && lines[0].deliveryDate > needBy)) && !plans.some(p => same(c, p))) plans.push(c);
  }
  return labelPlans(plans.slice(0, 3), needBy);
}
function labelPlans(plans, needBy) { plans.forEach((p, i) => { p.label = 'P' + (i + 1); p.summary = p.lines.map(l => `${fq(l.qty, l.unit)} ${l.brand} ${dayLabel(l.deliveryDate)}`).join(' + ') + ` — ${money(p.total)}, ${Math.round(p.coverage.pctByNeedBy)}% by ${dayLabel(needBy)}`; }); return plans; }
function combine(lines) {
  if (lines.length === 1) return lines[0].plans.map(p => ({ ...p }));
  const chosen = lines.filter(l => l.plans.length).map(l => l.plans[0]); if (!chosen.length) return [];
  const all = chosen.flatMap(p => p.lines); const total = r2(sum(all.map(x => x.lineTotal))); const dates = [...new Set(all.map(x => x.deliveryDate))].sort();
  const missing = lines.filter(l => !l.plans.length).length;
  return [{ label: 'P1', strategy: 'multi_line', title: `${chosen.length}-line order`, lines: all, total, coverage: { pct: missing ? 0 : Math.min(...chosen.map(p => p.coverage.pct)), pctByNeedBy: missing ? 0 : Math.min(...chosen.map(p => p.coverage.pctByNeedBy)) }, deliveryDates: dates, splitCount: all.length, overage: r2(sum(all.map(x => x.overage))), summary: `${all.length} lines — ${money(total)}, delivery ${dates.map(dayLabel).join(', ')}` }];
}

// ---------------------------------------------------------------- policy engine
function policyEvaluate(ctx) {
  const out = [], suppressed = []; const m = ctx.mandate, buyer = ctx.buyer, lines = ctx.lines; const issuer = m ? m.issuedBy.name : '—';
  const fire = (id, vals, lineIds, outcome) => out.push({ ruleId: id, title: RULES[id].title, outcome: outcome || RULES[id].outcome, reason: render(RULES[id].reason, vals), lineIds: lineIds || [], side: RULES[id].side });
  if (ctx.killSwitch && ctx.killSwitch.on) fire('V3', { agent: ctx.agentId, by: ctx.killSwitch.by || 'Valio Aimo ops' });
  const mc = ctx.mandateCheck || { ok: !!m, detail: 'missing' }; if (!mc.ok) fire('R0', { detail: mc.detail });
  if (m) {
    const excl = new Set(m.hardExclusions.allergens), dietReq = new Set(m.hardExclusions.diet), sub = m.substitution, silent = new Set(sub.silentCategories || []), allowed = new Set(m.allowedCategories);
    const profile = ctx.profile, signals = ctx.signals;
    for (const ln of lines) {
      const p = BY_GTIN[ln.gtin];
      const lineExcl = new Set([...excl, ...(ln.excludeAllergens || [])]);
      const bad = [...new Set([...p.allergens, ...p.mayContain])].filter(a => lineExcl.has(a)).sort(); const miss = [...dietReq, ...(ln.diet || [])].filter(d => !p.diet.includes(d));
      if (bad.length || miss.length) fire('R1', { product: p.name, violations: [...bad.map(a => ALLERGEN_LABELS[a].toLowerCase()), ...miss.map(x => (DIET_LABELS[x] || x) + ' requirement')].join(', '), issuer: ln.excludeAllergens && ln.excludeAllergens.length ? 'guest allergy list' : issuer }, [ln.lineId]);
      if (!allowed.has(p.category)) fire('R9', { product: p.name, category: p.category }, [ln.lineId]);
      if (ln.role === 'substitute' && ln.substituteFor) {
        const prim = BY_GTIN[ln.substituteFor.gtin]; const delta = ln.priceDeltaPct || 0; const ch = ln.changes || []; const why = [];
        if (delta > sub.maxPriceDeltaPct + 1e-9) why.push(`price delta above the ${sub.maxPriceDeltaPct}% tolerance`);
        if (ch.includes('category change') && sub.sameCategoryOnly !== false) why.push('category changed');
        if (ch.includes('brand switch') && sub.allowBrandSwitch === false) why.push('brand switches not allowed');
        if (ch.includes('pack size') && sub.allowPackSizeChange === false) why.push('pack-size changes not allowed');
        if (ch.includes('spec change')) why.push('product spec differs'); if (ch.includes('allergen profile')) why.push('allergen/diet profile changed');
        if ((sub.blockedPairs || []).some(b => b[0] === prim.gtin && b[1] === p.gtin)) why.push('this swap is blocked by the mandate');
        const vals = { sub: p.name, primary: prim.name, changes: ln.changeText || ch.join(', ') || 'same spec', delta: (delta >= 0 ? '+' : '−') + Math.abs(delta).toFixed(1) + '%', unit: p.unit, max: sub.maxPriceDeltaPct + '%', why: why.join(' and ') };
        if (why.length) fire('R5', vals, [ln.lineId]);
        else if (silent.has(p.category)) suppressed.push({ ruleId: 'R4', lineIds: [ln.lineId], reason: `Silent swap: mandate v${m.version} pre-approves in-tolerance swaps in ${p.category}.` });
        else fire('R4', vals, [ln.lineId]);
      }
      if (!everOrdered(buyer, signals, p.gtin)) fire('R8', { product: p.name, buyer: buyer.name }, [ln.lineId]);
      if (profile) { const eff = effectiveProfile(profile, p.category, (buyer.site || {}).id); const [failed] = applyFilters(eff, p); const nb = neverBuy(profile, p); for (const f of [...failed, ...(nb ? [nb] : [])]) fire('R11', { product: p.name, filter: f, version: profile.version }, [ln.lineId], profile.filterViolationOutcome || 'APPROVE'); }
      if (ln.favouriteAvailable && ln.favouriteAvailable !== p.gtin && ln.role === 'primary') fire('R12', { product: p.name, favourite: BY_GTIN[ln.favouriteAvailable].name }, [ln.lineId]);
      const whh = weeklyHistory(buyer)[p.gtin]; if (whh && ln.qty > D.rules.params.sanityMultiplier * whh.median8w) fire('V2', { qty: fq(ln.qty, p.unit), product: p.name, mult: D.rules.params.sanityMultiplier, median: fq(whh.median8w, p.unit) }, [ln.lineId]);
      const adj = ln.qtyAdjustment; if (adj && adj.baseline) { const d = (adj.planned - adj.baseline) / adj.baseline * 100; if (Math.abs(d) > 10) fire('R13', { product: adj.label || p.name, planned: fq(adj.planned, p.unit), baseline: fq(adj.baseline, p.unit), delta: (d >= 0 ? '+' : '−') + Math.abs(d).toFixed(0) + '%', why: adj.why || 'history' }, [ln.lineId], Math.abs(d) > 30 ? 'APPROVE' : 'NOTIFY'); }
    }
    const total = ctx.total, ev = ctx.event;
    const lim = ev ? (m.limits.perEventEUR || m.limits.perOrderEUR) : m.limits.perOrderEUR;
    if (total > lim + 1e-9) fire('R2', { total: money(total), limit: money(lim) + (ev ? ' per event' : ''), issuer });
    if ((ctx.mtd || 0) + total > m.limits.perMonthEUR + 1e-9) fire('R3', { mtd: money(ctx.mtd || 0), total: money(total), limit: money(m.limits.perMonthEUR) });
    if (ev && ev.guests && m.limits.perGuestEUR) { const pg = total / ev.guests; if (pg > m.limits.perGuestEUR + 1e-9) fire('R14', { perGuest: money(pg), target: money(m.limits.perGuestEUR), event: ev.name || 'the event' }); }
    for (const rl of ctx.requestLines || []) {
      const ls = lines.filter(l => l.requestLineId === rl.lineId); if (!ls.length) continue;
      const got = sum(ls.map(l => l.qty)); const unit = ls[0].unit;
      if (got + 1e-9 < rl.qty) fire('R6', { detail: `Only ${fq(got, unit)} of ${fq(rl.qty, unit)} ${rl.label || ''} can be supplied (${Math.round(got / rl.qty * 100)}% coverage).` }, ls.map(l => l.lineId));
      else if (new Set(ls.map(l => l.gtin)).size > 1) { const cats = new Set(ls.map(l => l.category)); if ([...cats].every(c => silent.has(c))) suppressed.push({ ruleId: 'R6', lineIds: ls.map(l => l.lineId), reason: `Split to 100% in ${[...cats].join(', ')} pre-approved by mandate v${m.version}.` }); else fire('R6', { detail: `Split across ${new Set(ls.map(l => l.gtin)).size} products to reach exactly 100% (${fq(got, unit)}${rl.label ? ' ' + rl.label : ''}).` }, ls.map(l => l.lineId), 'NOTIFY'); }
      for (const l of ls) if (l.deliveryDate > rl.needBy) fire('R7', { qty: fq(l.qty, l.unit), product: l.name, date: dayLabel(l.deliveryDate), needBy: dayLabel(rl.needBy) }, [l.lineId]);
    }
    const so = ctx.standingOrder; if (so && so.median) { const d = (so.qty - so.median) / so.median * 100; if (Math.abs(d) > D.rules.params.driftThresholdPct) fire('R10', { so: so.id, qty: fq(so.qty, so.unit), drift: (d >= 0 ? '+' : '−') + Math.abs(d).toFixed(0) + '%', median: fq(so.median, so.unit) }); }
    if ((buyer.openInvoicesEUR || 0) + total > (buyer.creditLimitEUR || 1e12)) fire('V1', { open: money(buyer.openInvoicesEUR), total: money(total), limit: money(buyer.creditLimitEUR), buyer: buyer.name });
  }
  let outcome = 'AUTO'; for (const d of out) if (RANK[d.outcome] > RANK[outcome]) outcome = d.outcome;
  const ids = [...new Set(out.map(d => d.ruleId))].sort((a, b) => a[0] === b[0] ? +a.slice(1) - +b.slice(1) : a < b ? -1 : 1);
  const top = [...new Set(out.filter(d => d.outcome === outcome).map(d => d.ruleId))].join(', ');
  const summary = { AUTO: 'Within mandate — the agent may order without human involvement.', NOTIFY: `Allowed; the buyer is notified (${top}).`, APPROVE: `Needs one human approval (${top}).`, BLOCK: `Blocked (${top}); the agent cannot proceed.` }[outcome];
  return { outcome, decisions: out, suppressed, ruleIds: ids, summary };
}

G.AimoCore = { D, P, BY_GTIN, BY_KEY, ALLERGENS, ALLERGEN_LABELS, DIET_LABELS, RULES, RANK, KIND_LABELS, CRITERIA, CRITERIA_LABELS, PRESETS, PRESET_LABELS, CHECKS,
  clone, r2, r1, sum, median, quant, money, money0, fq, render, rid, mulberry32, canonical, sha256hex, clock, addDays, weekday, dayLabel, deliveryDay, isoTs,
  resolveNeed, searchCatalog, needGroupId, needGroupLabel, digitalLink, defaultProfile, normaliseW, effectiveProfile, filterCheck, applyFilters, neverBuy, sustainabilityScore,
  baseState, BE, genKey, signJws, verifyJws, decodeJws, jwks, audit, auditVerify, tamper, untamper, sentence, signMandate, registerMandate, mandateCheck, mandateOf,
  issueOffer, verifyOffer, weeklyHistory, habitual, computeSignals, productSignal, pairSignal, everOrdered, planLine, buildPlans, combine, policyEvaluate,
  get S() { return S; }, set S(v) { S = v; for (const k in _sigCache) delete _sigCache[k]; } };
})(typeof window !== 'undefined' ? window : globalThis);
