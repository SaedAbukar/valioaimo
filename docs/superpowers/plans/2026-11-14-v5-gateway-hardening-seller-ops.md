# v5 Gateway hardening, richer analytics, wholesaler features: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Load superpowers:test-driven-development before Task 1. Use the `dataviz` skill before touching any chart (Tasks 9–11), `claude-api` before any Claude call (Task 7), `simplify` and superpowers:requesting-code-review at the end (Task 13).

**Goal:** Make the agent gateway production-grade for many agents at once, using these levers:
- no overselling, no double orders
- typed tools that a small model can call without guessing
- push updates instead of polling
- state that survives a restart
- rate limits
- a multi-agent benchmark

Then use the gateway's data to give Valio Aimo something it cannot get from a webshop:
- agent-channel metrics
- forward demand and lost-sales signals
- a proactive seller agent

**Architecture:** Every change goes through the existing seams:
- `gateway/playbook/engine.py` (rails)
- `gateway/playbook/tools.py` (order tools)
- `gateway/analytics/*` (insight rails)
- `gateway/auth.py` (who is calling)
- `gateway/adapter.py` (the only module that talks to Valio Aimo)
- `gateway/__main__.py` (REST) and `gateway/mcp_server.py` (MCP)

REST and MCP share the same handlers, so every feature lands in both.

**Tech stack:** Python 3.13, Starlette, SQLite (stdlib), PyJWT/cryptography (ES256), `mcp` 2.x (`MCPServer`), Vega-Lite 5 specs, pytest. Optional `anthropic` SDK for LLM agents in the benchmark.

**Spec:** this plan's *Context* section (the gap assessment of 14 Nov 2026) plus the **Appendix**, the proactive-seller brief, which is binding for Task 12. Background: docs/CHALLENGE_BRIEF.md and docs/CHALLENGE_CHECKLIST.md.

## Context: what the assessment found (14 Nov 2026)

Measured on 20 runs one after another and 40 at once, offline:

| What | Result |
|---|---|
| Time per tool call | about 2 ms |
| Full agent run | 16 ms median, 35 ms at most |
| Errors with 40 agents at once | none |
| Calls out of order | always refused with 409 and `next_allowed_tools` |

Gaps, ordered by what they would cost a real buyer or Valio Aimo:

1. **Overselling.** `_lock_prices` calls `verify_offer(..., qty=None)`, so stock is not re-checked when the order is placed. Two agents can both order the last 640 L.
2. **Double orders.** A retried `place_order` (after a timeout) creates a second order; there is no idempotency key.
3. **Untyped order tools.** The order playbook has output schemas but **no input schemas**. MCP order and insight tools take a raw `args_json` string, and some errors lack a `fix` hint. A small model has to guess the fields.
4. **No push.** After `request_approval` the agent must poll; there are no events, long-poll or webhooks.
5. **Memory only.** Sessions, orders, the inbox and the signing keys are lost on restart.
6. **No rate limits.**
7. **No multi-agent harness.** Tests run one agent at a time. Nothing scores N agents, or different models, on invariants and behaviour.
8. **Insight endpoints are not authenticated.** `/v1/insights/*` takes `buyerId` from the body, so anyone can read any buyer's analytics. This was found while writing the plan.
9. **Analytics has one dataset.** It covers past order lines only: no agent activity, no forward demand, no forecasting, and no "what drove this change".

## Global Constraints

- The mock API key and URL live only in `.env` (git-ignored). Never print, echo or commit them; scan staged files for the key before each push.
- `gateway/data/aimo_products.json` and `/data/` stay out of git.
- Only `gateway/adapter.py` talks to the mock API. Nothing else imports `urllib`, `http.client` or `requests`; `test_5_agents_never_reach_backend_or_secrets` enforces this.
- The gateway decides; no LLM decides an outcome. LLMs may only call tools.
- Every new endpoint ships in REST, MCP **and** `/openapi.json` (`test_6_openapi_31_and_every_documented_path_is_served` must stay green) **and** `GET /v1/tools`.
- Every new error has the shape `{error, message, guard?, fix?, next_allowed_tools?}`, and every 4xx a caller can correct has a `fix`.
- Credentials as in `gateway/auth.py`:
  - agent: bound to one buyer
  - human: approves only
  - ops: Valio Aimo operations

  Cross-buyer data goes to `ops` only, and is aggregated with **k ≥ 3 buyers** per group.
- The chef app is one client. Keep the existing UI direction; don't redesign. Card wording follows `gateway/playbook/cards.py` lint and `docs/UX.md`.
- Commits: stage files by name (the hook blocks bulk staging and `.env`). End messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push to `origin main` when the suite is green.
- The suite stays green after every task: `make test` (135 passed + 1 opt-in live test at plan time).

