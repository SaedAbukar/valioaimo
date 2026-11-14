# The order playbook

The playbook is the set of rails every purchasing agent follows when it orders
for a kitchen: Claude, GPT, Gemini, a script, or the built-in chef assistant.
It lives in one versioned file, [`gateway/playbook/order_playbook.v1.yaml`](../gateway/playbook/order_playbook.v1.yaml),
and the gateway enforces it with a state machine ([`engine.py`](../gateway/playbook/engine.py)).

- `GET /v1/playbook` returns the whole file: steps, tools per step, output schemas, guards, banned words, card templates.
- `POST /v1/sessions` starts a session; `POST /v1/sessions/{id}/tools/{tool}` runs one tool.
- Every response carries `next_allowed_tools`. A tool called out of order returns
  **`409 step_not_allowed`** with the tools that are allowed now.
- Every output is checked against the step's JSON Schema. A wrong shape is rejected (`422 guard_failed`).
- Every call is written to the hash-chained `audit_event` log with the playbook version, the step, the inputs and the time it took, so any run can be replayed.
- The same tools are available over MCP (`python -m gateway.mcp_server`), through the same state machine.

The idea in one line: **recall the kitchen's own memory first, discover only for gaps, and let the gateway (not the agent) decide.**

## The steps in plain words

| # | Step | What happens | Tools | Output |
|---|------|--------------|-------|--------|
| 0 | Receive | The gateway checks who is asking: a known agent for a known kitchen with a valid, signed spending limit. If not, it stops here. | `start_session` | Session |
| 1 | Understand | The request is turned into an Order Brief: what, how much, when, where, any diets or allergies, and whether it is an event, a standing order or a one-off. Each fact is marked *found*, *assumed* or *missing*. If the date, amount or site is missing, the agent asks **one** question. Guesses are shown to the chef, never hidden. | `parse_request`, `ask_user` | OrderBrief |
| 2 | Recall first | The kitchen's own memory, always in this order: favourites and pinned products, past orders of the same kind that went well (`perfect_order`, `right_sized`, `good_substitute`), how much guests really ate at similar events, standing orders, and leftovers in stock. Each match records where it came from and how sure we are (high, medium, low). What is not covered becomes a gap. | `get_favourites`, `find_similar_orders`, `get_learned_quantities`, `get_standing_orders`, `get_leftovers`, `recall` | RecallResult |
| 3 | Discover only for gaps | Only when recall left gaps. The agent maps each gap to a product group, searches the Valio Aimo assortment and gets signed offers. If nothing meets the hard rules (allergens, diet), it returns a safe alternative or a "Can't do this". This step is **locked** when there are no gaps. | `search_products`, `get_product`, `request_offers` | Candidates |
| 4 | Plan | The basket: guests × learned use + a service buffer − leftovers; whole packs with the least waste; delivery day by shelf life; up to three options only where there is a real choice. Every line says why it is there and where it came from. | `plan_basket` | BasketPlan |
| 5 | Check | Run by the gateway, not the agent: offer signatures and freshness, then spending, allergen, delivery and substitution rules (`gateway/rules.yaml`). The result is one of *auto*, *tell me*, *needs OK* or *blocked*, with plain reasons. The agent cannot change it. | `check_basket` | Decision |
| 6 | Present | The result becomes cards the chef understands. A lint rejects banned words (mandate, policy, rule ids, GTIN, score, tier…), more than 3 numbers or 3 options on a card, or more than one main action. Cards an external agent brings are linted the same way. | `render_cards` | Cards |
| 7 | Act | Place the order, or send one OK request to the right person. Only what Check allowed. Prices are locked to the signed offers: an expired or changed offer stops the order and sends the agent back to Plan. | `place_order`, `request_approval` | Order |
| 8 | Follow up and learn | Delivery updates, the "How did it go?" card after the event, outcome labels per line, and tips. This feeds step 2 next time. | `record_usage`, `get_tips` | ProcessRecord |

Changes the chef makes from the cards rewind the session to the right step:
a new guest count goes back to **Understand**, a product pick, a tip or a safe
alternative goes back to **Plan**. Everything after that step runs again.

### Learning, quietly or with a question

- Quantities are learned **quietly** only from runs that went right (`right_sized`):
  the median of the last three, needing at least two, clamped to 60–115 %.
