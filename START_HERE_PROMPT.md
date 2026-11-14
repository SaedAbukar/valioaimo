# Prompt for the coding session (paste this as the first message)

You are continuing the **Aimo Agent Gateway** project for the Valio Aimo
challenge at Junction 2026. A previous session built a plan, a data model
and a v1 MVP. Your job is **v2: a chef-friendly, chat-first app on top of a
gateway that enforces a repeatable agent playbook.**

## 0. Before anything else

1. Read `HANDOFF.md` in the repo root completely. It lists every file, link
   and decision. If the repo is not here, ask me for `aimo-agent-gateway.zip`
   and `aimo-data-model.zip`, or the GitHub repo name.
2. Read `docs/CHALLENGE_BRIEF.md` (the official challenge brief, organiser insights,
   scenarios and judging criteria — the source of truth for what must be solved) and
   `docs/PLAN.md` (the full plan exported from the Claude Docs plan; HANDOFF.md §4
   overrides it for v2). Both are in this folder on the Mac: ~/Code/valioaimo/docs/.
   If they are not committed yet, `git add docs/CHALLENGE_BRIEF.md docs/PLAN.md`,
   commit and push them.
   Then read `PROGRESS.md`, `docs/ARCHITECTURE.md`, `docs/data-model/DATA_MODEL.md`
   and `gateway/rules.yaml`.
