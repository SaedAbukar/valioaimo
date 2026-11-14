# API for agents

The full contract is **`GET /openapi.json`** (OpenAPI 3.1). The same handlers are available as MCP tools over Streamable HTTP at **`POST /mcp`** on the same gateway (or `make mcp`, a stdio proxy to it); `GET /v1/tools` lists every tool in order, with its REST path. All `/v1` calls except rules, playbook and tools need `Authorization: Bearer <credential>` ([EXPOSURE.md](EXPOSURE.md)).

## Discovery (no credential)

| Endpoint | What it gives |
|---|---|
| `GET /.well-known/ucp` | UCP-style profile: services, capabilities, trust keys, rules, playbook |
| `GET /.well-known/agent-card.json` | A2A agent card, JWS-signed |
| `GET /.well-known/jwks.json` | Keys for offers, order confirmations, the card |
| `GET /openapi.json` | The contract |
| `GET /v1/rules` | Autonomy matrix: alone / alone and tell / named human / never |
| `GET /v1/playbook`, `GET /v1/tools` | The enforced steps; every tool in order |

## Lookup (agent; read-only, no commitment)

| Endpoint | MCP | Body |
|---|---|---|
| `POST /v1/products/search` | `lookup_products` | `{query, qty?, needBy?, excludeAllergens?, diet?, limit?}` (schema-checked: 422 `bad_input` with `fix.example`) |
| `POST /v1/products/price-availability` | `get_price_availability` | `{productIds[], needBy?, qty?}` |
| `GET /v1/products/{productId}` | `get_product` | – |

## Ordering: the playbook (agent)

| Endpoint | Notes |
|---|---|
| `POST /v1/sessions` | Start, for the credential's buyer. Returns `sessionId` and `next_allowed_tools`. |
| `POST /v1/sessions/{id}/tools/{tool}` | One step. Out of order: `409 step_not_allowed`. Bad input: `422 guard_failed` with `fix`. |
| `GET /v1/sessions/{id}` | Outputs per step |
| `GET /v1/sessions/{id}/log` | Plain-language log of what was done and why |
| `GET /v1/sessions/{id}/events?after=N&wait=0..25` | Push updates (long-poll): `step.completed`, `decision.made`, `approval.requested`, `approval.decided`, `order.placed`, `offer.expiring`, `suggestion.created`; returns `{events, next, next_allowed_tools}`. MCP `wait_for_update`. |

Every tool's input has a JSON Schema in the playbook (`inputs:`, 1.1.0) and in `/v1/tools` (`inputSchema`); a mismatch is `422 bad_input` with `fix.expected` and `fix.example`. State-changing calls (`POST /v1/sessions`, `place_order`, `request_approval`, `record_usage`, approval decisions, suggestion feedback) accept an **`Idempotency-Key`** header (or `idempotencyKey` field): a retry returns the stored response with `Idempotent-Replay: true`. Every credential has a rate limit: `429 rate_limited` with `Retry-After`.

The usual path is `parse_request {text}`, then `recall`, then `request_offers` (only for gaps), then `plan_basket` (returns `offers[]`), then `check_basket` (run by the gateway), then `render_cards`. After that the agent calls **`place_order {offerIds}`**, or `request_approval` and, after the human's OK, `place_order {offerIds}`.

`place_order` errors:

| Response | When |
|---|---|
| `422 cite_offers` | No `offerIds` were sent |
| `422 fixed_prices` | A price field was sent |
| `409 offer_mismatch` | The ids are not the checked basket's (re-quote) |
| `409 price_locked` | An offer expired or the price changed (re-quote) |
| `409 stock_changed` | Someone else got the stock since the quote; `shortfall` says what is short (re-quote) |
| `422 agent_paused` | Valio Aimo operations paused this agent (any tool, mid-session) |

## Trust

| Endpoint | MCP |
|---|---|
| `GET /v1/mandate`: the buyer's signed Intent Mandate and the buyer's JWKS | `whoami` |
| `GET /v1/offers/{id}`: the signed offer (`vc+jwt`) | `get_offer` |
| `POST /v1/offers/{id}/verify`: six checks | `verify_offer` |
| `GET /v1/orders/{id}`: the order and its signed confirmation (`order+jwt`), already verified | `get_order` |

## Approvals (named human credential only; agents get 403)

| Endpoint | |
|---|---|
| `GET /v1/approvals` | The approver's inbox |
| `POST /v1/approvals/{approvalId}` | `{ok, note?}`. The decision is recorded and audited, and `approvedBy` goes into the signed confirmation. |

## Suggestions from Valio Aimo's seller agent (agent)

| Endpoint | MCP | Notes |
|---|---|---|
| `GET /v1/suggestions` | `get_suggestions` | At most 3, signed `suggestion+jwt`, `promotional: true`; never outside the mandate |
| `POST /v1/suggestions/{id}/feedback` | `suggestion_feedback` | `{decision: accepted\|dismissed, reason?}`; dismissed: not again for 30 days |
| `plan_basket {acceptSuggestion}` | `plan_basket` | Uses one: re-plans and re-checks; never an order by itself |

## Audit and operations

| Endpoint | Who |
|---|---|
| `GET /v1/audit?sessionId=` | The buyer's own trail (agent or approver); every buyer with the ops credential. Includes chain verification. |
| `POST /v1/ops/agents/{agentId}/pause` `{paused, reason}` | Valio Aimo operations (kill switch V3) |
| `GET /v1/ops/metrics` | Operations: agent-channel metrics across customers (k ≥ 3) plus raw counters (calls, decision mix, 409/422 rates, adapter latency, breaker) |
| `GET /v1/ops/demand?by=day\|category\|product&from&to` | Operations: forward demand from agents' plans (k ≥ 3) |
| `GET /v1/ops/lost-sales` | Operations: what agents could not get, and why (k ≥ 3) |
| `GET /v1/ops/orders`, `GET /v1/ops/inventory` | Operations: every order with its confirmation; stock and schedule (used by the benchmark's invariants) |
| `GET /v1/ops/metrics-raw` | Operations: raw counters only |

## The chef app (first-party UI, not for agents)

`/v1/chat`, `/v1/chat/{id}/actions`, `/v1/board`, `/v1/orders/history`, `/v1/insights/*`, `/v1/kitchens` need the buyer's chef-app credential; approving in chat needs the approver's own. The insight playbook (`/v1/insights/sessions/...`, buyer from the credential) is also usable by agents: datasets `orders`, `agent_activity`, `demand`; calcs `forecast` and `anomaly`; tool `explain_change`. See [PLAYBOOK.md](PLAYBOOK.md).
