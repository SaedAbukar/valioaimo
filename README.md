# Aimo Agent Gateway: Valio Aimo challenge, Junction 2026

**How Valio Aimo can be safely and openly readable by autonomous purchasing agents.**

The judged product is the **gateway**: an agent-facing interface with a structured lookup, fixed-price signed offers, orders that cite those offers, and published guardrails. Anything outside the agent's authority goes to a named human. Any agent can use it over REST (OpenAPI 3.1) or MCP. It follows an enforced playbook and is checked against open standards. The chef chat app in `ui/` is just one example client.

> "I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability."
>
> An external agent hits the gateway, looks up products, prices and availability from the Valio Aimo mock API, and plans from the kitchen's favourite. The gateway checks the signed offer against the signed mandate, and the order is placed with a signed confirmation, in under a second. At 3,000 L the same request needs Laura Virtanen's OK. The agent cannot give that OK itself.

**The agent proposes; the gateway decides.**

| Requirement | Answer |
|---|---|
| Product, price and availability lookup | `POST /v1/products/search` and MCP `lookup_products`. JSON with price per sales unit and per kg/L, availability for your need-by date, delivery reliability, CO₂ and pack labels. Live from the mock API through [`gateway/adapter.py`](gateway/adapter.py). |
| Inquiry to commitment at fixed prices | Each basket line rests on a signed, 15-minute offer (W3C VC as `vc+jwt`). `place_order` must cite those offer ids. A changed or expired price means re-quote. Price fields are rejected: there is no negotiation. The order confirmation is signed. |
| Permissions and human approval | `GET /v1/rules` publishes what the agent decides alone, what it decides and reports, what needs a named human and what is never allowed. The gateway evaluates them, not the LLM. Approvals go to a named person's inbox; an agent credential gets 403. |
| No exposure, open standards, trust both ways | See [EXPOSURE](docs/EXPOSURE.md) and [STANDARDS](docs/STANDARDS.md). Credentials are bound to one customer account; a signed buyer mandate gives the agent its authority; the agent can verify every offer and confirmation with the JWKS. |

The full audit is in **[docs/CHALLENGE_CHECKLIST.md](docs/CHALLENGE_CHECKLIST.md)**: every item is PASS, PARTIAL or not built, with where it lives, the test that proves it and how to demo it.

## Run it

```bash
make setup      # .venv + requirements (Python 3.11+)
make index      # builds gateway/data/aimo_products.json from the organisers' data in data_raw/ (not in git)
make run        # gateway + chef app on http://127.0.0.1:8000
make agent      # an external agent places the brief's order (scripts/agent_demo.py)
make test       # 134 tests (+1 live test: AIMO_LIVE_TESTS=1)
make mcp        # the same gateway over MCP (stdio), as AIMO_AGENT_TOKEN's agent
```

Put the Valio Aimo mock API in `.env` (git-ignored, never committed):

```
AIMO_BASE_URL=https://junction26.valioaimo.fi
AIMO_API_KEY=<key from the Junction platform>
```

Without a key everything runs on deterministic demo values, and each price says which source it came from. `GET /health` shows whether the mock API is reachable.

## 3-minute demo

**0:00 Discovery (30 s).** The gateway describes itself to any agent.

```bash
curl -s localhost:8000/.well-known/ucp | jq '.ucp.capabilities[].name, .trust'
curl -s localhost:8000/v1/rules | jq '.autonomy | {needsNamedHumanOk: [.needsNamedHumanOk[].title], neverAllowed: [.neverAllowed[].title]}'
```

**0:30 The brief's request, by an external agent (60 s).** The script uses only HTTP and the gateway; it has no UI and no access to the backend.

```bash
python scripts/agent_demo.py
```

The script prints each step:

| Step | What it shows |
|---|---|
| discover | The gateway's profile and signing keys |
| authority | The buyer's mandate, signed by Laura Virtanen, with the €2,000 per-order limit |
| lookup | Five real lactose-free milks with live prices, Monday availability and reliability |
| rails | `place_order` called too early is refused with 409 |
| understand | 1,000 L by Mon 16.11. |
| recall | The favourite, so no search is needed |
| plan | The plan rests on a signed offer priced by the mock API |
| check | The gateway decides AUTO |
| act | The order, with its signed confirmation, checked by the agent with the JWKS |