## Review Focus

These five failure modes are the most likely to bite and are not covered by any test today; each one gets a test in the task named.

1. Two agents race for the last stock: exactly one order succeeds, the other gets 409 `stock_changed` and re-quotes (Task 1, `test_concurrent_orders_never_oversell`).
2. A retried order with the same idempotency key returns the same order; the same key with a different body gets 422 (Task 2).
3. The gateway restarts while an approval is pending: after restart the human approves, the agent orders, and the old confirmation still verifies (Task 5).
4. A buyer credential reads another buyer's insights or demand: 403. Ops aggregates with fewer than 3 buyers in a group are suppressed (Tasks 8 and 11).
5. A seller suggestion conflicts with the mandate (an allergen, or a category outside it): it is never shown, and accepting one still goes through `check_basket` (Task 12).

---

## File structure

| File | Responsibility |
|---|---|
| `gateway/playbook/order_playbook.v1.yaml` → **v1.1.0** | Adds an `input` JSON Schema per tool; changelog in docs/PLAYBOOK.md |
| `gateway/playbook/engine.py` | Validates input, idempotency cache, emits events, persists sessions |
| `gateway/playbook/tools.py` | Stock re-check and reservation in `_lock_prices` / `place_order` |
| `gateway/adapter.py` | `FixtureBackend.reserve()`, atomic under a lock |
| `gateway/events.py` (new) | Per-session event log, long-poll wait |
| `gateway/persist.py` (new) | SQLite snapshot and restore of sessions, orders, inbox, approvals; key files |
| `gateway/ratelimit.py` (new) | Token bucket per credential |
| `gateway/mcp_tools.py` (new) | Typed MCP wrappers generated from the playbook input schemas |
| `scripts/agent_bench.py` (new) | Multi-agent harness: scripted and optional LLM agents, invariants, report |
| `gateway/analytics/datasets.py` (new) | `agent_activity` and `demand` datasets |
| `gateway/analytics/query.py`, `charts.py`, `explain.py` | Dataset parameter, `forecast` / `anomaly` calcs, `explain_change` |
| `gateway/ops.py` (new) | Ops metrics, forward demand, lost sales (k-anonymity) |
| `gateway/seller.py` (new) | Proactive seller agent (Appendix) |
| `tests/gateway/test_hardening.py`, `test_analytics_v2.py`, `test_ops.py`, `test_seller.py`, `test_bench.py` (new) | Proof per task |

---

### Task 1: Re-check and reserve stock when the order is placed (no overselling)

**Files:**
- Modify: `gateway/playbook/tools.py` (`_lock_prices`, `place_order`)
- Modify: `gateway/trust.py` (`verify_offer` reverify detail)
- Modify: `gateway/adapter.py` (`FixtureBackend.reserve`)
- Modify: `gateway/core.py` (`self.lock = threading.RLock()`)
- Test: `tests/gateway/test_hardening.py`

**Interfaces:**
- Produces:
  - `FixtureBackend.reserve(lines: list[dict], by: dict[str, date]) -> tuple[bool, list[str]]`: atomic; all or nothing; returns the shortfall messages.
  - `place_order` raises `StepNotAllowed(guard="stock_changed", next_allowed_tools=["plan_basket"], shortfall=[...])`.

- [ ] **Step 1: Write the failing tests.**
  - `test_place_order_rechecks_stock`: plan 1,000 L, then `gw.backend.set_stock(fav_gtin, 100)` and clear its inbound. `place_order` then raises with `guard == "stock_changed"`.
  - `test_concurrent_orders_never_oversell`: 8 threads each run the full milk flow through `TestClient`, each to `place_order`. Assert that the sum of ordered quantity per gtin is at most its starting availability by need-by, and that every loser got a 409 `stock_changed`.
- [ ] **Step 2:** Run `pytest tests/gateway/test_hardening.py -k stock -v`. Expected: FAIL; no guard exists, and the race test oversells.
- [ ] **Step 3: Implement.**
  - `_lock_prices` passes `qty=line qty` to `verify_offer`.
  - `place_order` holds `gw.lock` around verify, then `reserve`, then `backend.place_order`.
  - `reserve` checks `available_by` per line inside the lock.
- [ ] **Step 4:** Run `pytest tests -q`. Expected: all green.
- [ ] **Step 5:** Commit: `fix: re-check and reserve stock at order time`.

### Task 2: Idempotency keys for state-changing calls

**Files:**
- Modify: `engine.py` (`call(..., idempotency_key: str | None = None)`)
- Modify: `__main__.py` (read the `Idempotency-Key` header)
- Modify: `mcp_server.py` (`idempotencyKey` parameter)
- Modify: `discovery.py` (header documented on `/v1/sessions/{id}/tools/{tool}` and `/v1/approvals/{id}`)
- Test: `test_hardening.py`

