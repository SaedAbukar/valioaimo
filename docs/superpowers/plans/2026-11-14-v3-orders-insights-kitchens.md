# v3 Orders, Insights and Kitchens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jira-style orders, Wrapped + Explore insights driven by a broad analytics toolkit any model can call, and a CRM-style kitchens area with a refreshed Material 3 look.

**Architecture:** A year of synthetic history is generated deterministically and loaded into SQLite. A second playbook (`insight_playbook.v1.yaml`) with its own state machine exposes analytics tools over REST and MCP; queries compile from a validated spec to SQL, charts are Vega-Lite specs built by the gateway. The single-page app gains Orders (board/list), Insights (Your year / Explore) and Kitchens views.

**Tech Stack:** Python 3.13, starlette, sqlite3, jsonschema, PyYAML, mcp 2.x, anthropic SDK (optional), vanilla JS, Vega 5 / Vega-Lite 5 / vega-embed 6 from jsDelivr.

**Spec:** `docs/superpowers/specs/2026-11-14-v3-orders-insights-kitchens-design.md`

## Global Constraints

- Golden ordering scenarios (`tests/playbook/golden.yaml`) stay green; card lint rules unchanged.
- No raw SQL from callers: only the query spec, compiled with bound parameters and whitelisted fields.
- Analytics tools return `409 step_not_allowed` + `next_allowed_tools` out of order, `422` with a `fix` hint on bad input.
- Charts: gateway builds Vega-Lite v5 specs; page loads `vega@5.30.0`, `vega-lite@5.21.0`, `vega-embed@6.26.0` from cdn.jsdelivr.net.
- Typed questions: Claude Haiku (`claude-haiku-5-5`) when `ANTHROPIC_API_KEY` is set, rule-based interpreter otherwise; both via the same tools.
- Plain kitchen language in the UI; no jargon (mandate, policy, SQL, spec).
- Light + dark; works at 390 px and 1280 px; no git commits (user: "not yet").

## Review Focus

- Explore filter combination that matches no rows → an empty-state card, not a broken chart (test in Task 3).
- Prompt the rule interpreter cannot read → it still answers with a sensible default chart and says what it assumed (Task 4).
- Unknown field / bad aggregation from a model → 422 with the list of valid names (Task 3).
- Orders list with ~1,500 history rows → paginated, sorted, search stays responsive (Task 5).
- Switching kitchen/site → board, insights and kitchens all follow the selected org/site (Task 7 check).

---

### Task 1: Organisations, sites and a year of history

**Files:**
- Create: `scripts/gen_history.py`, `gateway/data/history_year.json`, `gateway/analytics/__init__.py`, `gateway/analytics/store.py`
- Modify: `gateway/data/buyers.json` (Pohjola gets `sites`: Helsinki, Tampere, Turku; Kaarela 2 schools; others 1)
- Test: `tests/analytics/test_store.py`

**Interfaces:**
- Produces: `store.load(gw) -> sqlite3.Connection` (tables `site`, `event`, `orders`, `order_line`), `store.SCHEMA: dict[str, dict]` describing every queryable field (label, type, unit).
- Line fields: `order_id, site_id, buyer_id, date, month, week, weekday, event_id, event_type, product, category, kind, supplier, qty, unit, unit_price, value_eur, kg, co2e_kg, on_time (0/1), used_pct, waste_eur, label`.

- [ ] Test: `test_history_is_deterministic_and_rich` — two loads give identical row counts; ≥ 1,200 orders, ≥ 15,000 lines, 12 months, every Pohjola site present, events of ≥ 5 types.
- [ ] Implement generator (seeded `random.Random(2026)`): weekly replenishment per site from buyer history + events from recipes; prices ±seasonal; waste lower in recent months; write JSON.
- [ ] Run `pytest tests/analytics -q` → PASS.

### Task 2: Analytics playbook and state machine

**Files:**
- Create: `gateway/analytics/insight_playbook.v1.yaml`, `gateway/analytics/engine.py`
- Test: `tests/analytics/test_rails.py`

**Interfaces:**
- Produces: `InsightEngine(gw).call(sid|None, tool, args) -> {tool, step, output, next_allowed_tools}`; tools `start_analysis, describe_data, get_values, run_query, suggest_chart, build_chart, explain_result`; reuses `PlaybookError` classes from `gateway/playbook/engine.py`.

- [ ] Test: out-of-order `build_chart` before `run_query` → `StepNotAllowed`; every call audited with `insightPlaybookVersion`.
- [ ] Implement YAML (steps, tool input JSON Schemas, fix hints) + engine.
- [ ] Run tests → PASS.

