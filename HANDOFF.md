# HANDOFF — Aimo Agent Gateway (Valio Aimo challenge, Junction 2026)

Written 14 Nov 2026, 09:10 Helsinki, at the end of the first (chat) session.
Read this file first. It holds everything the next session needs; nothing
in the old chat is required.

---------------------------------------------------------------------------

## 1. Where everything is

| What | Name | Location |
| --- | --- | --- |
| This repo | `aimo-agent-gateway` | This folder (or `aimo-agent-gateway.zip` the user downloaded) |
| Data model package | `aimo-data-model` | `docs/data-model/` in this repo (also `aimo-data-model.zip`) |
| Plan document | "Valio Aimo Agent Gateway – Junction 2026 Plan & Build Prompt" | Claude Docs artifact: https://claude.ai/artifact/UC1kBreE8Np4zcnDyhkvtB (user's Claude account) |
| Current clickable MVP (v1, will be replaced) | "Aimo Agent Gateway" | Artifact: https://claude.ai/artifact/4PYHao2tm2PPmvCVTekwTp ; source `ui/src/`, built file `ui/dist/index.html` |
| Progress log of the v1 build | `PROGRESS.md` | repo root |
| Challenge brief | "Valio Aimo challenge" text | `docs/CHALLENGE_BRIEF.md` (~/Code/valioaimo/docs on the Mac) — full brief, insights, scenarios, judging; no credentials |
| Plan document (markdown) | same plan as the Claude Docs link | `docs/PLAN.md` (~/Code/valioaimo/docs on the Mac); HANDOFF §4 overrides it for v2 |
| Valio Aimo resource portal | Junction 2026 Valio Aimo portal | https://junction26.valioaimo.fi/ — password is in the challenge brief (ask the user; never commit it) |
| Mock API base URL + key | `AIMO_BASE_URL`, `AIMO_API_KEY` | **User will provide the endpoint.** Key is in the challenge brief. Put both in `.env` (see `.env.example`); never commit |

If a file named here cannot be found, ask the user for it by the name in the
"Name" column.

---------------------------------------------------------------------------

## 2. The challenge in short

Valio Aimo (Finnish foodservice wholesaler, 20,000+ professional kitchens,
25,000 products, 700 suppliers) wants the interface and operating model that
lets an external AI purchasing agent find products, compare offers and order,
with the right human approval, on open standards — without exposing real
systems. Core: product/price/availability lookup; inquiry → order at fixed
prices; permission and human approval. Optional: delivery and sustainability,
substitutions/exceptions, traceability.

Judging: end-to-end demo 30% · matches the buyer's need with least manual
correction 20% · autonomy and controls 20% · robustness to exceptions 15% ·
openness and path to production 15%.

Example request: *"I need 1,000 litres of lactose-free milk by Monday. Find an
option that meets our requirements based on price and availability."*

---------------------------------------------------------------------------

## 3. Decisions already made (keep them)

- **Gateway pattern.** The agent never talks to Valio Aimo systems directly; it
  calls a gateway. The LLM proposes, deterministic rules decide.
- **Open standards.** REST + OpenAPI 3.1 shaped after UCP; MCP tools over the
  same handlers; AP2-style signed mandates; W3C VC 2.0 / JWS (ES256) signed
  offers; GS1 GTIN; EU 14 allergens. Details: `docs/STANDARDS.md`, plan doc.
- **Trust.** Only signed, fresh offers can be ordered; six checks
  (`gateway/trust.py`).
- **Approval rules.** AUTO / NOTIFY / APPROVE / BLOCK, strictest wins
  (`gateway/rules.yaml`, rules R0–R14, V1–V3; `gateway/policy.py`).
- **Event Autopilot.** A chef describes an event (text or voice, EN/FI);
  the system builds, checks and orders the whole basket
  (`docs/EVENT_AUTOPILOT.md`, `gateway/data/recipes.json`).
- **Preferences and favourites** per buyer, site and category
  (`gateway/preferences.py`).
- **History, insights, usage and waste loop** with outcome labels and governed
  metrics.
- **Data model v1.1** — 67 tables (3NF) + 10 views, labelled
  (`docs/data-model/schema.sql`, `DATA_MODEL.md`, ER and class diagrams).
  Principle: capture as much as possible, store only refined, labelled data.
- **Palette.** Turquoise blue (primary), white (surface), sky blue
  (secondary), in light and dark. Minimal Material 3. No gradients, glows or emoji.

---------------------------------------------------------------------------

## 4. NEW DIRECTION from the user (14 Nov, 09:04) — this is the next task

### 4.1 Users and the problem with v1