**Interfaces:**
- Produces: the engine caches `(sessionId, tool, key) -> (args_hash, response)` for 24 h. The same key with the same args returns the cached response, with the header `Idempotent-Replay: true`. The same key with different args gets 422 `guard="idempotency_conflict"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_retried_place_order_returns_same_order`: two calls with the same key produce the same `orderId`, and `len(gw.backend.orders) == 1`.
  - `test_same_key_different_body_is_422`.
  - `test_approval_decision_is_idempotent`.
- [ ] **Step 2:** Run them. Expected: FAIL (two orders).
- [ ] **Step 3: Implement.** Apply the cache only to `place_order`, `request_approval`, `record_usage`, approvals and suggestion feedback. Read-only tools ignore the key.
- [ ] **Step 4:** Run the suite: green.
- [ ] **Step 5:** Commit: `feat: idempotency keys`.

### Task 3: Precise input schemas and typed tools (REST and MCP)

**Files:**
- Modify: `order_playbook.v1.yaml` → version `1.1.0`, `input:` JSON Schema per tool
- Modify: `engine.py` (`validate_input(tool, args)`)
- Modify: `manifest.py` (adds `inputSchema`)
- Modify: `discovery.py` (`/v1/sessions/{id}/tools/{tool}` body uses `oneOf` per tool, or a discriminator by path enum)
- Create: `gateway/mcp_tools.py`
- Modify: `mcp_server.py`
- Modify: docs/PLAYBOOK.md changelog
- Test: `test_hardening.py`, `tests/gateway/test_mcp_parity.py`

