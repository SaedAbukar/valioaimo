/* Aimo kitchen assistant — chat-first front end.
 * Every chat turn runs the gateway playbook (POST /v1/chat); each step's output comes back as cards.
 * When no gateway is reachable (e.g. the page is published as an artifact), it plays recorded
 * gateway runs (window.AIMO_REPLAYS, made by scripts/record_replays.py). */
(function () {
'use strict';

// ------------------------------------------------------------------ icons (24px, stroke)
const ICONS = {
  chat: '<path d="M5 18.5V6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v7a2.5 2.5 0 0 1-2.5 2.5H9l-4 2.5Z"/>',
  board: '<rect x="4" y="4" width="4.5" height="16" rx="1.5"/><rect x="10" y="4" width="4.5" height="10" rx="1.5"/><rect x="16" y="4" width="4" height="13" rx="1.5"/>',
  insights: '<path d="M4 19h16"/><path d="M6 15l4-4 3 3 5-6"/><circle cx="18" cy="8" r="1"/>',
  settings: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  store: '<path d="M4 9.5 5.5 4h13L20 9.5"/><path d="M4 9.5c0 1.4 1.1 2.5 2.7 2.5S9.3 10.9 9.3 9.5c0 1.4 1.2 2.5 2.7 2.5s2.7-1.1 2.7-2.5c0 1.4 1.1 2.5 2.6 2.5S20 10.9 20 9.5"/><path d="M5.5 12v8h13v-8M10 20v-4.5h4V20"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
  chevl: '<path d="m14 6-6 6 6 6"/>',
  chevr: '<path d="m10 6 6 6-6 6"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  people: '<circle cx="9" cy="8" r="3"/><path d="M3.5 19c.6-3 2.8-4.5 5.5-4.5s4.9 1.5 5.5 4.5"/><circle cx="17" cy="9" r="2.3"/><path d="M15.5 14.6c2.4-.2 4.4 1 5 3.9"/>',
  pin: '<path d="M12 21s6-5.4 6-10.5A6 6 0 0 0 6 10.5C6 15.6 12 21 12 21Z"/><circle cx="12" cy="10.5" r="2.2"/>',
  more: '<circle cx="6" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18" cy="12" r="1.3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  mic: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V20.5"/>',
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  eye: '<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/>',
  star: '<path d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4 7.2 18.9l.9-5.4L4.2 9.7l5.4-.8Z"/>',
  basket: '<path d="M4 9h16l-1.6 9.2A2 2 0 0 1 16.4 20H7.6a2 2 0 0 1-2-1.8Z"/><path d="M9 9l3-5 3 5"/>',
  question: '<circle cx="12" cy="12" r="8.5"/><path d="M9.8 9.6a2.3 2.3 0 0 1 4.4.9c0 1.6-2.2 2-2.2 3.4"/><circle cx="12" cy="16.8" r=".6"/>',
  stop: '<circle cx="12" cy="12" r="8.5"/><path d="M7 7l10 10"/>',
  truck: '<path d="M3 7h11v9H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>',
  pick: '<rect x="4" y="5" width="16" height="4" rx="2"/><rect x="4" y="11" width="16" height="4" rx="2"/><path d="M8 19h8"/>',
  ok: '<path d="M12 3.5l7 3v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9v-5Z"/><path d="M9 12l2 2 4-4"/>',
  tip: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z"/>',
  clip: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4h6v3H9zM9 12h6M9 16h4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
};
const ic = (n) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`;
const CARD_ICON = { understood: 'eye', question: 'question', favourites: 'star', basket: 'basket', choice: 'pick', needs_ok: 'ok', cant_do: 'stop', delivery: 'truck', how_did_it_go: 'clip', tip: 'tip' };
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const KITCHENS = {
  'BUY-POHJOLA': { name: 'Hotelli Pohjola', person: 'Jari Lehtonen', role: 'Executive chef', initials: 'JL',
    ideas: [['Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. 12 vegan, 8 gluten-free, 1 nut allergy.', 'An event, start to finish'],
      ['I need 1,000 L lactose-free milk by Monday', 'A big top-up of a favourite'],
      ['Pikkujoulut 120 hengelle: kinkku, rosolli, laatikot, riisipuuro. 6 vegaania.', 'In Finnish, with one thing missing']] },
  'BUY-KOULU': { name: 'Kaarela School Kitchens', person: 'Sanna Koskinen', role: 'Catering manager', initials: 'SK',
    ideas: [['60 L oat drink by Monday', 'Nut-free kitchen, usual product is late']] },
  'BUY-UUSI': { name: 'Kahvila Uusi', person: 'Mira Nieminen', role: 'Owner, new kitchen', initials: 'MN',
    ideas: [['100 L milk by Wednesday', 'No history yet, real Valio Aimo products']] },
};
const GALA = KITCHENS['BUY-POHJOLA'].ideas[0][0];

// ------------------------------------------------------------------ state
const S = {
  mode: 'live', buyerId: 'BUY-POHJOLA', view: 'chat', convId: null, convs: {}, chats: [], board: null,
  panel: null, busy: false, uiDone: {}, usage: {}, tips: {}, recording: false,
};
const store = { get(k, d) { try { const v = localStorage.getItem('aimo.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('aimo.' + k, JSON.stringify(v)); } catch (e) { /* private mode */ } } };

// ------------------------------------------------------------------ API: live gateway or replay
const Live = {
  async j(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) throw Object.assign(new Error(data.message || 'Something went wrong'), { data });
    return data;
  },
  chat: (cid, text, buyerId) => Live.j('/v1/chat', { conversationId: cid, text, buyerId }),
  action: (cid, action, payload) => Live.j(`/v1/chat/${cid}/actions`, { action, payload }),
  approve: async (sid, cid, ok) => { const r = await Live.j(`/v1/approvals/${sid}`, { ok, by: 'Laura Virtanen' }); return r; },
  chats: (bid) => Live.j('/v1/chats?buyerId=' + bid),
  chatGet: (cid) => Live.j('/v1/chats/' + cid),
  board: (bid) => Live.j('/v1/board?buyerId=' + bid),
  insights: (bid) => Live.j('/v1/insights?buyerId=' + bid),
  settings: (bid) => Live.j('/v1/settings?buyerId=' + bid),
  playbook: () => Live.j('/v1/playbook'),
  reset: () => Live.j('/v1/demo/reset', {}),
  history: (bid, p) => Live.j('/v1/orders/history?' + new URLSearchParams(Object.assign({ buyerId: bid }, p))),
  orderDetail: (bid, id) => Live.j(`/v1/orders/history/${encodeURIComponent(id)}?buyerId=${bid}`),
  activity: (sid) => Live.j(`/v1/orders/${sid}/activity`),
  wrapped: (bid, site) => Live.j(`/v1/insights/wrapped?buyerId=${bid}${site ? '&siteId=' + site : ''}`),
  ask: (bid, prompt, filters, site) => Live.j('/v1/insights/ask', { buyerId: bid, prompt, filters, siteId: site || null }),
  kitchens: (bid) => Live.j('/v1/kitchens?buyerId=' + bid),
};

const Replay = (() => {
  const R = window.AIMO_REPLAYS || { scripts: [], insights: {}, settings: {} };
  const convs = {};   // id -> {id, buyerId, title, thread, cands: [scriptIdx], cursor, board}
  let n = 0;
  const words = (t) => new Set(String(t).toLowerCase().match(/[a-zåäö0-9]+/g) || []);
  const sim = (a, b) => { const A = words(a), B = words(b); let x = 0; A.forEach((w) => B.has(w) && x++); return x / Math.max(1, Math.min(A.size, B.size)); };
  const now = () => new Date().toISOString();
  function pub(c) { return { id: c.id, buyerId: c.buyerId, title: c.title, thread: c.thread, sessionIds: [c.id] }; }
  function step(c, match) {
    const ok = c.cands.filter((i) => { const st = R.scripts[i].steps[c.cursor]; return st && match(st); });
    if (!ok.length) return null;
    c.cands = ok;
    const st = R.scripts[ok[0]].steps[c.cursor++];
    c.board = st.board; c.title = st.title;
    const cards = JSON.parse(JSON.stringify(st.cards)).map((k) => Object.assign(k, { sessionId: c.id }));
    c.thread.push({ role: 'assistant', cards, at: now() });
    return cards;
  }
  function offScript(c, text) {
    const ideas = (KITCHENS[c.buyerId] || KITCHENS['BUY-POHJOLA']).ideas;
    const card = { id: 'demo-' + (n++), type: 'question', title: 'Try one of these', text: 'This preview plays real gateway runs. Pick an example to see it.',
      chips: [], numbers: [], options: ideas.map(([t, sub], i) => ({ id: 'ex' + i, label: t.length > 60 ? t.slice(0, 58) + '…' : t, sub, send: t })),
      actions: [], why: ['Run the app locally (make run) to try your own words.'], items: [], sessionId: c.id };
    c.thread.push({ role: 'assistant', cards: [card], at: now() });
    return [card];
  }
  return {
    available: () => R.scripts.length > 0,
    data: R,
    async chat(cid, text, buyerId) {
      let c = convs[cid];
      if (!c || c.cursor >= R.scripts[c.cands[0]].steps.length || R.scripts[c.cands[0]].steps[c.cursor].kind !== 'say') {
        const scored = R.scripts.map((s, i) => [i, s.buyerId === buyerId && !s.id.startsWith('gala-next') || (s.id === 'gala-next' && /150|12\.12/.test(text)) ? sim(text, s.steps[0].text) : 0]);
        const best = Math.max(...scored.map((x) => x[1]));
        c = { id: 'CHAT-R' + (n++), buyerId, title: 'New chat', thread: [], cands: scored.filter((x) => x[1] === best && best >= 0.45).map((x) => x[0]), cursor: 0, board: null };
        convs[c.id] = c;
      }
      c.thread.push({ role: 'user', text, at: now() });
      const cards = c.cands.length ? step(c, (st) => st.kind === 'say') : offScript(c, text);
      if (c.title === 'New chat') c.title = text.slice(0, 40);
      return { conversation: pub(c), cards: cards || offScript(c, text) };
    },
    async action(cid, action, payload) {
      const c = convs[cid];
      const key = payload && (payload.productId || (payload.value != null ? String(payload.value) : null));
      const cards = step(c, (st) => st.kind === 'act' && st.action === action && (!st.key || !key || st.key === key)) || [];
      return { conversation: pub(c), cards };
    },
    async approve(sid, cid) { return Replay.action(cid, 'approve', {}); },
    async chats(bid) { return { chats: Object.values(convs).filter((c) => c.buyerId === bid).reverse().map((c) => ({ id: c.id, title: c.title })) }; },
    async chatGet(cid) { return pub(convs[cid]); },
    async board(bid) {
      const cols = ['planning', 'waiting', 'ordered', 'delivered', 'done'].map((id) => ({ id, label: { planning: 'Planning', waiting: 'Waiting for OK', ordered: 'Ordered', delivered: 'Delivered', done: 'Done' }[id], items: [] }));
      for (const c of Object.values(convs)) {
        if (c.buyerId !== bid || !c.board) continue;
        for (const col of c.board.columns) for (const it of col.items) cols.find((x) => x.id === col.id).items.push(Object.assign({}, it, { conversationId: c.id, id: c.id }));
      }
      return { columns: cols, count: cols.reduce((a, x) => a + x.items.length, 0) };
    },
    async insights(bid) { return R.insights[bid] || { statements: [], chart: { values: [] }, tips: [] }; },
    async settings(bid) { return R.settings[bid]; },
    async playbook() { return R.playbook; },
    async history(bid, p) {
      let rows = ((R.extra || {}).history || {})[bid] || [];
      if (p.q) { const q = p.q.toLowerCase(); rows = rows.filter((o) => [o.event, o.site, o.key].some((x) => String(x || '').toLowerCase().includes(q))); }
      if (p.siteId) rows = rows.filter((o) => o.siteId === p.siteId);
      const page = +p.page || 1, size = +p.size || 50;
      return { orders: rows.slice((page - 1) * size, page * size), total: rows.length, page, size };
    },
    async orderDetail(bid, id) { return (((R.extra || {}).details || {})[bid] || {})[id] || { id, lines: [] }; },
    async activity() { return { activity: [] }; },
    async wrapped(bid, site) { return ((R.extra || {}).wrapped || {})[bid + '|' + (site || '')] || { cards: [] }; },
    async kitchens(bid) { return ((R.extra || {}).kitchens || {})[bid]; },
    async ask(bid, prompt) {
      const asks = ((R.extra || {}).asks || {})[bid] || [];
      const scored = asks.map((a) => [a, sim(prompt, a.prompt)]).sort((x, y) => y[1] - x[1]);
      if (scored.length && scored[0][1] >= 0.5) return scored[0][0].answer;
      return { offline: true, examples: asks.map((a) => a.prompt) };
    },
    async seed() {
      const r = await Replay.chat(null, GALA, 'BUY-POHJOLA');
      await Replay.action(r.conversation.id, 'order', {});
      return r.conversation.id;
    },
  };
})();

let API = Live;

// ------------------------------------------------------------------ helpers
const $ = (sel, el = document) => el.querySelector(sel);
const app = () => document.getElementById('app');
function toast(msg) {
  const t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 3200);
}
const conv = () => S.convs[S.convId];
const allCards = () => (conv() ? conv().thread.flatMap((m) => m.cards || []) : []);

// ------------------------------------------------------------------ render: shell
function render() {
  const k = KITCHENS[S.buyerId];
  const waiting = S.board ? (S.board.columns.find((c) => c.id === 'waiting') || { items: [] }).items.length : 0;
  const nav = [['chat', 'Chat', 'chat'], ['orders', 'Orders', 'board'], ['insights', 'Insights', 'insights'], ['settings', 'Kitchens', 'store']];
  app().className = 'app' + (S.panel ? ' panel-open' : '');
  app().innerHTML = `
  <aside class="side" aria-label="Main">
    <div class="brand"><div class="dot">A</div><div>Aimo<small>Kitchen assistant</small></div></div>
    <button class="new-chat" data-go="new">${ic('plus')} New chat</button>
    <nav class="nav">${nav.map(([v, l, i]) => `<button data-go="${v}" ${S.view === v ? 'aria-current="page"' : ''}>${ic(i)} ${l}${v === 'orders' && waiting ? `<span class="badge">${waiting}</span>` : ''}</button>`).join('')}</nav>
    <div class="recent-h">Recent chats</div>
    <div class="recent">${S.chats.map((c) => `<button data-chat="${c.id}" ${c.id === S.convId && S.view === 'chat' ? 'aria-current="true"' : ''}>${esc(c.title)}</button>`).join('') || '<span class="muted" style="padding:8px 12px;font-size:15px">No chats yet</span>'}</div>
    <button class="who" data-go="settings"><span class="av">${k.initials}</span><span><b>${esc(k.person)}</b><span>${esc(k.name)}</span></span></button>
  </aside>
  <main class="main">
    <header class="topbar"><b>${esc(S.view === 'chat' ? (conv() ? conv().title : 'New chat') : { orders: 'Orders', insights: 'Insights', settings: 'Kitchens' }[S.view])}</b>
      ${S.view === 'chat' ? `<button class="ibtn" data-go="new" aria-label="New chat">${ic('plus')}</button>` : ''}</header>
    <div class="view" id="view"></div>
    ${S.view === 'chat' ? composer() : ''}
  </main>
  ${S.panel ? `<div class="scrim" data-close></div><aside class="panel" role="dialog" aria-label="${esc(S.panel.title)}"><div class="panel-h"><h2>${esc(S.panel.title)}</h2><button class="ibtn" data-close aria-label="Close">${ic('close')}</button></div><div class="panel-b">${S.panel.html}</div></aside>` : ''}
  <nav class="tabbar" aria-label="Main">${[['chat', 'Chat', 'chat'], ['orders', 'Orders', 'board'], ['insights', 'Insights', 'insights'], ['settings', 'Kitchens', 'store']].map(([v, l, i]) => `<button data-go="${v}" ${S.view === v ? 'aria-current="page"' : ''}><span class="pip">${ic(i)}</span>${l}${v === 'orders' && waiting ? `<span class="badge">${waiting}</span>` : ''}</button>`).join('')}</nav>`;
  renderView();
}

function renderView() {
  const v = $('#view');
  if (!v) return;
  if (S.view === 'chat') v.innerHTML = chatView();
  if (S.view === 'orders') v.innerHTML = window.AimoOrders.view();
  if (S.view === 'insights') { v.innerHTML = window.AimoInsights.view(); window.AimoInsights.after(); }
  if (S.view === 'settings') { v.innerHTML = window.AimoKitchens.view(); window.AimoKitchens.after(); }
  if (S.view === 'chat') v.scrollTop = v.scrollHeight;
}

function composer() {
  const ph = conv() ? 'Reply or change something…' : 'What do you need? e.g. Gala for 180 on Saturday';
  return `<div class="composer-zone"><form class="composer" id="composer">
    <label for="msg" class="sr" style="position:absolute;left:-9999px">Message</label>
    <textarea id="msg" rows="1" placeholder="${esc(ph)}" ${S.busy ? 'disabled' : ''}></textarea>
    <button type="button" class="ibtn ${S.recording ? 'rec' : ''}" id="mic" aria-label="${S.recording ? 'Stop listening' : 'Speak'}">${ic('mic')}</button>
    <button type="submit" class="ibtn send" id="send" aria-label="Send" disabled>${ic('send')}</button>
  </form><div class="hint">Answers come as cards. Tap “Why?” on any card for the details.</div></div>`;
}

// ------------------------------------------------------------------ chat
function chatView() {
  const c = conv();
  if (!c || !c.thread.length) {
    const k = KITCHENS[S.buyerId];
    return `<div class="wrap"><div class="empty"><h1>Hi ${esc(k.person.split(' ')[0])}, what do you need?</h1>
      <p>Tell me an event or an order in your own words. I start from your favourites and what worked last time.</p>
      <div class="ideas">${k.ideas.map(([t, sub]) => `<button class="idea" data-send="${esc(t)}">${ic('chat')}<span>${esc(t)}<small>${esc(sub)}</small></span></button>`).join('')}</div></div></div>`;
  }
  // one-time actions on cards from earlier turns are spent; viewing actions stay
  const lastAsst = c.thread.map((m, i) => (m.role === 'assistant' ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
  const html = c.thread.map((m, i) => (m.role === 'user'
    ? `<div class="msg-user">${esc(m.text)}</div>`
    : `<div class="turn">${(m.cards || []).map((k) => cardHtml(k, i < lastAsst)).join('')}</div>`)).join('');
  return `<div class="wrap"><div class="thread">${html}${S.busy ? `<div class="typing" role="status"><i></i>${esc(S.busyLabel || 'Working on it')}</div>` : ''}</div></div>`;
}

const VIEW_ACTIONS = new Set(['see_items', 'track']);
function cardHtml(k, past) {
  let done = S.uiDone[k.id];
  if (past && !done && (k.options || []).length) done = { label: '' };
  const nums = k.numbers && k.numbers.length ? `<div class="nums num">${k.numbers.map((n) => `<div><b>${esc(n.value)}</b><span>${esc(n.label)}</span></div>`).join('')}</div>` : '';
  const chips = k.chips && k.chips.length ? `<div class="chips">${k.chips.map((c) => `<span class="chip ${c.status}" ${c.status === 'assumed' ? 'title="My guess"' : ''}>${esc(c.label)}</span>`).join('')}</div>` : '';
  let opts = '';
  if (k.options && k.options.length) {
    opts = `<div class="opts">${k.options.map((o, i) => `<button class="opt ${done && done.pick === o.id ? 'picked' : ''}" data-card="${k.id}" data-opt="${i}" ${done ? 'disabled' : ''}>
      <b>${esc(o.label)}</b>${o.tag ? `<span class="tag">${esc(o.tag)}</span>` : '<span></span>'}${o.sub || o.why ? `<small>${esc([o.sub, o.why].filter(Boolean).join(' · '))}</small>` : ''}</button>`).join('')}</div>`;
  }
  let usage = '';
  if (k.type === 'how_did_it_go') {
    const sel = S.usage[k.id] || {};
    usage = `<div class="usage">${k.items.map((r) => `<div class="urow"><span>${esc(r.label)}</span><span class="seg" role="group" aria-label="${esc(r.label)}">${r.choices.map((ch) => `<button data-usage="${k.id}" data-need="${esc(r.need)}" data-val="${ch.id}" aria-pressed="${(sel[r.need] || 'all') === ch.id}" ${done ? 'disabled' : ''}>${esc(ch.label)}</button>`).join('')}</span></div>`).join('')}</div>`;
  }
  let acts = '';
  if (done && done.label) acts = `<span class="done-note">${ic('check')} ${esc(done.label)}</span>`;
  else if (done) acts = '';
  else acts = (k.actions || []).filter((a) => !past || VIEW_ACTIONS.has(a.id)).map((a, i) => `<button class="btn ${a.primary ? 'primary' : ''}" data-card="${k.id}" data-act="${i}">${esc(a.label)}</button>`).join('');
  const why = k.why && k.why.filter(Boolean).length ? `<button class="why-link" data-why="${k.id}" aria-expanded="${!!S.uiDone['why:' + k.id]}">Why?</button>` : '';
  const whyList = S.uiDone['why:' + k.id] ? `<ul class="why">${k.why.filter(Boolean).map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '';
  return `<article class="card" data-type="${k.type}" id="c-${k.id}">
    <div class="card-h"><span class="ic">${ic(CARD_ICON[k.type] || 'chat')}</span>${esc(k.title)}</div>
    ${k.text ? `<div class="card-t">${esc(k.text)}</div>` : ''}${nums}${chips}${opts}${usage}
    ${acts || why ? `<div class="acts">${acts}${why}</div>` : ''}${whyList}</article>`;
}

function findCard(id) { return allCards().find((c) => c.id === id); }

async function send(text) {
  text = text.trim();
  if (!text || S.busy) return;
  const c = conv();
  if (c) c.thread.push({ role: 'user', text });
  else { S.pending = { id: 'tmp', thread: [{ role: 'user', text }], title: text.slice(0, 40) }; S.convs.tmp = S.pending; S.convId = 'tmp'; }
  await run(() => API.chat(c ? c.id : null, text, S.buyerId), ['Reading your request', 'Checking your favourites', 'Building the basket', 'Checking your rules']);
}

async function run(fn, labels) {
  S.busy = true; S.busyLabel = labels[0]; renderView();
  let li = 0; const timer = setInterval(() => { li = Math.min(li + 1, labels.length - 1); S.busyLabel = labels[li]; const t = $('.typing'); if (t) t.lastChild.textContent = S.busyLabel; }, 450);
  try {
    const r = await fn();
    applyConv(r.conversation);
  } catch (e) {
    toast(e.message || 'Could not reach the kitchen assistant.');
    if (conv() && conv().id === 'tmp') { delete S.convs.tmp; S.convId = null; }
  } finally {
    clearInterval(timer); S.busy = false;
    await refresh();
  }
}

function applyConv(c) {
  if (!c) return;
  delete S.convs.tmp;
  S.convs[c.id] = c; S.convId = c.id;
  store.set('conv', c.id);
}

async function refresh() {
  try {
    const [ch, b] = await Promise.all([API.chats(S.buyerId), API.board(S.buyerId)]);
    S.chats = ch.chats; S.board = b;
  } catch (e) { /* offline */ }
  render();
  if (S.panel && S.panel.kind === 'order') openOrder(S.panel.id, true);
}

async function onCardAction(cardId, idx) {
  const k = findCard(cardId); const a = k.actions[idx];
  const id = a.id;
  if (id === 'ack') { S.uiDone[cardId] = { label: a.label }; return renderView(); }
  if (id === 'change') { S.uiDone[cardId] = { label: 'Tell me what to change below' }; render(); const m = $('#msg'); m.placeholder = 'e.g. now 200 guests, or a different date'; m.focus(); return; }
  if (id === 'see_items') return openItems(k);
  if (id === 'track') { const it = boardItems().find((x) => x.order && x.order.orderId === (a.payload || {}).orderId) || boardItems().find((x) => x.conversationId === S.convId); return it ? openOrder(it.id) : null; }
  if (id === 'not_now') { S.uiDone[cardId] = { label: 'Kept in Planning' }; return renderView(); }
  const payload = Object.assign({}, a.payload || {}, { sessionId: k.sessionId });
  if (id === 'save_usage') payload.entries = S.usage[cardId] || {};
  const labels = { order: 'Placing the order', send_for_ok: 'Sending for OK', apply_tip: 'Changing the amounts', ignore_tip: 'Noted', use_alternative: 'Checking the safe choice', save_usage: 'Saving' };
  S.uiDone[cardId] = { label: { order: 'Ordered', send_for_ok: 'Sent for OK', apply_tip: 'Applied', ignore_tip: 'Ignored', use_alternative: 'Using the safe choice', save_usage: 'Saved' }[id] || a.label };
  await run(() => API.action(S.convId, id, payload), [labels[id] || 'Working on it', 'Checking your rules']);
}

async function onOption(cardId, i) {
  const k = findCard(cardId); const o = k.options[i];
  if (o.send) return send(o.send);
  if (k.type === 'question') {
    S.uiDone[cardId] = { label: o.label, pick: o.id };
    return run(() => API.action(S.convId, 'answer', { field: o.field, value: o.value, sessionId: k.sessionId }), ['Got it', 'Checking your favourites', 'Building the basket']);
  }
  if (k.type === 'choice') {
    S.uiDone[cardId] = { label: 'Picked', pick: o.id };
    return run(() => API.action(S.convId, 'pick', Object.assign({ sessionId: k.sessionId }, o.payload)), ['Locking the price', 'Checking your rules']);
  }
}

// ------------------------------------------------------------------ panel
function openPanel(kind, title, html, id) { S.panel = { kind, title, html, id }; S.lastFocus = document.activeElement; render(); const b = $('.panel [data-close]'); if (b) b.focus(); }
function closePanel() { S.panel = null; render(); if (S.lastFocus && document.body.contains(S.lastFocus)) S.lastFocus.focus(); }
const SRC = { favourites: 'Favourite', similar_orders: 'Worked last time', discover: 'New', learned_quantities: 'Learned', leftovers: 'In stock' };
function itemsHtml(groups) {
  return groups.map((g) => `<section><div class="day-h">${esc(g.day)}</div>${g.lines.map((l) => `<div class="item"><span>${esc(l.name)}${l.source ? `<span class="src">${SRC[l.source] || ''}</span>` : ''}</span><b class="num">${esc(l.qty || '')}${l.price ? ' · ' + esc(l.price) : ''}</b>${l.why ? `<small>${esc(l.why)}</small>` : ''}</div>`).join('')}</section>`).join('');
}
function openItems(k) { openPanel('items', k.title, itemsHtml(k.items || []) + (k.why && k.why.length ? `<ul class="why">${k.why.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '')); }
const boardItems = () => (S.board ? S.board.columns.flatMap((c) => c.items) : []);
function openOrder(id, quiet) {
  const it = boardItems().find((x) => x.id === id);
  if (!it) { if (quiet) { S.panel = null; render(); } return; }
  const order = ['planning', 'waiting', 'ordered', 'delivered', 'done'];
  const pos = order.indexOf(it.status);
  let acts = '';
  if (it.status === 'waiting') acts = `<p class="muted" style="margin:0">Demo: you are now ${esc(it.approval ? it.approval.approver.name : 'the approver')}.</p><div class="acts"><button class="btn primary" data-approve="${it.id}" data-conv="${it.conversationId}">OK, order it</button><button class="btn" data-decline="${it.id}" data-conv="${it.conversationId}">Not now</button></div>`;
  if (it.status === 'ordered') acts = `<div class="acts"><button class="btn" data-delivered="${it.conversationId}">Mark as delivered (demo)</button></div>`;
  if (it.status === 'delivered') acts = `<div class="acts"><button class="btn primary" data-openchat="${it.conversationId}">Tell me how it went</button></div>`;
  const html = `<div class="stepper" aria-label="${esc(it.statusLabel)}">${order.map((s, i) => `<i class="${i <= pos ? 'on' : ''}"></i>`).join('')}</div>
    <div><span class="pill ${it.status}">${esc(it.statusLabel)}</span></div>
    <dl class="kv"><dt>What</dt><dd>${esc(it.subtitle)}</dd>${it.totalLabel ? `<dt>Total</dt><dd class="num">${esc(it.totalLabel)}</dd>` : ''}
    ${(it.deliveries || []).map((d) => `<dt>Delivery</dt><dd>${esc(d.label)} ${esc(d.window)}</dd>`).join('')}</dl>
    ${acts}${itemsHtml(it.items || [])}
    <div class="acts"><button class="btn text" data-openchat="${it.conversationId}">Open the chat</button></div>`;
  if (quiet) { S.panel = { kind: 'order', title: it.title, html, id }; render(); } else openPanel('order', it.title, html, id);
}

// ------------------------------------------------------------------ orders
function ticket(it) {
  return `<button class="ticket" data-order="${it.id}"><b>${esc(it.title)}</b><small>${esc(it.subtitle)}</small><span class="row"><span class="pill ${it.status}">${esc(it.statusLabel)}</span><span class="num">${esc(it.totalLabel || '')}</span></span></button>`;
}
function ordersView() {
  const b = S.board || { columns: [] };
  return `<div class="wrap wide"><div class="page-h"><h1>Orders</h1><span class="muted">${esc(KITCHENS[S.buyerId].name)}</span></div>
    <div class="board">${b.columns.map((c) => `<section class="col"><h2>${esc(c.label)} <span>${c.items.length}</span></h2>${c.items.map(ticket).join('') || '<div class="col-empty">Nothing here</div>'}</section>`).join('')}</div>
    <div class="group-list">${b.columns.filter((c) => c.items.length).map((c) => `<section><h2>${esc(c.label)} <span class="muted">${c.items.length}</span></h2><div class="tickets">${c.items.map(ticket).join('')}</div></section>`).join('') || '<p class="muted">No orders yet. Start a chat and they show up here.</p>'}</div></div>`;
}

// ------------------------------------------------------------------ insights
async function loadInsights() {
  const d = await API.insights(S.buyerId);
  const ch = d.chart || { values: [] };
  let chart = '';
  if (ch.values && ch.values.length) {
    const W = 640, H = 200, L = 36, Rr = 14, T = 14, B = 30, max = 12;
    const x = (i) => L + i * (W - L - Rr) / (ch.values.length - 1);
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const pts = ch.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const last = ch.values.length - 1;
    chart = `<div class="chart"><h2>${esc(ch.title)}, share of food ordered</h2>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(ch.title)} fell from ${ch.values[0]}% to ${ch.values[last]}%">
      ${[0, 4, 8, 12].map((v) => `<line x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}" stroke="var(--outline)" stroke-width="1"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`).join('')}
      <polygon points="${x(0)},${y(0)} ${pts} ${x(last)},${y(0)}" fill="var(--primary-soft)" opacity=".7"/>
      <polyline points="${pts}" fill="none" stroke="var(--primary)" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${x(last)}" cy="${y(ch.values[last])}" r="5" fill="var(--primary)"/>
      <text x="${x(last) - 8}" y="${y(ch.values[last]) - 12}" text-anchor="end" style="fill:var(--fg);font-weight:700">${ch.values[last]}%</text>
      ${ch.labels.map((l, i) => (i % 2 === 1 || i === last ? `<text x="${x(i)}" y="${H - 8}" text-anchor="${i === last ? 'end' : 'middle'}">${i === last ? 'This week' : 'w/c ' + esc(l)}</text>` : '')).join('')}
      </svg></div>`;
  }
  S.insightsHtml = `<div class="wrap"><div class="page-h"><h1>Insights</h1><span class="muted">${esc(KITCHENS[S.buyerId].name)}</span></div>
    <div class="statements">${d.statements.map((s) => `<div class="statement ${s.tone}"><b>${esc(s.text)}</b>${s.detail ? `<span>${esc(s.detail)}</span>` : ''}</div>`).join('')}</div>
    ${chart}
    ${d.tips && d.tips.length ? `<div class="section"><h2>Tips</h2><div class="statements">${d.tips.map((t, i) => `<article class="card" data-type="tip"><div class="card-h"><span class="ic">${ic('tip')}</span>Tip</div><div class="card-t">${esc(t.text)}</div>${t.tipId ? `<div class="acts">${S.tips[t.tipId] ? `<span class="done-note">${ic('check')} ${esc(S.tips[t.tipId])}</span>` : `<button class="btn primary" data-tip="${t.tipId}" data-v="Will apply next time">Apply</button><button class="btn" data-tip="${t.tipId}" data-v="Ignored">Ignore</button>`}</div>` : ''}</article>`).join('')}</div></div>` : ''}</div>`;
  if (S.view === 'insights') renderView();
}

// ------------------------------------------------------------------ settings / more
async function loadSettings() {
  const [d, pb] = await Promise.all([API.settings(S.buyerId), S.playbook ? Promise.resolve(S.playbook) : API.playbook()]);
  S.playbook = pb;
  const theme = store.get('theme', 'system');
  const eur = (v) => (v == null ? '—' : '€' + Number(v).toLocaleString('en-US'));
  S.settingsHtml = `<div class="wrap"><div class="page-h"><h1>Settings</h1></div>
    <div class="section"><h2>Recent chats</h2><div class="list" id="m-recent">${S.chats.slice(0, 5).map((c) => `<button class="li" data-chat="${c.id}"><span>${esc(c.title)}</span></button>`).join('') || '<div class="li muted">No chats yet</div>'}</div></div>
    <div class="section"><h2>Kitchen</h2><div class="list">${Object.entries(KITCHENS).map(([id, k]) => `<button class="li" data-buyer="${id}"><span class="radio ${id === S.buyerId ? 'on' : ''}"></span><span>${esc(k.name)}<small>${esc(k.person)} · ${esc(k.role)}</small></span></button>`).join('')}</div></div>
    <div class="section"><h2>Favourites</h2><div class="list">${d.favourites.map((f) => `<div class="li"><span>${esc(f.name)}</span>${f.pinned ? '<small>Always first</small>' : ''}</div>`).join('') || '<div class="li"><span>None yet<small>I remember what you pick, so this fills up by itself.</small></span></div>'}</div></div>
    <div class="section"><h2>Spending limits</h2><div class="list">${d.limits.map((l) => `<div class="li"><span>${esc(l.label)}</span><b class="num">${eur(l.value)}</b></div>`).join('')}</div></div>
    <div class="section"><h2>Never order</h2><div class="list"><div class="li"><span>${d.allergens.length ? d.allergens.map(esc).join(', ') : 'Nothing blocked'}<small>Products that contain or may contain these are never ordered.</small></span></div></div></div>
    <div class="section"><h2>People who OK orders</h2><div class="list">${d.approvers.map((a) => `<div class="li"><span>${esc(a.name)}<small>${esc(a.role)}</small></span></div>`).join('')}</div></div>
    <div class="section"><h2>Appearance</h2><div class="seg-wide">${['system', 'light', 'dark'].map((t) => `<button class="btn ${theme === t ? 'primary' : ''}" data-theme-set="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div></div>
    <div class="section"><h2>How it works</h2><div class="list steps">${(pb.steps || []).map((s) => `<div class="li"><span>${esc(s.name)}<small>${esc(s.does)}</small></span></div>`).join('')}</div>
      <p class="muted" style="font-size:14px">Every assistant follows these steps, version ${esc(pb.version || '')}. Prices: ${S.mode === 'live' ? (d.liveApi ? 'live from Valio Aimo' : 'demo prices until the Valio Aimo key is set') : 'recorded demo run'}.</p></div>
    ${S.mode === 'live' ? `<div class="section"><h2>Demo</h2><div class="acts"><button class="btn" data-reset>Start the demo again</button></div></div>` : ''}</div>`;
  if (S.view === 'settings') renderView();
}

function applyTheme() {
  const t = store.get('theme', 'system');
  if (t === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t);
}

// ------------------------------------------------------------------ voice (local app only)
let rec = null;
function toggleMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast('Voice works in Chrome or Edge in the full app. Type here for now.');
  if (S.recording && rec) { rec.stop(); return; }
  try {
    rec = new SR(); rec.lang = /[äö]/.test(($('#msg') || {}).value || '') ? 'fi-FI' : 'en-GB'; rec.interimResults = true;
    rec.onresult = (e) => { const m = $('#msg'); m.value = Array.from(e.results).map((r) => r[0].transcript).join(' '); $('#send').disabled = !m.value.trim(); };
    rec.onend = () => { S.recording = false; const m = $('#msg') && $('#msg').value; render(); if (m) { $('#msg').value = m; $('#send').disabled = false; } };
    rec.onerror = () => toast('I could not hear you. Check the microphone permission.');
    rec.start(); S.recording = true; render();
  } catch (e) { toast('The microphone is not available here.'); }
}

// ------------------------------------------------------------------ events
document.addEventListener('click', async (e) => {
  const t = e.target.closest('button, [data-close]');
  if (!t) return;
  const d = t.dataset;
  if ('close' in d) return closePanel();
  for (const m of [window.AimoOrders, window.AimoInsights, window.AimoKitchens]) if (m && await m.click(t, d)) return;
  if (d.go) {
    if (d.go === 'new') { S.convId = null; S.view = 'chat'; S.panel = null; return render(); }
    S.view = d.go; S.panel = null; render();
    if (d.go === 'insights') window.AimoInsights.load();
    if (d.go === 'settings') window.AimoKitchens.load();
    if (d.go === 'orders') { refresh(); window.AimoOrders.load(); }
    return;
  }
  if (d.chat) { if (!S.convs[d.chat]) applyConv(await API.chatGet(d.chat)); S.convId = d.chat; S.view = 'chat'; S.panel = null; return render(); }
  if (d.send) return send(d.send);
  if (d.act) return onCardAction(d.card, +d.act);
  if (d.opt) return onOption(d.card, +d.opt);
  if (d.why) { S.uiDone['why:' + d.why] = !S.uiDone['why:' + d.why]; return renderView(); }
  if (d.usage) { const m = S.usage[d.usage] = S.usage[d.usage] || {}; m[d.need] = d.val; return renderView(); }
  if (d.order) return window.AimoOrders.open(d.order);
  if (d.approve || d.decline) {
    const sid = d.approve || d.decline; const cid = d.conv;
    S.panel = null; S.view = 'chat'; S.convId = cid;
    if (d.decline) { toast('Kept in Planning'); return render(); }
    return run(() => API.approve(sid, cid, true).then((r) => r.conversation ? r : API.chatGet(cid).then((c) => ({ conversation: c }))), ['Placing the order']);
  }
  if (d.delivered) { S.panel = null; S.view = 'chat'; S.convId = d.delivered; return run(() => API.action(d.delivered, 'delivered', {}), ['Opening the check-in']); }
  if (d.openchat) { if (!S.convs[d.openchat]) applyConv(await API.chatGet(d.openchat)); S.convId = d.openchat; S.view = 'chat'; S.panel = null; return render(); }
  if (d.buyer) { S.buyerId = d.buyer; store.set('buyer', d.buyer); S.convId = null; S.panel = null; window.AimoOrders.reset(); window.AimoInsights.reset(); await refresh(); window.AimoKitchens.load(); return; }
  if (d.themeSet) { store.set('theme', d.themeSet); applyTheme(); renderView(); return; }
  if (d.tip) { S.tips[d.tip] = d.v; return loadInsights(); }
  if ('reset' in d) { await API.reset(); S.convs = {}; S.convId = null; S.uiDone = {}; await boot(); toast('Demo restarted'); return; }
  if (t.id === 'mic') return toggleMic();
});
document.addEventListener('input', (e) => {
  if (e.target.id === 'msg') { e.target.style.height = 'auto'; e.target.style.height = Math.min(160, e.target.scrollHeight) + 'px'; $('#send').disabled = !e.target.value.trim(); }
});
document.addEventListener('keydown', (e) => {
  if (e.target.id === 'msg' && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e.target.value); }
  if (e.key === 'Escape' && S.panel) closePanel();
});
document.addEventListener('submit', (e) => { if (e.target.id === 'composer') { e.preventDefault(); send($('#msg').value); } });

// ------------------------------------------------------------------ boot
window.AimoApp = { S, get API() { return API; }, esc, ic, ICONS, render, renderView, openPanel, closePanel, toast, store, KITCHENS,
  boardItems, applyConv, refresh, openOrder, itemsHtml, applyTheme };

async function boot() {
  applyTheme();
  S.buyerId = store.get('buyer', 'BUY-POHJOLA');
  if (!KITCHENS[S.buyerId]) S.buyerId = 'BUY-POHJOLA';
  let live = false;
  if (location.protocol.startsWith('http')) {
    try { const r = await fetch('/v1/playbook', { cache: 'no-store' }); live = r.ok && (r.headers.get('content-type') || '').includes('json'); } catch (e) { live = false; }
  }
  if (!live && Replay.available()) {
    API = Replay; S.mode = 'replay'; S.buyerId = 'BUY-POHJOLA';
    const cid = await Replay.seed();
    applyConv(await Replay.chatGet(cid));
  } else {
    API = Live; S.mode = 'live';
    const ch = await API.chats(S.buyerId);
    const last = store.get('conv', null);
    const pick = ch.chats.find((c) => c.id === last) || ch.chats[ch.chats.length - 1];
    if (pick) applyConv(await API.chatGet(pick.id));
  }
  await refresh();
}
boot();
})();