3. I will give you the Valio Aimo mock API endpoint. Put it in `.env` as
   `AIMO_BASE_URL`, with `AIMO_API_KEY` (I'll paste it). Never commit either.
   Map the real endpoints in `gateway/adapter.py` and write what you find to
   `docs/MOCK_API_NOTES.md` (fields, units, stock and lead-time behaviour).
   Until then, use `gateway/data/*.json`.
4. Create a task list and keep `PROGRESS.md` updated after every milestone.

## 1. Who it is for

Chefs and kitchen staff, not IT people. v1 was too technical and showed too
much data. v2 must feel calm, obvious and simple yet beautiful. Plain kitchen
language. A user should never feel incompetent.

## 2. Priority 1: the agent workflow (the "rails")

The gateway publishes a **versioned playbook** that every agent follows, and
enforces it with a state machine. This is the most important part: repeatable,
followable by any agent, and easy to refine.

Implement:

- **The playbook file.** `gateway/playbook/order_playbook.v1.yaml` holds the
  steps 0–8 from HANDOFF §4.3: Receive → Understand → **Recall first** →
  **Discover only for gaps** → Plan → Check → Present → Act → Follow up and
  learn. For each step: the tools it unlocks, the required output as a JSON
  Schema, guards and exit conditions.
- **Recall order.** Favourites and pinned products → past successful similar
  orders (outcome labels `perfect_order`, `right_sized`, `good_substitute`) →
  learned quantities per guest → standing orders → leftovers. Each matched
  line records its source and a confidence of high, medium or low.
- **Discover rules.** Only for gaps. Reason about the need, map it to a product
  group, search the API, get signed offers.
- **Check is run by the gateway, not decided by the agent.** It covers the
  trust checks and the spending, allergen and delivery rules, reusing
  `gateway/trust.py`, `gateway/policy.py` and `gateway/rules.yaml`.
- **State machine endpoints.** `GET /v1/playbook`, plus a session endpoint
  where each step's tool returns `next_allowed_tools`. Out-of-order calls get
  `409 step_not_allowed`. Expose the same tools over MCP.
- **Logging.** Every step goes to `audit_event` with the playbook version, so
  runs can be replayed.
- **Golden scenarios.** Put the six scenarios from HANDOFF §4.3 in
  `tests/playbook/`, as replayable tests. They must pass before you touch the UI.
- **Docs.** `docs/PLAYBOOK.md` explains each step in plain words, with a
  changelog. A playbook change must keep the golden scenarios green.

Use the data model in `docs/data-model/schema.sql` for names and storage.
Keep it 3NF; add tables only with a clear consumer.

## 3. Priority 2: the chat-first UI (flow and design over technology)

Don't over-engineer the front end. A single-page app reusing
`ui/src/engine.js` is fine. Spend the time on flow and look.

- **First screen is a normal AI chat**, like Claude, ChatGPT or Gemini: a
  message box with a mic button and a thread.
- **The assistant answers only in cards**, never in paragraphs. Card types and
  wording rules are in HANDOFF §4.2: what I understood, one question, from your
  favourites, shopping basket, product choice, needs your OK, can't do this,
  delivery, how did it go, tip.
  - one idea per card
  - one main action
  - no more than 3 options and 3 numbers
  - a "Why?" link for any detail
- **Layout is a mix of Claude and Jira.** Chat in the centre with past chats
  in a left sidebar. Orders work as tickets on a simple board: Planning →
  Waiting for OK → Ordered → Delivered → Done. Opening a card or order slides
  in a right-hand detail panel.
- **Desktop and mobile.**
  - Desktop: sidebar, chat, detail panel.
  - Mobile: full-screen chat, a bottom bar (Chat, Orders, Insights, More),
    the board as a list grouped by status, and details in bottom sheets.
- **The other pages follow the same simplicity.**
  - Orders: the board.
  - Insights: three or four plain statements with one chart, written like
    "You threw away less this month", with tips as cards.
  - Settings: favourites, spending limits, allergens, people who approve.
- **Design.** Minimal Material 3, using only turquoise blue (primary), white
  (surface) and sky blue (secondary), in light and dark. Large readable type,
  generous white space, friendly icons. No gradients, glows, emoji or jargon:
  never say mandate, policy, rule id, GTIN, score or tier.
- **Wiring.** Each chat turn runs the playbook through the gateway, and each
  step's output becomes a card, so the chat is the playbook made visible.
- **Demo.** Opens on a chat already showing the gala example: "Gala dinner for
  180 on Saturday…" → What I understood → From your favourites → Basket →
  Ordered.

## 4. Definition of done

- Golden playbook scenarios and the existing tests pass (`pytest`).
- `make run` serves the gateway and the UI. Each of the six scenarios can be
  run from the chat and looks right on 390 px mobile and 1280 px desktop, in
  light and dark. Save screenshots to `docs/screenshots/v2/`.
- `docs/PLAYBOOK.md`, `docs/UX.md` (rewritten for chat and cards),
  `docs/ARCHITECTURE.md` and `README.md` are updated.
- A self-contained demo build at `ui/dist/index.html`, published as a Claude
  artifact if that tool is available.
- `PROGRESS.md` is up to date, with remaining gaps listed.

Work autonomously. Record decisions in `docs/ASSUMPTIONS.md` instead of
asking, except for the API endpoint and key, which I'll provide.

## Appendix — challenge checklist (audit the MVP against the brief)

The judged product is the AGENT-FACING GATEWAY and its rules; the chef chat app
is one example buyer-side agent using it (the brief says it is "not about
replacing the webshop with a chatbot"). Make each item TRUE, proven by a test or
demo step, and record it in `docs/CHALLENGE_CHECKLIST.md` (PASS/FAIL, where, how
to demo):

1. Structured lookup: product, price and availability as JSON via OpenAPI
   (`/openapi.json`) and MCP tools, through `gateway/adapter.py` and the real mock API.
2. Inquiry -> commitment at fixed prices: signed, time-limited offer -> order must
   cite the offer id; expired or changed price = re-quote; no negotiation.
3. Permissions and human approval: published rules (spend, substitutions outside
   preferences, late delivery, allergens); the gateway decides, not the LLM; approval
   reaches a named human and is recorded.
4. End to end: "I need 1,000 litres of lactose-free milk by Monday..." runs
   request -> lookup -> order OR approval against the mock backend, from a script or
   agent calling only the gateway, in under a minute.
5. No exposure: agents never reach backend systems directly; document what is exposed.
6. Open standards listed with reasons in `docs/STANDARDS.md` (OpenAPI 3.1, MCP,
   /.well-known discovery, JWS-signed offers and confirmations, signed mandate).
7. Trust both ways: agent bound to a customer account + signed authority; offers
   verifiable by the agent.
8. The playbook (Understand -> Recall -> Discover -> Plan -> Check -> Present -> Act
   -> Learn) is served by the gateway and enforced.
9–11 (optional): delivery reliability + sustainability labels; substitutions and
   partial availability with reasons; human-readable log for buyer and Valio Aimo.

Demo order: start with an external agent hitting the gateway, show approval, then
show the chef app as one client.

