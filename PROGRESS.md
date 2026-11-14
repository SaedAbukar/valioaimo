# Progress — Aimo Agent Gateway

## v5 — hardening, seller agent, analytics, operations view (14 Nov 2026)
Plan: docs/superpowers/plans/2026-11-14-v5-gateway-hardening-seller-ops.md (Tasks 1–21). Rulings: docs/ASSUMPTIONS.md (v5).
- Hardening (1–6): stock re-checked and reserved at order time (409 `stock_changed`); `Idempotency-Key`; a JSON Schema per tool (playbooks 1.1.0, typed MCP tools, 422 `bad_input` with an example); session events + long-poll; SQLite persistence with stable keys; rate limits (429 + `Retry-After`).
- Audit findings (14–21): one gateway for REST and MCP (Streamable HTTP `/mcp`, stdio proxy); chef-app routes and chat approvals need credentials, demo tokens only in demo mode; ticking clock, kill switch on every call; per-session lock, atomic steps; resilient adapter (retry, breaker, deadline, worker threads); rejected calls audited, JSON logs with `traceparent`, ops metrics; input validated everywhere, bounded long-poll, eviction, incremental audit verify; `authz.py`, `Backend` protocol, approvals module, MCP `isError`.
- Seller agent (12): `gateway/seller.py`, signed `suggestion+jwt`, ≤ 3 per buyer, mandate-safe, accepted only through `plan_basket` → `check_basket`; REST, MCP, A2A skill, event; `agent_demo.py --suggestions`.
- Bench (7): `scripts/agent_bench.py`, `make bench` → docs/BENCH.md. Live against the mock API: 100 % completion, every invariant holds, determinism 100 %. Found and fixed two oversell bugs (weekly restock, re-registered live stock).
- Analytics (8–10): insight rails authenticated; datasets `agent_activity` and `demand`; `forecast`, `anomaly`, `explain_change`; forecast drawn dashed with a band, a running month as a hollow dot.
- Operations view (11): `/v1/ops/metrics`, `/demand`, `/lost-sales` (k ≥ 3), ops MCP mode, Kitchens › Valio Aimo view; demo seed with four kitchens.
- Tests: 279 passed + 1 opt-in live test (passed). Live: `make agent` (both flows on live prices), `--suggestions`, `make bench` all pass.
- Not built: chef-app "From Valio Aimo" suggestion card; LLM bench rows (no Anthropic key on this machine).
- Published: artifact https://claude.ai/artifact/WemSdQFg5vy35Ki2YkeAbi version 4 (`1794666826-c172`), built from `ui/dist/artifact.html` (recorded demo; the operations view needs the live gateway).
- Screenshots: `docs/screenshots/v2` regenerated, plus `v5-forecast-*` and `v5-valio-aimo-view-*` (390/1280, light/dark).

## v4 — challenge audit (14 Nov 2026)
- Audited against docs/CHALLENGE_BRIEF.md and the planning-session checklist → **docs/CHALLENGE_CHECKLIST.md** (core 1–4, underlying 5–8, optional 9–11 all PASS; scenarios: 3 PASS, 2 PARTIAL, proactive seller agent not built).
- New: OpenAPI 3.1 (`/openapi.json`), `/.well-known/ucp`, signed `/.well-known/agent-card.json`, structured lookup (`/v1/products/search`, `/price-availability`) through the mock API, bearer credentials bound to one buyer (`gateway/auth.py`), approver inbox + human-only approvals, orders that must cite offer ids, no-negotiation guard, signed order confirmations, `/v1/mandate`, `/v1/offers/{id}[/verify]`, `/v1/orders/{id}`, plain session log, ops kill switch, pack labels in lookup, live pricing for recalled favourites.
- MCP: 40 tools, identity from `AIMO_AGENT_TOKEN`, no approve tool.
- `scripts/agent_demo.py` (stdlib-only external agent): brief request → AUTO order in < 1 s on the live mock API; 3,000 L → needs OK → Laura approves → order.
- Tests: 135 passed + 1 opt-in live test (passed). Docs: README (gateway first + 3-minute demo), API, STANDARDS, EXPOSURE, ASSUMPTIONS.
- Git: pushed to github.com/SaedAbukar/valioaimo (organiser dataset index excluded).