The users are **chefs and kitchen staff, not IT people.** The v1 MVP is too
technical and shows too much data; it can confuse them and make them feel
incompetent. The new version must feel easy, calm and obvious.

### 4.2 UI/UX: chat first, answers as cards

- **First page = a normal AI chat** (like Claude, ChatGPT, Gemini): a message box,
  a mic button, a conversation thread.
- **The assistant does not answer in text paragraphs. It answers in cards**
  that are very easy to understand, each with one clear action.
- **Layout: a mix of Jira and Claude.**
  - **Claude part:** the conversation is the centre; past conversations in a
    collapsible left sidebar.
  - **Jira part:** orders are tracked like tickets on a simple board
    (columns: Planning → Waiting for OK → Ordered → Delivered → Done), with a
    detail panel that slides in from the right.
- **Desktop and mobile.**
  - **Desktop:** left sidebar (Chat, Orders board, Insights, Settings + recent
    chats), centre chat, right panel for the card or order the user opened.
  - **Mobile:** full-screen chat; bottom bar (Chat, Orders, Insights, More);
    the board becomes a list grouped by status; detail opens as a bottom sheet.
- **Simple yet beautiful.** Same palette (turquoise, white, sky blue), lots of
  white space, large readable type, friendly icons, no jargon.
- **The flow and the design matter most.** Do not spend time on technical UI
  plumbing; a single-page front end with the existing engine is fine.

**Card types** (one idea per card, plain kitchen language, max 3 options):

| Card | When | Content | Action |
| --- | --- | --- | --- |
| What I understood | After every request | Event, date, guests, dishes, diets as editable chips | Looks right / Change |
| One question | A critical fact is missing (max one) | Short question + tap answers | Tap an answer |
| From your favourites | Recall found a match | "Same as your Christmas party in 2025 — it went well", items reused | Use this |
| Shopping basket | Plan ready | Grouped by delivery day, total, cost per guest | Order / See items |
| Product choice | Real choice needed | Up to 3 products: name, price per portion, one-line why | Pick one |
| Needs your OK | Over a limit or a change | What changed and why, in one sentence | OK / Not now |
| Can't do this | Blocked (e.g. allergen) | What and why, safe alternative | Use alternative |
| Delivery | After ordering | Day, time window, what arrives | Track |
| How did it go? | After the event | Per product: used it all / some left / ran out (sliders or 3 buttons) | Save |
| Tip | From history | "Last 3 galas used less cream — order 10% less?" | Apply / Ignore |

**Wording rules.** Never show: mandate, policy, rule id, GTIN, JWS, score,
tier, need group. Use: spending limit, your rules, product, price per portion,
"best match", "cheaper option", "faster delivery". Every technical detail sits
behind a "Why?" link that opens a plain explanation. Never more than 3 numbers
on a card.

### 4.3 Backend: the agent workflow is the product ("rails")

The gateway publishes a **versioned, repeatable playbook** that every agent
must follow. It is the guideline the agent works by, and it can be refined
and upgraded over time. The gateway enforces it: a step's tools unlock only
when the previous step produced its required output.

**The basic flow (from the user):**

1. **Understand.** Break the request down and extract the facts that matter.
2. **Recall first.** Look in the buyer's own data — favourites, pinned
   products, and similar past orders that went well — and build the idea
   from there.
3. **Discover only if needed.** If recall gives nothing usable (or leaves
   gaps), reason about what is needed and get it from the Valio Aimo API.

**Full playbook (implement as `gateway/playbook/order_playbook.v1.yaml` + a
state machine):**