The whole run takes under a second.

**1:30 Approval (45 s).** The same request at 3,000 L.

```bash
python scripts/agent_demo.py --over-limit
```

| Step | What it shows |
|---|---|
| check | NEEDS_OK: over the spending limit for one order |
| approval | Sent to Laura Virtanen, Head of Procurement |
| rails | The agent tries to approve itself and gets 403 |
| inbox | Laura's inbox shows the request |
| human | Laura approves with her own credential |
| act | The agent places the order; the confirmation names her as approver |
| log | The plain-language audit trail |

**2:15 The chef app as one client (45 s).** Open http://127.0.0.1:8000. A chef types the gala dinner request and gets cards back: what I understood, from your favourites, basket, ordered. The app runs the same playbook and the same rules.

| Screen | What to show |
|---|---|
| Orders | The Jira-style board |
| Insights | The kitchen's year |
| Kitchens | The CRM-style view |

**Same thing over MCP.** Add `python -m gateway.mcp_server` to Claude Desktop or Claude Code and ask for the milk order. The tools are `lookup_products`, the playbook tools, `get_order` and the others; there is no approve tool.

## What is in here

| Part | Where |
|---|---|
| Agent API (REST + discovery) | [`gateway/__main__.py`](gateway/__main__.py), [`gateway/discovery.py`](gateway/discovery.py) (OpenAPI 3.1, UCP, agent card) · [docs/API.md](docs/API.md) |
| Lookup through the mock API | [`gateway/lookup.py`](gateway/lookup.py) → [`gateway/adapter.py`](gateway/adapter.py) · [docs/MOCK_API_NOTES.md](docs/MOCK_API_NOTES.md) |
| Identity and credentials | [`gateway/auth.py`](gateway/auth.py) · [docs/EXPOSURE.md](docs/EXPOSURE.md) |
| Playbook (steps 0–8) and state machine | [`gateway/playbook/order_playbook.v1.yaml`](gateway/playbook/order_playbook.v1.yaml), [`engine.py`](gateway/playbook/engine.py) · [docs/PLAYBOOK.md](docs/PLAYBOOK.md) |
| Offers, orders, approvals | [`gateway/trust.py`](gateway/trust.py) (VC 2.0 + ES256, six checks), [`gateway/playbook/tools.py`](gateway/playbook/tools.py) (`place_order`, `request_approval`, `decide_approval`) |
| Rules | [`gateway/rules.yaml`](gateway/rules.yaml), [`gateway/policy.py`](gateway/policy.py) |
| Audit | [`gateway/audit.py`](gateway/audit.py) (hash chain) |
| MCP | [`gateway/mcp_server.py`](gateway/mcp_server.py) |
| External agent example | [`scripts/agent_demo.py`](scripts/agent_demo.py) |
| Chef app (example client) | `ui/src/` → `ui/dist/index.html` · [docs/UX.md](docs/UX.md) |
| Insight playbook (questions → charts) | [`gateway/analytics/`](gateway/analytics/) · [docs/PLAYBOOK.md](docs/PLAYBOOK.md#the-insight-playbook-questions--charts) |
| Tests | `tests/gateway/` (challenge checklist, MCP parity, live), `tests/playbook/` (golden scenarios, rails), `tests/analytics/` |
| Standards, architecture, decisions | [docs/STANDARDS.md](docs/STANDARDS.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md), [PROGRESS.md](PROGRESS.md) |

## The six golden scenarios (through the playbook)

1. **Milk.** 1,000 L lactose-free by Monday. Offline: the favourite covers 640 L and last time's good substitute the rest. Live: the favourite covers everything.
2. **Gala for 180.** Recalls the last gala and the use per guest it learned; leftover cream is used first; the guest with a nut allergy gets a nut-free dessert.
3. **New kitchen.** No history, so discovery runs over the real Valio Aimo products and the chef picks one.
4. **Allergen conflict.** "Can't do this", with a safe alternative.
5. **Guest change.** At 200 guests the order is rescaled, goes over the event limit and needs an OK.
6. **After the event.** "How did it go?" saves what was used; the next gala gets a tip to order less cream.

Screenshots: [docs/screenshots/v2](docs/screenshots/v2).

The challenge data is used only for Junction 2026, as the organisers require. The indexed product file is therefore not in git; `make index` rebuilds it from the portal download.