### Remaining gaps
- Proactive Valio Aimo seller agent (example scenario) not built.
- "Suggest recipes around a seasonal ingredient" and a "tomorrow" last-minute golden scenario not built.
- Chef-app endpoints run without sign-in in the demo (documented in docs/EXPOSURE.md).
- Claude Haiku analyst path not exercised live (no Anthropic key on this machine).

## Earlier

## Published
- Artifact: https://claude.ai/artifact/4PYHao2tm2PPmvCVTekwTp — slug `1b710f3e-6284-4874-8781-8bbf027c6d73`, version `1794608519-366b` (MVP v1).
  Republish: `python3 ui/build.py` then publish_files with slug + base_version (latest version above).

## Done
- Python reference core (gateway/): catalog (97 products, GTIN-14), need resolution, preferences, planner, policy (rules.yaml R0–R14, V1–V3), trust (VC 2.0 + JWS ES256 offers, 6 checks), audit hash chain, signals, thin server `python -m gateway`. Tests: `pytest -q tests` → 27 passed.
- Client-side engine (ui/src/engine.js, flows.js) mirroring the core + seeded 12-week history (3 buyers), Event Autopilot, approvals, outcome store, recommendations, waste/usage, ops, outcome labels, metric definitions, day context.
- UI (ui/src/app.js, app2.js, styles.css, index.html) — 10 screens + guided demo (13 steps) + data model view; build `python3 ui/build.py` → ui/dist/index.html. Inline SVG icons (react-icons md paths, offline).
- Data model v1.1 copied to docs/data-model/.
- Screenshots: docs/screenshots (10 screens × 390/1280 × light/dark + 5 interaction shots).

- Docs written (README, ARCHITECTURE, UX, PROBLEM_SOLUTION, EVENT_AUTOPILOT, DATA_MODEL, API, STANDARDS, ROADMAP, ASSUMPTIONS); Mermaid validated with mmdc.
- Zip: /home/claude/aimo-agent-gateway.zip

## Next
- Done. Optional polish only.

## Decisions
- Demo clock anchored Fri 13 Nov 2026 09:00 EET for repeatable scenes.
- Event budget (hotel) €3,300 per event / €26 per guest so 180 guests → auto-order (NOTIFY) and 200 → one approval.
- Backend kept as thin reference skeleton per priority change; MVP page is the deliverable.

## DESIGN DIRECTION — user feedback 2026-11-14 00:40 (TOP PRIORITY for next refinement run)
The UI/UX is too bloated, too "AI-looking" and messy. Next run must:
- Clean and simplify as much as possible: minimal design following Material 3 (fewer screens/elements, one primary action per screen, generous whitespace, no decorative gradients/glows/emoji/badges overload, short copy, progressive disclosure for detail).
- Palette: three main colours only — turquoise blue (primary), white (surface), sky blue (secondary/container). Same three-colour identity in dark mode (dark surface tuned to the same hues; turquoise and sky blue adapted for contrast). Semantic status colours only where strictly needed (block/approve), muted.
- Keep all requirements reachable, but behind cleaner navigation (consider: Autopilot, Orders, Insights, Settings + "How it works").