| # | Step | Agent does | Gateway tools unlocked | Required output (schema) | Exit / guard |
| --- | --- | --- | --- | --- | --- |
| 0 | Receive | Log request, identify buyer, site, agent | `start_session` | `session_id` | Unknown agent or no valid spending limit → stop |
| 1 | Understand | Extract the **Order Brief**: what (items or dishes), how much (qty or guests + diets), when (need-by), where (site), constraints (allergens, diets, budget, brands), context (event, standing, ad hoc) | `parse_request`, `ask_user` | `OrderBrief` with each fact marked found / assumed / missing | Missing date, quantity or site → ask **one** question card; assumptions are shown, not hidden |
| 2 | Recall | Search the buyer's own data in this order: (a) pinned / favourite products for each need, (b) past successful orders of the same kind (labels `perfect_order`, `right_sized`, `good_substitute`), (c) similar events (`sig_per_guest_consumption`), (d) standing orders, (e) leftovers in stock | `get_favourites`, `find_similar_orders`, `get_learned_quantities`, `get_leftovers` | `RecallResult`: matched lines, source of each, confidence high / medium / low, gaps | High-confidence match → draft basket from it and skip to Step 4 for those lines |
| 3 | Discover | For the gaps only: reason about the need, map it to product groups, search the API, get signed offers | `search_products`, `get_product`, `request_offers` | `Candidates` per gap with signed offers | No offer meets hard constraints → alternative or "Can't do this" card |
| 4 | Plan | Build the basket: quantities (guests × learned use + buffer − leftovers), pack sizes with least waste, delivery days by shelf life, up to 3 alternatives only where there is a real choice | `plan_basket` | `BasketPlan` with a plain "why" per line | Every line traces to recall or discovery |
| 5 | Check | Gateway runs trust checks and spending / allergen / delivery rules | `check_basket` (gateway-run, not agent-decided) | `Decision`: auto / tell me / needs OK / blocked + plain reasons | Agent cannot change the decision |
| 6 | Present | Turn the result into cards (§4.2) | `render_cards` | `Card[]` | Plain-language lint: no banned words, at most 3 numbers per card |
| 7 | Act | Place the order, or send the OK request to the right person | `place_order`, `request_approval` | `Order` / `ApprovalRequest` | Only after Step 5; price-locked to the signed offers |
| 8 | Follow up and learn | Delivery updates, "How did it go?" card after the event, labels, tips | `record_usage`, `get_tips` | `ProcessRecord`, `OutcomeLabel[]` | Feeds Step 2 next time |

**Playbook requirements:**

- **Versioned file.** Steps, tools per step, required outputs (JSON Schema),
  guards, banned words and card templates. Served at `GET /v1/playbook`; every
  session records which playbook version it ran under.
- **State machine in the gateway.** Calling a tool out of order returns
  `409 step_not_allowed` with `next_allowed_tools`, so any agent (Claude, GPT,
  Gemini, a script) can follow it.
- **Every step is logged** (`audit_event`) with its inputs, output and timing,
  so runs can be replayed and the playbook improved.
- **Golden scenarios.** Golden scenarios in `tests/playbook/` replay a request
  through all steps and assert the outputs. Changing the playbook must keep
  them green; new lessons become new scenarios.
- **Playbook changelog.** `docs/PLAYBOOK.md` explains every step in plain words
  and keeps a changelog.

**Golden scenarios to start with:**

1. Milk: "1,000 L lactose-free milk by Monday". Recall finds the favourite;
   stock covers 640 L → split with a second brand → "tell me".
2. Gala for 180 (salmon, beef, mousse; 12 vegan, 8 gluten-free, 1 nut
   allergy). Recall finds last gala → quantities from learned use and
   leftovers → order.
3. A new kitchen with no history: no favourites → full discovery → product
   choice card.
4. Allergen conflict: the only substitute contains nuts → "Can't do this" with
   a safe alternative.
5. Guest change: "now 200 guests" → rescale → "needs OK" (over limit).
6. After the event: "How did it go?" → labels → next similar event gets a tip.

---------------------------------------------------------------------------

## 5. What exists and what to reuse

- **Planner and rules:** `gateway/planner.py`, `policy.py`, `trust.py`,
  `preferences.py`, `signals.py`, `audit.py` — reference Python, 28 tests in
  `tests/`. Reuse inside the playbook steps.
- **Synthetic data:** `gateway/data/catalog.json` (products), `recipes.json`
  (dishes → ingredients per portion), `buyers.json` (hotel chain, hospital,
  school with history). Replace or augment with the real mock API data once
  the user gives the endpoint.
- **API adapter stub:** `gateway/adapter.py`. Map the real endpoints here first
  and write notes to `docs/MOCK_API_NOTES.md`.
- **v1 front end:** `ui/src/` (engine.js, flows.js, ui.js, styles.css,
  data.js). `engine.js` holds the client-side logic (parser, planner, policy,
  audit) and can be reused. **Rebuild the UI** around chat + cards + board as
  in §4.2; do not patch the v1 screens.
- **Docs to update:** `docs/UX.md` (rewrite for chat + cards), `docs/ARCHITECTURE.md`
  (add the playbook / state machine), new `docs/PLAYBOOK.md`, `README.md`.
- **Environment notes from session 1:** offline sandbox, no pip or npm installs;
  starlette, pydantic, PyJWT + cryptography, mcp and pytest were available.
  `fastapi` was not. Check your own environment.

---------------------------------------------------------------------------

## 6. Open items

- **Real mock API:** the user will provide the endpoint. Fields, units, stock
  behaviour and lead times are unknown until then.
- **Voice in the browser:** Web Speech API in the local app; the Claude artifact
  page blocks the microphone.
- **Finnish parsing:** pattern-based. Consider an LLM step behind the playbook's
  `parse_request` with a strict JSON schema.
- **Open questions for the mentors:** see "Assumptions" in the plan doc.