**Interfaces:**
- Produces:
  - `playbook()["inputs"][tool]`: a JSON Schema with `additionalProperties: false`, `description` per field and an `examples` entry. Examples:
    - `parse_request {text}` or `{answer: {field, value}}`
    - `plan_basket {choices?, useAlternative?, acceptTip?, ignoreTip?, acceptSuggestion?}`
    - `place_order {offerIds, idempotencyKey?}`
    - `record_usage {entries}`
  - A 422 `guard="bad_input"` carries `fix: {"expected": <schema summary>, "example": {...}}`.
  - `mcp_tools.register(mcp, run)`: builds typed Python functions (real parameters and docstrings from the schema) for each order **and** insight tool. `call_tool(args_json)` stays as a generic fallback.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_tool_has_an_input_schema` (order and insight)
  - `test_bad_input_has_a_fix_with_an_example`: `place_order {"offerId": "x"}` returns 422 and `fix.example.offerIds`.
  - `test_mcp_order_tools_are_typed`: `list_tools()`; `place_order.inputSchema.properties` has `offerIds` and no `args_json`.
  - `test_every_4xx_in_rails_has_fix_or_next_allowed_tools`: a parametrized sweep over known error paths.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** Validate with `jsonschema.Draft202012Validator` before the handler. Turn validation errors into one plain `message` plus `fix`. Keep the old `args_json` MCP tools working through `call_tool` only.
- [ ] **Step 4:** Run the suite, including golden: green. Expected: `public_playbook()["version"] == "1.1.0"`. Update the rail test that asserts `1.0.0`, and record the change as a Ruling.
- [ ] **Step 5:** Commit: `feat: typed tool inputs (playbook 1.1.0)`.

### Task 4: Push updates: session events, long-poll, MCP wait

**Files:**
- Create: `gateway/events.py`
- Modify: `engine.py`, `tools.py` (`decide_approval` emits), `__main__.py`, `mcp_server.py`, `discovery.py`
- Test: `test_hardening.py`

**Interfaces:**
- Produces:
  - `Events.emit(session_id, type, data)`
  - `Events.wait(session_id, after: int, timeout: float) -> list[dict]`, using a `threading.Condition`.
  - Event types: `step.completed`, `decision.made`, `approval.requested`, `approval.decided`, `order.placed`, `offer.expiring` (2 min before `validUntil`, emitted lazily on read), `suggestion.created`.
  - REST: `GET /v1/sessions/{id}/events?after=N&wait=0..25` (agent credential; returns `{events, next}`).
  - MCP: `wait_for_update(sessionId, after=0, timeoutSeconds=20)`.
  - Optional `callbackUrl` on `POST /v1/sessions`: documented as a production path only, not implemented. **Ruling:** outbound calls from the gateway to agents are out of scope for the prototype; long-poll covers the need without opening the network.

- [ ] **Step 1: Write the failing test.** `test_agent_is_woken_by_approval`: a thread long-polls with `wait=5` after `request_approval`; the main thread approves as Laura; the waiter returns in under 1 s with `approval.decided`, and `next_allowed_tools` contains `place_order`.
- [ ] **Step 2:** Run it: FAIL. **Step 3:** Implement. **Step 4:** Suite green. **Step 5:** Commit: `feat: session events and long-poll`.

### Task 5: State that survives a restart

**Files:**
- Create: `gateway/persist.py`
- Modify: `core.py` (`Gateway(db=..., keys_dir=...)`), `crypto.load_or_create` usage, `__main__.py` (`AIMO_DB`, default `data/gateway.db` for `make run`; `:memory:` in tests), `.gitignore` (`/data/` already)
- Test: `test_hardening.py`

**Interfaces:**
- Produces:
  - `persist.save(gw)` is called after every state-changing engine call (inside the lock).
  - `persist.load(gw)` runs at boot.
  - Keys are PEM files in `data/keys/` (`gw-*.pem`, `buyer-*.pem`), so the JWKS is stable across restarts.

- [ ] **Step 1: Write the failing test.** `test_restart_keeps_pending_approval_and_keys`, run against a temporary db:
  1. Run to `request_approval`.
  2. Create a new `Gateway` on the same db and keys directory.
  3. Approve, then `place_order`.
  4. The first gateway's JWKS still verifies the new confirmation, and the session log is continuous.
- [ ] **Steps 2–5:** FAIL, implement, green, commit: `feat: persist sessions and keys`.

### Task 6: Rate limits per credential

**Files:**
- Create: `gateway/ratelimit.py`
- Modify: `__main__.py` (in the `guarded` wrapper), `mcp_server.py`, `discovery.py` (429 response)
- Test: `test_hardening.py`

**Interfaces:**
- Produces: `RateLimiter(rate_per_min=120, burst=30).check(token) -> float | None`, which returns the retry-after seconds. A 429 carries `{error: "rate_limited", retryAfter}` and the `Retry-After` header. Ops is exempt. `AIMO_RATE_PER_MIN` overrides the rate (tests set it high, except the rate test).

- [ ] Write `test_burst_over_limit_is_429_with_retry_after`. Run it (FAIL), implement, run the suite (green), commit: `feat: per-agent rate limits`.

### Task 7: Multi-agent benchmark (scripted and LLM agents)

**Files:**
- Create: `scripts/agent_bench.py`
- Create: `tests/gateway/test_bench.py`
- Create: `docs/BENCH.md` (generated report)
- Modify: `Makefile` (`make bench`)

**Interfaces:**
- Consumes: the REST API only, through `scripts/agent_demo.Gateway`.
- Produces: `bench(base, agents=N, scenarios=[...], model=None) -> dict`, plus a markdown report.
  - **Scenarios:**
    - `milk` (the brief's sentence)
    - `over_limit` (3,000 L)
    - `allergen` (Kaarela oat drink)
    - `stale_offer` (advance the demo clock past 15 min, then expect a re-quote)
    - `retry` (`place_order` twice with the same key)
    - `race` (N agents, last stock)
    - `out_of_order` (an agent deliberately skips steps)
  - **Invariants, checked from the gateway's own records and audit:**
    - no oversell
    - no duplicate order per idempotency key
    - every order cites offers that verify
    - no order without AUTO/NOTIFY or a human approval
    - every approval was made by a named approver
    - the audit chain verifies
  - **Scores:**
    - completion rate
    - 409 and 422 counts per run (fewer means better guidance)
    - latency p50 and p95
    - determinism: after `/v1/demo/reset`, the same scenario gives the same outcome and total
  - **LLM agents (optional):** when `ANTHROPIC_API_KEY` is set, `--model claude-haiku-5-5|claude-sonnet-5-5` drives the same tools through a manual tool-use loop. Load the `claude-api` skill first and use the typed input schemas from Task 3 as tool definitions. These scores show whether a small model can follow the rails unaided. With no key, the LLM rows are skipped, and the report says so.

- [ ] **Step 1: Write the failing tests.**
  - `test_bench_scripted_20_agents_hold_every_invariant`: in-process `TestClient`, 20 agents, all scenarios. Every invariant holds, and the determinism score is 1.0.
  - `test_bench_report_lists_scores`.
- [ ] **Steps 2–5:** FAIL, implement, green, then run `make bench` and commit the report: `feat: multi-agent benchmark`.

### Task 8: Insight rails are authenticated, and typed over MCP

**Files:**
- Modify: `__main__.py` (insight routes use `caller(req, "agent", "human", "ops")` with `same_buyer`; `/v1/insights/ask`, `/wrapped`, `/v1/orders/history`, `/v1/kitchens` accept a credential and fall back to the chef app's buyer only when called without one, as documented in EXPOSURE)
- Modify: `analytics/engine.py` (`start_analysis` takes the buyer from the caller)
- Modify: `mcp_server.py` (via `mcp_tools`)
- Modify: `ui/src/app.js` (sends the buyer-app context unchanged)
- Test: `test_analytics_v2.py`

- [ ] **Step 1: Write the failing test.** `test_insight_session_for_other_buyer_is_403`: the Pohjola agent calls `start_analysis {buyerId: BUY-KOULU}` and gets 403. Also `test_insight_mcp_tools_are_typed`.
- [ ] **Steps 2–5:** FAIL, implement, green, commit.
- [ ] **Ruling to record:** the chef-app endpoints stay usable without a token in the demo, as documented in EXPOSURE. Agent-facing insight sessions require a token.

### Task 9: New datasets: agent activity and demand

**Files:**
- Create: `gateway/analytics/datasets.py`
- Modify: `analytics/store.py` (`SCHEMAS` per dataset)
- Modify: `analytics/query.py` (`spec.dataset`, default `"orders"`)
- Modify: `analytics/engine.py` (`describe_data {dataset?}` lists datasets)
- Modify: `insight_playbook.v1.yaml` → `1.1.0` with a recipe per dataset
- Test: `test_analytics_v2.py`

**Interfaces:**
- Produces:
  - **`agent_activity`**: one row per playbook session, built from the audit and the engine. Columns: buyer, site, agent, channel (api/mcp/chat), date, decision, top rule, rule ids, re-quotes, 409 count, 422 count, `time_to_order_s`, `approval_wait_s`, approver, approved, order total, live price share. Measures: `sessions`, `autonomous_rate`, `approval_rate`, `blocked_rate`, `requote_rate`, `p50_time_to_order`, `p90_approval_wait`, `guidance_errors`.
  - **`demand`**: one row per planned or open line plus one row per unmet need. Columns: need-by date, category, product, qty, source (planned/ordered/unmet), unmet reason (`not_deliverable`, `not_by_date`, `partial`, `blocked_allergen`, `over_limit_rejected`), buyer, site. Measures: `planned_qty`, `unmet_qty`, `fill_rate`, `lost_value_eur`.
  - Buyers see only their own rows; `ops` sees all, with k-anonymity enforced in `query.run` when `dimensions` include `buyer`-identifying fields.

- [ ] **Step 1: Write the failing tests.**
  - `test_agent_activity_counts_requotes_and_approval_wait`: run the over-limit flow plus one stale offer; `requote_rate > 0` and `p90_approval_wait` is not null.
  - `test_demand_records_unmet_with_reason`: the Kaarela allergen case gives `unmet_reason == "blocked_allergen"`.
  - `test_ops_k_anonymity_suppresses_small_groups`.
- [ ] **Steps 2–5:** FAIL, implement, green, commit.

### Task 10: Smarter analysis: forecast, anomaly, explain_change

Load the `dataviz` skill first: the forecast must be visually distinct, and anomalies need markers and labels.

**Files:**
- Modify: `analytics/query.py` (`CALCS += ["forecast", "anomaly"]`, with `horizon` 1–6 periods)
- Modify: `analytics/charts.py` (forecast segment dashed with a band; anomaly points with a ring and tooltip)
- Modify: `analytics/explain.py` (facts mention forecast and anomalies)
- Modify: `analytics/engine.py` + playbook (new tool `explain_change {measure, period_a, period_b, by}` in the explain step)
- Test: `test_analytics_v2.py`

**Interfaces:**
- Produces:
  - `forecast`: a seasonal-naive forecast (same period last year) blended with a linear trend over the last 6 periods. Rows are marked `is_forecast: true`, with `lo`/`hi` bounds of ±1.28·σ of the residuals. **Ruling:** no ML dependency; deterministic and explainable.
  - `anomaly`: a robust z-score against a moving median (window 6); `|z| > 3` gives `is_anomaly`.
  - `explain_change`: the contribution of each value of `by` to the difference between periods, top 5 plus Other, as one plain sentence each ("Turku drove +€4.1k of the +€6.0k rise in cream spend").

- [ ] **Step 1: Write the failing tests.**
  - `test_forecast_marks_future_rows_and_bounds`
  - `test_anomaly_flags_a_spike` (inject a spike into a copy of the db)
  - `test_explain_change_contributions_sum_to_total` (tolerance 0.05)
  - `test_forecast_chart_is_dashed_and_has_band`
- [ ] **Steps 2–5:** FAIL, implement, green, commit. Render the result in the app (Explore) and look at it at 390 and 1280 px, light and dark.

### Task 11: Valio Aimo operations view: channel metrics, forward demand, lost sales

**Files:**
- Create: `gateway/ops.py`
- Modify: `__main__.py` (`GET /v1/ops/metrics`, `GET /v1/ops/demand?from&to&by=category|product|day`, `GET /v1/ops/lost-sales`; ops credential only)
- Modify: `mcp_server.py` (an ops MCP server mode when `AIMO_AGENT_TOKEN=demo-ops`: `ops_metrics`, `ops_demand`, `ops_lost_sales`)
- Modify: `discovery.py`
- Modify: UI: a small "Valio Aimo view" section reached from Kitchens › How it works (a demo switch), reusing the Explore chart component
- Test: `tests/gateway/test_ops.py`

**Why it matters to a wholesaler:** agents state their need before they order, with a date, quantity, diet and event. That is a demand signal no webshop has.

| View | What it gives Valio Aimo |
|---|---|
| Forward demand | Next week's planned need per category and day across customers, for stock and transport planning |
| Lost sales | What agents asked for that Valio Aimo could not supply, and why; feeds assortment and supplier decisions |
| Channel metrics | The pilot metrics already listed in docs/STANDARDS.md: autonomous rate, approval wait, re-quote rate, blocked rate, fill rate, time to order |

All three are queries over the Task 9 datasets, with k ≥ 3 aggregation.

- [ ] **Step 1: Write the failing tests.**
  - `test_ops_metrics_match_bench_runs`: after a bench run, `autonomous_rate` equals the fraction of AUTO/NOTIFY sessions.
  - `test_ops_endpoints_forbid_agents_and_humans`
  - `test_forward_demand_aggregates_across_buyers_with_k_anonymity`
  - `test_lost_sales_lists_reasons`
- [ ] **Steps 2–5:** FAIL, implement, green, check the UI in the browser at both widths and both themes, commit.

### Task 12: Proactive seller agent

Build exactly what the **Appendix** specifies. Use these from earlier tasks:
- Task 3: typed inputs for `get_suggestions`, `suggestion_feedback` and `plan_basket {acceptSuggestion}`
- Task 4: a `suggestion.created` event, so buyer agents are woken, not polled
- Task 2: feedback is idempotent
- Task 9: accept and dismiss land in `agent_activity`, so ops sees the suggestion acceptance rate

Tests: the list in the Appendix, in `tests/gateway/test_seller.py`.

### Task 13: Simplify, document, review, ship

- [ ] Run the `simplify` skill over the diff since the v4 commit (`542ec05`). Apply the fixes, and keep the suite green.
- [ ] Update the docs:
  - docs/CHALLENGE_CHECKLIST.md: new rows under "Robustness", namely no oversell, idempotency, restart, rate limit, concurrency and the bench. The proactive-seller scenario moves to PASS, and the scenario summary row changes.
  - docs/STANDARDS.md: Idempotency-Key (IETF draft), `Retry-After` (RFC 9110), long-poll events, A2A skill.
  - docs/EXPOSURE.md: ops data, k-anonymity, seller-agent limits.
  - docs/API.md, docs/PLAYBOOK.md (1.1.0 changelog for both playbooks), docs/ARCHITECTURE.md §11, docs/ASSUMPTIONS.md (v5 rulings), PROGRESS.md.
  - README: add `make bench`. Keep the 3-minute demo; add a suggestion step only if it fits.
- [ ] Regenerate the screenshots (`python scripts/screenshots.py` with `make run` up). Rebuild and republish the artifact (https://claude.ai/artifact/WemSdQFg5vy35Ki2YkeAbi) with the same file path.
- [ ] Final whole-branch review: superpowers:requesting-code-review with a fresh reviewer on the most capable model. Give it the diff since `542ec05`, this plan and the Review Focus list. Then do one fix pass, RED → GREEN per finding.
- [ ] Run the live checks: `AIMO_LIVE_TESTS=1 pytest tests/gateway/test_live_e2e.py`, `make agent`, then `make bench` against `make run`.
- [ ] Scan staged files for the API key, commit by name, push to `origin main`.

---

## Appendix: proactive selling agent brief (binding for Task 12)

```text
You are continuing the Aimo Agent Gateway (Valio Aimo challenge, Junction 2026) in ~/Code/valioaimo
(git repo, remote github.com/SaedAbukar/valioaimo, branch main; you may commit and push freely,
staging files by name, never .env).

