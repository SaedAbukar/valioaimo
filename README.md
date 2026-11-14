# Aimo Agent Gateway — Valio Aimo challenge, Junction 2026

A chef types or says what they need. A purchasing agent works it out through a
**playbook the gateway enforces**, and the answer comes back as a few simple cards.

> "Gala dinner for 180 on Saturday: salmon starter, beef tenderloin, chocolate mousse.
> 12 vegan, 8 gluten-free, 1 nut allergy."
> → What I understood → Same as your Spring gala, it went well → Basket €3,205 (€17.80 per guest) → Ordered.

**The agent proposes; the gateway decides.** The agent recalls the kitchen's own
memory first, discovers only for gaps, and the gateway runs the checks (signed
offers, spending limits, allergens, delivery dates) before anything is ordered.

## Run it

```bash
make setup      # .venv + requirements (Python 3.11+)
make run        # records demo runs, builds ui/dist, serves http://127.0.0.1:8000
make test       # 118 tests, incl. the six golden playbook scenarios
make mcp        # the same tools over MCP (stdio)
```

Put the Valio Aimo mock API in `.env` (never committed):

```
AIMO_BASE_URL=https://junction26.valioaimo.fi
AIMO_API_KEY=<key from the Junction platform>
```

Without a key everything works on demo prices; `GET /health` shows whether the live API is reachable.
`ui/dist/index.html` also works with no server: it plays recorded gateway runs.

## What is in here

| Part | Where |
|---|---|
| Playbook (steps 0–8, tools, schemas, guards, wording rules) | [`gateway/playbook/order_playbook.v1.yaml`](gateway/playbook/order_playbook.v1.yaml) · [docs/PLAYBOOK.md](docs/PLAYBOOK.md) |
| State machine (409 `step_not_allowed`, schema checks, audit) | [`gateway/playbook/engine.py`](gateway/playbook/engine.py) |
| Steps | `understand.py` (EN/FI) · `recall.py` · `discover.py` · `menu.py` · `tools.py` · `cards.py` |
| Rules and trust (reused from v1) | `gateway/policy.py`, `gateway/rules.yaml`, `gateway/trust.py` (W3C VC 2.0 + ES256 offers), `gateway/audit.py` (hash chain) |
| Real Valio Aimo data | 17,546 products indexed in `gateway/data/aimo_products.json` (`make index`), mock API client in `gateway/adapter.py` · [docs/MOCK_API_NOTES.md](docs/MOCK_API_NOTES.md) |
| REST and MCP | `gateway/__main__.py`, `gateway/mcp_server.py` |
| Chat-first app | `ui/src/` → `ui/dist/index.html` · [docs/UX.md](docs/UX.md) |
| Golden scenarios | [`tests/playbook/golden.yaml`](tests/playbook/golden.yaml) |
| Architecture, data model, standards | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/data-model/](docs/data-model/), [docs/STANDARDS.md](docs/STANDARDS.md) |
| Decisions and assumptions | [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md), [PROGRESS.md](PROGRESS.md) |

## Orders, insights and kitchens (v3)

- **Orders like Jira:** board or list, keys, event colours, swimlanes, search and quick filters, a year of past orders, an activity timeline per order.
- **Insights:** *Your year*, a Wrapped-style story of the kitchen's year; *Explore*, ask in words or filter and get a chart, a caption and three facts.
- **Kitchens:** a CRM-style view of every site with KPIs and sparklines.
- **Insight playbook** ([gateway/analytics/insight_playbook.v1.yaml](gateway/analytics/insight_playbook.v1.yaml)): describe → query → suggest → chart → explain, simple enough for a small model. `GET /v1/tools` lists every tool for the whole journey.

## API for agents

```
GET  /v1/playbook                         the playbook
POST /v1/sessions                         {buyerId} -> sessionId, next_allowed_tools
POST /v1/sessions/{id}/tools/{tool}       run one step's tool
GET  /v1/sessions/{id}                    outputs per step
POST /v1/approvals/{id}                   human approver {ok, by}
GET  /v1/audit?sessionId=…                hash-chained log, verified
GET  /v1/tools                            every tool of both playbooks, in order
POST /v1/insights/sessions                {buyerId} -> analysis session
POST /v1/insights/sessions/{id}/tools/{tool}   describe_data, run_query, build_chart, …
POST /v1/insights/ask                     {buyerId, prompt, filters} -> chart + caption + facts
```

## The six golden scenarios

1. **Milk** — 1,000 L lactose-free by Monday: favourite covers 640 L, the rest from last time's good stand-in; ordered, "I'll keep you posted".
2. **Gala for 180** — recalls the last gala, learned use for salmon and beef, leftover cream used first, nut-free dessert for the allergy; ordered.
3. **New kitchen** — no history, so discovery on real Valio Aimo products and a product choice.
4. **Allergen conflict** — the only other oat drink may contain nuts: "Can't do this" with a safe alternative.
5. **Guest change** — "now 200 guests": rescaled, over the event limit, needs an OK, then the order is updated.
6. **After the event** — "How did it go?" → labels → the next gala gets a tip to order less cream.

Screenshots: [docs/screenshots/v2](docs/screenshots/v2).

The challenge data is used only for Junction 2026, as the organisers require.
