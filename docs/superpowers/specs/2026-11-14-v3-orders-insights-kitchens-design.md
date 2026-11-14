# v3 design: Jira-style orders, Wrapped + Explore insights, CRM-style kitchens

Date: 14 Nov 2026. Status: approved by the user ("you can decide… go ahead").

## Intent

Chefs should run a whole kitchen group from the app: see every order like a Jira
board, understand their year at a glance (Spotify Wrapped feel), and ask any question
about their data and get the right chart. Any agent, even a small model, must be able
to do the whole journey through gateway tools: from the first prompt, to the order,
to complex analysis.

## Goals

1. **Orders like Jira.** Board (columns) or List (rows), switchable. Issue keys
   (`POH-42`), event colour labels, swimlanes / group by (status, event, site), quick
   filters (search, event, site, status, due soon), sort, an activity timeline per order
   (from the audit log, in plain words). Past orders (a year of history) live here too,
   searchable and sortable; analysis lives in Insights. No extra top-level tab.
2. **Insights › Your year** (simple): Wrapped-style story of big numbers and charts:
   total spend, top products, top event, waste trend, CO₂, "your kitchen personality",
   best-run event, on-time deliveries. Tap through, full-bleed colour cards.
3. **Insights › Explore** (advanced): filters (site, period, category, event) + a prompt
   box. An agent answers with a chart, a caption and three facts. Saved questions as chips.
4. **Analytics toolkit** (`insight_playbook.v1.yaml`), detailed and broad, with the same
   rails as ordering (409 out of order, schema-checked inputs, fix-it hints, audit):
   `describe_data → get_values → run_query → suggest_chart → build_chart → explain_result`.
   Query spec: measures × aggregations, dimensions with time grains, filters (eq, in,
   between, contains, gte/lte), compare to previous period, calcs (share, running total,
   rank, change %, moving average), sort, top-N + "other". Charts: line, area, bar, column,
   stacked/grouped/100%, scatter, bubble, heatmap, treemap-like, donut, waterfall,
   histogram, boxplot, KPI, sparkline, table. Output is a Vega-Lite spec the gateway
   builds from a small chart intent, so a model never writes Vega-Lite itself (advanced
   agents may pass extra encodings, which are validated).
5. **Who answers typed questions:** Claude Haiku 5.5 drives the toolkit when
   `ANTHROPIC_API_KEY` is set; otherwise a built-in rule-based interpreter maps common
   phrasing (EN/FI) to the same tool calls. Both go through the same rails.
6. **Kitchens (was Settings), CRM style.** Org header + list of sites as cards with KPIs
   (spend this month, open orders, waste trend sparkline, next delivery), site detail
   with tabs: Overview, People, Favourites, Rules (limits, allergens), Deliveries.
   Pohjola becomes a chain of 3 hotels. Appearance moves to a small section at the end.
7. **Look.** Material 3 tonal palette built around turquoise (primary) and sky blue,
   with state layers (hover / press), surface containers, a categorical event palette,
   SVG icons, livelier motion that respects reduced motion. Still light + dark.

## Non-goals / anti-goals

- No raw SQL from models; queries only through the validated spec.
- No drag-and-drop status changes (status follows real events: approval, delivery).
- Do not break the six golden ordering scenarios or the plain-language card rules.
- Nothing that makes a chef feel lost: Explore must show a chart for the starter chips
  without typing anything.

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| A. Own SVG chart renderer | No dependency, but "almost any chart" means months of work | Rejected |
| **B. Gateway builds Vega-Lite specs from a small chart intent; page renders with vega-embed (CDN)** | Huge chart range, well-known spec, needs the CDN | **Chosen** |
| C. Model writes Vega-Lite directly | Flexible, but small models fail often | Rejected (allowed only as validated extra encodings) |

Data: a deterministic generator (`scripts/gen_history.py`) builds 12 months of orders
per site from the curated catalogue, recipes and event calendar, loaded into SQLite at
start. Queries run on SQLite through the spec compiler.

## Left to the builder

Exact Wrapped card copy, colour values, chart defaults per shape, the rule-based
phrase list, and how many history orders (aim: ~1,500 orders, ~20k lines).