Read first: README.md, docs/CHALLENGE_BRIEF.md, docs/CHALLENGE_CHECKLIST.md, docs/EXPOSURE.md,
docs/STANDARDS.md, docs/ASSUMPTIONS.md (v4 section), PROGRESS.md, then gateway/__main__.py,
gateway/auth.py, gateway/lookup.py, gateway/discovery.py, gateway/mcp_server.py,
gateway/playbook/tools.py and tests/gateway/test_challenge.py.

GOAL
Build the brief's example scenario "Proactive selling agent: Valio Aimo's own agent spots a new or
seasonal product and proactively suggests it to the buyer's agent". It is the only scenario marked
"Not built" in docs/CHALLENGE_CHECKLIST.md. The gateway is the judged product; keep the
gateway-first framing.

WHAT TO BUILD (keep it small and consistent with what exists)
1. A seller-side suggestion engine (e.g. gateway/seller.py) that picks at most 3 suggestions per buyer
   from the real assortment (gateway/aimo_products.py) and the buyer's own history/favourites
   (gateway/playbook/recall.py, gateway/data/history.json):
   - seasonal (e.g. Christmas or game season relative to the gateway clock),
   - new to this buyer but similar to something they buy often,
   - a better option on the buyer's own criteria (lower CO2, a label like Hyvää Suomesta,
     higher delivery reliability), priced from the mock API through the adapter.
   Each suggestion has a plain reason, a trade-off, the source data and an expiry.
   Hard rules: never suggest anything that breaks the buyer's signed mandate (allergen
   exclusions, categories) or its preferences; never add to a basket; no price negotiation.