## Redesign run (2026-11-14 03:55 →)
- v1 UI backed up to /home/claude/scratch/v1ui (not in repo).
- Plan: new ui.js + styles.css; IA = Autopilot · Orders · Insights · Settings; one input handles events and plain orders; detail in bottom sheets.
- 05:22 published redesign v2 → version `1794626575-65a7` (base for next publish).
  Decisions: tokens in styles.css (turquoise #087a85 / white / sky #dcf0fa + #87ceeb; dark #0e1a1d surface, #6fd3dc primary); single font Figtree;
  one input handles events AND plain orders (units L/kg → agent order; else event brief); detail moved into bottom sheets;
  approvals live at top of Orders; catalog explorer removed (offers open from product rows); guided overlay replaced by Settings › Demo scenarios;
  planner: relaxed (other-variant) products never outrank strict ones (bug fix, also in planner.py); hotel monthly budget €45,000 so R3 doesn't swamp demo.
  Old UI kept in /home/claude/scratch/v1ui (app.js/app2.js removed from build).
- 05:44 published polish 1 → version `1794627866-cca2`.
- 06:47 published polish 2 → version `1794631623-5e82` (metrics list, reconcile layout, org-scoped result card, snackbar cleared by sheets).
- 06:52 published polish 3–5 → latest version `1794631926-c9a6`: sentence-case chips, Esc closes menus, quieter usage report (labels only where waste/shortage), textarea aria-label, boot error state.
- Docs: UX.md rewritten for v2 (tokens, IA, components, states, a11y); README/PROBLEM_SOLUTION locations updated; 65 new screenshots in docs/screenshots (11 screens + 6 sheets × 390/1280 × light/dark).
- Next (if more time): optional desktop two-pane Autopilot; focus return after closing sheets.
- 06:54 published polish 6 → version `1794632039-db5c`: Autopilot two panes ≥1100px (summary | detail list), focus returns after sheets close, sentence-case rule rows; screenshots regenerated.
- 06:55 published polish 7 → version `1794632084-103a`: mobile architecture lanes wrap, data-model entity scrolls into view.
- 06:56 published polish 8 → latest version `1794632184-da18`.
- 07:03 focused pass published → version `1794632620-560a`:
  1. Insights chart: y-axis labels (0/50/100%), x labels end at "This week" (to 13 Nov); KPI tiles say "4-week avg" (waste "Last 12 weeks") so they don't contradict the weekly end value.
  2. Orders badge uses primary turquoise, not red.
  3. Focus trap in sheets (Tab/Shift+Tab cycle, Esc closes, focus returns to opener).
  4. Finnish parser: "lauantaina 21.11.", "ensi perjantaina", "huomenna", hengelle/henkilölle/vieraalle, vegaani(a), gluteeniton/-tonta, laktoositon/-tonta, keliaakikko, pähkinä-/kala-allergia(kko); brief gets lang 'fi' and the card shows "la 21.11. · 120 hengelle · noutopöytä", menu shows the Finnish dish word. Tests: tests/js/parser.test.js (6 cases, EN+FI) run via pytest (tests/test_js_parser.py) → 28 passed.
  5. Phone Autopilot: after planning the input collapses to a one-line field (tap to edit); card numbers + status/order/primary action above the fold at 390×844.
  6. Bug: event card lost its order/usage rows after reconciliation; now shows "Done · usage recorded". 13 scenarios re-run OK; 65 screenshots regenerated.

---------------------------------------------------------------------------
# v2 — chat-first app on playbook rails (session 2, 14 Nov 2026)

Repo now lives in `~/Code/valioaimo` (extracted from `aimo-agent-gateway_1.zip`). Python env: `.venv` (starlette, uvicorn, pydantic, PyJWT, cryptography, PyYAML, jsonschema, mcp 2.x, pytest).

## Milestones
- [x] Real Valio Aimo data: `scripts/build_aimo_index.py` -> `gateway/data/aimo_products.json` (17,546 products, allergens, diet claims, CO2e, delivery reliability, substitutions). Raw files in `data_raw/` (git-ignored).
- [x] Mock API adapter: `AimoApiClient` (POST /api/price, /api/availability, X-API-Key, batches ≤1000, 5-min cache, fixture fallback). `.env` has `AIMO_BASE_URL`; Key received 14 Nov 09:55 and set in `.env`; live API verified (see below).
- [x] Playbook `gateway/playbook/order_playbook.v1.yaml` + state machine `engine.py` (409 step_not_allowed, JSON Schema outputs, audit per call with version and ms).
- [x] Steps: understand.py (EN/FI parser), recall.py (5 sources in order), discover.py (curated + real products bridge), menu.py (event -> ingredients), tools.py (all tools), cards.py (cards + plain-language lint), agent.py (built-in chef assistant, board), insights.py.
- [x] REST (`gateway/__main__.py`) and MCP (`gateway/mcp_server.py`, 21 tools) over the same engine.
- [x] Golden scenarios `tests/playbook/golden.yaml` (6) + rail tests -> `pytest` 46 passed.
- [x] Chat-first UI: ui/src/{index.html,styles.css,app.js} -> ui/dist/index.html (served) + ui/dist/artifact.html; live mode via /v1/chat, offline mode plays recorded gateway runs (ui/src/replays.json). v1 UI moved to ui/legacy-v1/.
- [x] Checked in the built-in browser (1280 light/dark, 390 dark): guest change -> needs OK -> board -> approve -> delivered -> How did it go -> tip on next gala.
- [x] 60 screenshots: docs/screenshots/v2 (scripts/screenshots.py, Playwright; all six scenarios run from the chat at 390/1280 × light/dark).
- [x] Published v2 artifact: https://claude.ai/artifact/WemSdQFg5vy35Ki2YkeAbi (file ui/dist/artifact.html; republish the same path to update).
- [x] Docs: PLAYBOOK.md, UX.md (rewritten), ARCHITECTURE.md §9, MOCK_API_NOTES.md, README.md, ASSUMPTIONS.md (v2).

## Remaining gaps
- LLM parsing step behind parse_request (schema is ready) is not built; parsing is pattern-based EN/FI.
- State is in memory (audit chain in SQLite :memory:); schema.sql tables are the target, no Postgres wiring.
- Curated assortment allergens/stock are synthetic; only the new-kitchen path uses real products.
- Tips on the Insights page are not wired back to the next plan (the chat Tip card is).
- Order cut-off time (closingTime) and delivery tracking are not shown yet.

## Live mock API (14 Nov 2026, 09:55)
- Key in `.env`; `/api/ping` 200; `/health` liveApi.reachable true.
- Found: Cloudflare blocks Python's default User-Agent (403) -> client sends `aimo-agent-gateway/0.2`.
- Adapter now batches price + availability per gap, takes unit/pack content from comparisonPrice, drops undeliverable products, handles 999999 / 9999999999 / 0-without-date.
- New-kitchen flow verified in the app on live prices (2 API calls). Tests: 56 passed (new tests/playbook/test_live_bridge.py, no network).
- Observations written to docs/MOCK_API_NOTES.md. Replays re-recorded with live prices; artifact republished.

## v3 — Jira orders, Wrapped + Explore insights, CRM kitchens (14 Nov 2026)
Design: docs/superpowers/specs/2026-11-14-v3-orders-insights-kitchens-design.md · Plan: docs/superpowers/plans/2026-11-14-v3-orders-insights-kitchens.md
- [x] A year of history (Dec 2025 – Nov 2026): 1,280 orders, 21,235 lines, 86 events, 6 sites; generated in 0.1 s, seeded (gateway/analytics/store.py).
- [x] Insight playbook + engine (409/422 with fix hints, audit), query compiler, 17 chart types (Vega-Lite), explainer.
- [x] Analyst: Claude Haiku 5.5 tool loop when ANTHROPIC_API_KEY is set, rule engine otherwise (no key on this machine: Claude path not run live).
- [x] REST: /v1/tools, /v1/insights/*, /v1/orders/history(/id), /v1/orders/{id}/activity, /v1/kitchens. MCP: 31 tools.
- [x] UI: ui/src/orders.js, insights.js, kitchens.js; M3 tokens + state layers; validated chart palette.
- [x] Tests: 118 passed. Checked in the browser at 1280 (light, dark) and 390; offline build checked on a static server.
