# UX — chat first, answers as cards (v2)

**Who it is for:** chefs and kitchen staff, not IT people. They are busy, often on a
phone, sometimes with wet hands. The app must feel calm and obvious, and nobody
should ever feel they lack the know-how to use it.

v1 showed too much: rule ids, scores, tiers, offer details. v2 hides all of that
behind one "Why?" link and talks like a colleague.

## The first screen is a chat

A normal AI chat, as in Claude, ChatGPT or Gemini: a message box, a mic button and
a thread. The demo opens on a chat that already shows the gala example:
"Gala dinner for 180 on Saturday…" → What I understood → From your favourites →
Basket → Ordered.

**The assistant answers only in cards, never in paragraphs.** Each chat turn runs
the gateway playbook (`POST /v1/chat`) and each step's output becomes a card, so the
chat is the playbook made visible.

## Card types

| Card | When | Content | Main action |
|---|---|---|---|
| What I understood | After every request | Event, date, guests, dishes, diets as chips; guesses dashed | Looks right · Change |
| One question | A critical fact is missing (never more than one) | Short question + up to 3 tap answers | Tap an answer |
| From your favourites | Recall found a match | "Same as your Spring gala 2026. It went well." | Use this |
| Shopping basket | Plan is ready | Total, per guest, deliveries (max 3 numbers) | Order · See items |
| Product choice | A real choice (no memory for this need) | Up to 3 products: name, price per kg/L, one-line why, tag (Best match, Cheaper option, Faster delivery) | Pick one |
| Needs your OK | Over a limit or a change | What and why in one sentence | OK · Not now |
| Can't do this | Blocked (e.g. allergen) | What and why, safe choice as a chip | Use alternative |
| Delivery | After ordering | Day, time of day, total | Track |
| How did it go? | After the event | Per product: Used it all / Some left / Ran out | Save |
| Tip | From history | "Your last 3 galas had whipping cream left over. Order 20% less?" | Apply · Ignore |

### Wording rules (enforced by the gateway's card lint)

- One idea per card, one main action, at most 3 options and 3 numbers.
- Never shown: mandate, policy, rule id, GTIN, JWS, score, tier, need group, unit codes like KI or ST.
- Said instead: spending limit, your rules, product, price per kg / L, best match, cheaper option, faster delivery.
- Every technical detail sits behind **Why?**, written in the same plain words.
- Dates as kitchens write them: "Sat 21.11.". Money without cents above €100.

Cards from earlier turns keep their content but lose one-time buttons (you can't
order twice from an old basket); "See items" and "Track" stay.

## Layout: Claude + Jira

**Desktop (≥ 860 px):** left sidebar (New chat, Chat, Orders, Insights, Settings,
recent chats, who you are), chat in the centre (max 760 px), and a right panel that
slides in for "See items", an order ticket, or details.

**Phone:** full-screen chat; bottom bar with Chat, Orders, Insights, More; the
board becomes a list grouped by status; details open as a bottom sheet.

### Orders board

Planning → Waiting for OK → Ordered → Delivered → Done. A ticket shows the event
or order, one subtitle line, a status pill and the total. Opening it shows a 5-step
progress bar, deliveries and items grouped by day with a plain why per line and
where it came from (Favourite, Worked last time, New). For the demo the panel also
lets you act as the approver ("OK, order it") and mark an order delivered.

### Insights

Three or four plain statements ("You threw away less this month."), one chart
(food left over, share of food ordered, 8 weeks) and tips as cards.

### Settings (More on phones)

Kitchen (switch between the demo kitchens), favourites, spending limits, never
order (allergens), people who OK orders, appearance (system / light / dark), and
"How it works": the nine playbook steps in plain words.

## Visual design

Minimal Material 3. Three colours: turquoise (primary), white (surface) and sky blue
(secondary), each tuned for light and dark. Muted amber and red appear only on
"Needs your OK" and "Can't do this". Figtree, 17 px base, 19 px card sentences,
26 px numbers. Generous spacing, 20 px card corners, simple line icons.
No gradients, glows, emoji or jargon.

## States

- **Working:** a single line under the thread walks through the steps ("Reading
  your request", "Checking your favourites", "Building the basket", "Checking your rules").
- **Errors:** a short toast that says what went wrong; the chat stays as it was.
- **Offline / artifact:** the same page plays recorded gateway runs and offers the
  examples as tap answers if you type something it has no recording for.
- **Voice:** Web Speech API in Chrome and Edge (fi-FI if the text looks Finnish,
  else en-GB). Where the microphone is blocked, a toast says to type instead.

## Accessibility

Visible focus rings, keyboard send (Enter) and Escape to close panels, focus returns
to the opener, buttons ≥ 44 px, `aria-pressed` on the usage choices, `role="status"`
for progress and toasts, reduced motion respected, contrast checked in both themes.

Screenshots: [`docs/screenshots/v2/`](screenshots/v2) — every scenario at 390 px and 1280 px, light and dark.

---

## v3 (14 Nov 2026): Orders like Jira, Insights like Wrapped, Kitchens like a CRM

**Orders.** Switch between **Board** (five columns) and **List** (rows), remembered per
device. Every order has a key (`POH-901`) and an event colour label; regular deliveries
get a grey "Regular" label. Search, kitchen filter, group by event or kitchen (swimlanes
on the board, sections in the list), quick filters (Needs OK, Due this week, Events only)
and an event legend you can click to filter. The Done column and the list include a year
of past orders (833 for Pohjola), sortable and paged 50 at a time. Opening a live order
shows its activity timeline ("Request understood → Checked favourites and past orders →
Basket planned → Checked: fits your rules → Ordered from Valio Aimo"); opening a past one
shows every product, whether it was just right or left over, and whether it came on time.

**Insights › Your year.** A story of nine full-colour cards: the year in numbers, your
number-one product, your kitchen personality ("The Cream Team"), your busiest month, your
biggest night, how much less you threw away, your carbon footprint in car trips, on-time
deliveries, and a send-off into Explore. Tap the arrows, use ← → keys, or swipe. Pick one
kitchen or the whole group.

**Insights › Explore.** Ask in words, filter by kitchen, period, category and event type,
or tap a starter question. The answer is one chart, a plain caption and three facts, with
a Chart / Table switch and "How I made this" showing each tool step.

**Kitchens** (was Settings). Organisation header with credit in use and the people who OK
orders, then one card per kitchen with spend in the last 30 days, food left over, on-time
rate and a 12-month sparkline. A kitchen opens a panel with Overview, People, Deliveries
and Rules. Favourites, rules, appearance and "How it works" follow.

**Look.** Material 3 tonal surfaces and state layers (every button and card tints on hover
and press), bigger story type, and a categorical palette checked with the colour validator
(turquoise first). Yellow and magenta sit below 3:1 on white, so every chart has tooltips,
a legend and a table view.