2. A signed suggestion: a JWS from the gateway key, typ "suggestion+jwt", with
   "issuer: Valio Aimo seller agent" clearly marked as promotional, so the buyer's agent can tell
   a seller suggestion from its own recall.
3. Delivery to the buyer's agent (pull plus push-style):
   - REST: GET /v1/suggestions (agent credential, own buyer only),
     POST /v1/suggestions/{id}/feedback {accepted|dismissed, reason}.
   - MCP: get_suggestions and suggestion_feedback.
   - A2A: add a "proactive-offers" skill to /.well-known/agent-card.json; add a
     com.valioaimo.suggestions capability to /.well-known/ucp.
   - Document it in /openapi.json (the existing OpenAPI test checks every documented path is served).
4. Using a suggestion goes through the normal playbook only. A suggestion may appear as a Tip in
   recall or plan for the chef app; accepting it re-plans and still passes check_basket, signed offers
   and approval rules (first-time product → R8 notify). Every suggestion shown, accepted or dismissed
   is audited (actor "agent:valio-aimo-seller").
5. Rate limit: at most 3 open suggestions per buyer; a dismissed product is not suggested again for 30 days.
   Buyers can opt out (a mandate or profile flag), and the opt-out is respected.
6. Chef app (optional, small): one "From Valio Aimo" tip card in chat, clearly labelled as a suggestion
   from the seller. Follow the existing card wording rules (gateway/playbook/cards.py lint) and
   docs/UX.md. Do not redesign anything.