- When the same item is over-ordered three times in a row, the gateway does
  **not** change it silently. It offers a Tip ("Your last 3 galas had whipping
  cream left over. Order 20% less?") and the chef decides.

## Golden scenarios

The scenarios in [`tests/playbook/golden.yaml`](../tests/playbook/golden.yaml) replay a request through all
steps on a fresh gateway and assert the cards, the decision and the basket.
A playbook change must keep them green (`make test`). A new lesson becomes a new scenario.

| Scenario | What it proves |
|---|---|
| s1 Milk: 1,000 L lactose-free by Monday | Recall finds the favourite; stock covers 640 L; the second brand comes from a past `good_substitute`; Discover is skipped; decision *tell me*. |
| s2 Gala for 180 | Recall finds the last gala; salmon and beef follow learned use; 6 L leftover cream is used first; the nut-allergy guest gets a nut-free dessert; ordered within the event limit. |
| s3 New kitchen | No memory, so full discovery on the **real Valio Aimo product data**; a product choice card with three real products; pick, then order. |
| s4 Allergen conflict | The usual oat drink is too late and the only other one may contain nuts: "Can't do this" with a safe alternative; the order cannot be placed until the chef chooses. |
| s5 Guest change | "now 200 guests" rewinds to Understand, rescales, and lands over the event limit: needs OK, approval, then the order is updated. |
| s6 After the event | "How did it go?" saves labels per product; the next gala gets a tip about cream; applying it orders less. |

Rail tests in [`tests/playbook/test_rails.py`](../tests/playbook/test_rails.py) cover 409s, the one-question rule,
the Discover lock, gateway-run Check, price lock after expiry, lint, and audit.

## Writing your own agent

```bash
curl -s localhost:8000/v1/playbook | jq '.steps[] | {n, id, tools}'
SID=$(curl -s -XPOST localhost:8000/v1/sessions -d '{"buyerId":"BUY-POHJOLA"}' | jq -r .sessionId)
curl -s -XPOST localhost:8000/v1/sessions/$SID/tools/parse_request -d '{"text":"I need 1,000 L lactose-free milk by Monday"}' | jq .next_allowed_tools
curl -s -XPOST localhost:8000/v1/sessions/$SID/tools/place_order   # -> 409 step_not_allowed
```

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-11-14 | First version: steps 0–8, recall order (favourites → similar orders → learned quantities → standing orders → leftovers), Discover locked without gaps, gateway-run Check, plain-language card lint, price lock, rewinds for chef changes, tips after three over-orders. Six golden scenarios. |
| 1.1.0 | 2026-11-14 | `inputs:` — one JSON Schema (draft 2020-12, `additionalProperties: false`, a description per field, examples) per tool. Validated before the tool runs: a mismatch is 422 `bad_input` with `fix.expected` and `fix.example`. MCP tools are generated from these schemas (typed parameters, no `args_json`; `call_tool` stays as a fallback). `place_order`, `request_approval` and `record_usage` take an optional `idempotencyKey`. `plan_basket` takes `acceptSuggestion`. Stock is re-checked when the order is placed (409 `stock_changed`). |

---

# The insight playbook (questions → charts)

A second set of rails, [`gateway/analytics/insight_playbook.v1.yaml`](../gateway/analytics/insight_playbook.v1.yaml),
lets any agent, even a small model, answer almost any question about a kitchen's own
data with the right chart. Same contract as ordering: tools unlock in order (`409
step_not_allowed` + `next_allowed_tools`), every input is checked (`422` with a `fix`
naming what is valid), every call is audited with the playbook version.

| # | Step | Tool | What the gateway does for the model |
|---|---|---|---|
| 0 | Start | `start_analysis {buyerId, siteId?}` | Scopes all data to one buyer (and optionally one kitchen). |
| 1 | Describe | `describe_data`, `get_values {field}` | Lists 13 measures with units, 11 dimensions, time grains, periods, operators, calcs, chart types, kitchens, plus worked examples. |
| 2 | Query | `run_query {measures, dimensions, filters, period, compare, calc, sort, limit, other}` | Compiles a whitelisted spec to SQL with bound values. Supports top-N + Other, share, running total, rank, change %, moving average, compare to previous period/year. |
| 3 | Suggest | `suggest_chart` | Ranks the chart types that fit the result's shape, with a reason each. |
| 4 | Chart | `build_chart {type, x?, y?, color?, size?}` | Writes the Vega-Lite v5 spec: line, area, column, bar, stacked, grouped, percent, heatmap, donut, scatter, bubble, histogram, boxplot, waterfall, KPI, sparkline, table. |
| 5 | Explain | `explain_result` | A plain caption and three facts (and it does not call a month that is still running "the lowest"). |

`GET /v1/tools` (and the MCP tool `list_tools`) lists every tool of both playbooks in
order, so one agent can go from the first prompt, to the order, to the analysis.

**Who answers typed questions in the app:** Claude Haiku 5.5 (low effort) drives these
tools when `ANTHROPIC_API_KEY` is set; otherwise a built-in EN/FI rule interpreter
builds the same tool calls. Both are shown step by step under "How I made this".

| Version | Date | Change |
|---|---|---|
| insight 1.0.0 | 2026-11-14 | First version: six steps, 13 measures, 11 dimensions, 17 chart types, recipes for small models. |
| insight 1.1.0 | 2026-11-14 | `inputs:` — a JSON Schema per tool (same validation and `fix` as the order playbook); MCP insight tools are typed. Datasets `agent_activity` and `demand` next to `orders` (`describe_data {dataset}`, `run_query {dataset}`); calcs `forecast` (horizon 1–6, `is_forecast` rows with `lo`/`hi`) and `anomaly` (`is_anomaly`, robust z); new tool `explain_change {measure, period_a, period_b, by}` (top 5 + Other, contributions sum to the change); two recipes for the new datasets. |