### Task 3: Query compiler, chart builder, explainer

**Files:**
- Create: `gateway/analytics/query.py`, `gateway/analytics/charts.py`, `gateway/analytics/explain.py`
- Test: `tests/analytics/test_query.py`, `tests/analytics/test_charts.py`

**Interfaces:**
- `query.run(conn, spec) -> {columns, rows, shape, sql_preview}`; spec keys: `measures[{field,agg,as}]`, `dimensions[{field,grain}]`, `filters[{field,op,value}]`, `compare:"previous_period"|"previous_year"|None`, `calc[{type:share|running_total|rank|change_pct|moving_avg, of, window}]`, `sort[{by,dir}]`, `limit`, `other:bool`, `period{from,to}`.
- `charts.suggest(result) -> [{type, why}]`; `charts.build(result, intent) -> vega_lite_spec`; types: line, area, bar, column, stacked, grouped, percent, scatter, bubble, heatmap, donut, waterfall, histogram, boxplot, kpi, sparkline, table.
- `explain.run(result, spec) -> {caption, facts[3]}`.

- [ ] Tests: spend by month for Helsinki returns 12 rows; top-5 products + other sums to total; share sums to 100; `change_pct` vs previous period; unknown field → `GuardFailed` whose `fix` lists valid fields; empty filter result → `rows == []` and `explain` caption "No orders match these filters."; heatmap spec has `rect` mark and two encodings; every chart type builds a spec with `$schema` v5.
- [ ] Implement; run tests → PASS.

### Task 4: Analyst agent (Haiku or rules) and REST/MCP

**Files:**
- Create: `gateway/analytics/analyst.py`
- Modify: `gateway/__main__.py` (`/v1/insights/*` routes), `gateway/mcp_server.py` (register analytics tools), `requirements.txt` (anthropic)
- Test: `tests/analytics/test_analyst.py`

**Interfaces:**
- `Analyst(gw).ask(prompt:str, filters:dict, buyer_id:str) -> {chart, rows, caption, facts, steps[], engine:"claude"|"rules", assumed[]}`.
- Routes: `GET /v1/insights/playbook`, `POST /v1/insights/sessions`, `POST /v1/insights/sessions/{id}/tools/{tool}`, `POST /v1/insights/ask`, `GET /v1/insights/wrapped?buyerId=&siteId=`, `GET /v1/orders?…` (history list).

- [ ] Tests (rules engine): "waste by month" → line chart over 12 months; "top 5 products by spend in Tampere" → bar with 5 + filter site; "kulutus kategorioittain" (FI) → category breakdown; gibberish → default spend-by-month with `assumed` non-empty.
- [ ] Implement Claude path with tool use (read claude-api skill first), falling back to rules on any error.
- [ ] Run tests → PASS.

### Task 5: Jira-style Orders view

**Files:** Modify `ui/src/app.js`, `ui/src/styles.css`; Modify `gateway/playbook/agent.py` (board items get `key`, `eventColor`, `site`, `due`, `activity[]`) .
- [ ] Board/List toggle (remembered), group by status/event/site, quick filters (search, event chips, site, status, due soon, history), sort, keys like `POH-42`, event colour stripe + label, activity timeline in the panel, history paginated 50/page.
- [ ] Check in the browser at 1280 and 390, light and dark.

### Task 6: Insights — Your year + Explore

**Files:** Modify `ui/src/app.js`, `ui/src/styles.css`, `ui/src/index.html` (vega scripts).
- [ ] Your year: 8 swipeable story cards from `/v1/insights/wrapped`.
- [ ] Explore: filters + prompt + starter chips; renders chart via vega-embed with theme tokens; shows caption, 3 facts, "How I made this" steps; table toggle.
- [ ] Offline replay: record wrapped + starter-chip answers into replays.json.

### Task 7: Kitchens (CRM) and colour refresh

**Files:** Modify `ui/src/app.js`, `ui/src/styles.css`, `gateway/playbook/insights.py` (`kitchens()` data).
- [ ] Org header, site cards with KPIs + sparkline, site detail tabs (Overview, People, Favourites, Rules, Deliveries), appearance at the end.
- [ ] New M3 token set with state layers and event palette; check contrast both themes.

### Task 8: Verify, simplify, publish

- [ ] `make test` all green; screenshots regenerated; `/simplify` pass over the diff; docs (README, UX, PLAYBOOK §insights, PROGRESS); rebuild + republish artifact.