PROOF (TDD, write the failing test first)
Add tests in tests/gateway/test_seller.py:
- suggestions respect allergen exclusions and opt-out;
- signature verifies with the JWKS;
- another buyer's credential gets 403;
- feedback is audited;
- dismissed products are not suggested again;
- accepting one leads to a re-plan that still goes through check_basket (not a direct order);
- MCP parity.
Keep the whole suite green (make test, currently 135 passed + 1 opt-in live test:
AIMO_LIVE_TESTS=1 pytest tests/gateway/test_live_e2e.py). Extend scripts/agent_demo.py with
--suggestions to show the buyer's agent pulling and verifying a suggestion.

DOCS
- docs/CHALLENGE_CHECKLIST.md: move the scenario to PASS with where, test and demo.
- docs/EXPOSURE.md: what the seller agent may use (only the buyer's own data with Valio Aimo) and
  what it may never do.
- docs/STANDARDS.md (A2A skill), docs/API.md, docs/ASSUMPTIONS.md (decisions), PROGRESS.md,
  and the README demo, as an optional extra step only if it fits in the 3 minutes.

RULES
- The mock API key and URL stay in .env (git-ignored). Never print, echo or commit them.
  gateway/data/aimo_products.json stays out of git.
- Only gateway/adapter.py talks to the mock API.
- The gateway decides; no LLM decides.
- Run the app (make run) and check any UI change in the browser at 390 px and 1280 px,
  light and dark.
- Work autonomously and record decisions in docs/ASSUMPTIONS.md. Commit and push when green.
```

---

## Prompt for the Opus session that executes this plan

```text
Continue the Aimo Agent Gateway in ~/Code/valioaimo (git, origin github.com/SaedAbukar/valioaimo, main;
commit and push freely, stage files by name, never .env).

Read docs/superpowers/plans/2026-11-14-v5-gateway-hardening-seller-ops.md completely and execute it
with superpowers:executing-plans (inline), loading superpowers:test-driven-development first. Use the
dataviz skill for Tasks 9–11 charts, claude-api for Task 7's LLM agents, simplify and
superpowers:requesting-code-review in Task 13. Tasks 1–6 are the hardening and come first; Task 12 is
the proactive seller (its brief is the plan's Appendix and is binding). Work autonomously: record
rulings in the ledger and docs/ASSUMPTIONS.md, keep PROGRESS.md current, keep `make test` green after
every task, and push when green. Finish with the live checks and a summary listing rulings and
deferred minors.
```

---

## Tasks 14–21: architecture audit of 48001b0 (added 14 Nov 2026 at the user's request)

Same TDD process and Global Constraints. Scale to a Junction prototype (SQLite, demo tokens behind a demo mode). Order: after Task 12, before Tasks 7–11; Task 13's final review covers these too. Every scale-down is a Ruling in the ledger.

### Task 14: Share state between MCP and REST (Critical, C1)
MCP over Streamable HTTP at `/mcp` inside the `__main__` app, on the same `Gateway`; identity from the Bearer header. Stdio stays as a thin proxy to `AIMO_GATEWAY_URL` (or in-process for tests).
Tests: an MCP agent calls `request_approval`, Laura approves over REST, `wait_for_update` wakes, `place_order` succeeds; stock is shared between channels.

### Task 15: Close the chat approval bypass and lock down chef-app routes (Critical, C2 and C3)
Chef app gets a buyer-user credential; chat approve/decline need the approver's human credential; `/v1/demo/reset` ops-only or demo mode; `/v1/board`, `/v1/chats*`, `/v1/orders/{sid}/activity`, `/v1/orders/history*`, `/v1/insights*`, `/v1/kitchens`, `/v1/settings` authenticated with buyer from the credential. Credentials from the environment; `demo-*` only when `AIMO_DEMO=1` (default for `make run`). `hmac.compare_digest`.
Tests: each route 401/403 without the right credential; chat approve needs a human credential; UI still works (browser, 390 and 1280 px).

### Task 16: Ticking clock and kill switch on every call (High, H1 and H2)
Default to a ticking clock, frozen only in tests; test offers expire in the server. Check the kill switch in `Engine._call` for every tool and pass `killSwitch` into the policy context (V3). Test a paused agent's `place_order` is blocked mid-session.

### Task 17: Per-session lock and atomic tool steps (High and Medium, H3 and M1)
Per-session lock around `Engine._call`; run tools on a deep copy of session data, commit only after the output schema check; `_place` releases stock if signing/recording fails after `backend.place_order`.
Tests: parallel calls on one session never mix plan/offer versions; a forced schema failure leaves the session unchanged.

### Task 18: Resilient adapter (High, H4)
Engine and lookup calls via `anyio.to_thread`; retry with jitter (2 tries); circuit breaker (open after 3 failures, 30 s cool-down, fallback to demo values with `priceSource` flagged); short deadline per request; `/health` returns the error class only.
Tests with a failing/slow fake client: breaker opens, fallbacks flagged, other requests not blocked.

### Task 19: Audit rejected calls; logging, metrics, tracing (High and Medium, H6 and M7)
Audit every 403/409/422 as `rejected.<tool>` with actor, guard and code. Structured JSON logs with request id, session id and W3C `traceparent` passthrough. `GET /v1/ops/metrics-raw` (ops): call counts, decision mix, 409/422 rates, adapter latency and errors, breaker state; merged with Task 11.
Test: an agent's attempt to approve itself appears in the audit as rejected.

### Task 20: Validate input everywhere, bound resource use (Medium, M2–M4)
Lookup bodies validated with JSON Schemas (422 + fix); MCP `call_tool` malformed `args_json` → structured 422; `ask_insight` filters get a schema. One condition per session in `events.py`; bounded long-poll pool (503 + Retry-After when full). Evict expired idempotency entries, API cache entries and event logs. Incremental `audit.verify()`. Tests.

### Task 21: Structure and MCP polish (Medium and Low, M5, M6, L1–L6)
`gateway/authz.py` used by REST and MCP (fixes `get_order` drift); `Backend` Protocol; inbox and audit filtering out of `__main__.py`; no `gw.insights` side effect in `Analyst.__init__`; split `tools.py` if simple; `discover_gateway` uses the configured base URL; `AuditLedger.tamper()` to test helpers; `start_session` accepts an idempotency key; MCP protocol-level errors (`isError`); optionally narrow the MCP tool list (`list_changed`) or record a Ruling.

Afterwards: docs/EXPOSURE.md, STANDARDS.md (Streamable HTTP MCP, traceparent, circuit breaker), CHALLENGE_CHECKLIST.md (Robustness section), ASSUMPTIONS.md, PROGRESS.md. Report which findings are closed or scaled down, with the proving tests.
