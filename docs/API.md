# API for agents

The full contract is **`GET /openapi.json`** (OpenAPI 3.1). The same handlers are available as MCP tools (`make mcp`); `GET /v1/tools` lists every tool in order, with its REST path. All `/v1` calls except rules, playbook and tools need `Authorization: Bearer <credential>` ([EXPOSURE.md](EXPOSURE.md)).

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
| `POST /v1/products/search` | `lookup_products` | `{query, qty?, needBy?, excludeAllergens?, diet?, limit?}` |
| `POST /v1/products/price-availability` | `get_price_availability` | `{productIds[], needBy?, qty?}` |
| `GET /v1/products/{productId}` | `get_product` | – |

## Ordering: the playbook (agent)

| Endpoint | Notes |
|---|---|
| `POST /v1/sessions` | Start, for the credential's buyer. Returns `sessionId` and `next_allowed_tools`. |
| `POST /v1/sessions/{id}/tools/{tool}` | One step. Out of order: `409 step_not_allowed`. Bad input: `422 guard_failed` with `fix`. |
| `GET /v1/sessions/{id}` | Outputs per step |
| `GET /v1/sessions/{id}/log` | Plain-language log of what was done and why |

The usual path is `parse_request {text}`, then `recall`, then `request_offers` (only for gaps), then `plan_basket` (returns `offers[]`), then `check_basket` (run by the gateway), then `render_cards`. After that the agent calls **`place_order {offerIds}`**, or `request_approval` and, after the human's OK, `place_order {offerIds}`.

`place_order` errors:

| Response | When |
|---|---|
| `422 cite_offers` | No `offerIds` were sent |
| `422 fixed_prices` | A price field was sent |
| `409 offer_mismatch` | The ids are not the checked basket's (re-quote) |
| `409 price_locked` | An offer expired or the price changed (re-quote) |

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

## Audit and operations

| Endpoint | Who |
|---|---|
| `GET /v1/audit?sessionId=` | The buyer's own trail (agent or approver); every buyer with the ops credential. Includes chain verification. |
| `POST /v1/ops/agents/{agentId}/pause` `{paused, reason}` | Valio Aimo operations (kill switch V3) |

## The chef app (first-party UI, not for agents)

`/v1/chat`, `/v1/chat/{id}/actions`, `/v1/board`, `/v1/orders/history`, `/v1/insights/*`, `/v1/kitchens`. The insight playbook (`/v1/insights/sessions/...`) is also usable by agents; see [PLAYBOOK.md](PLAYBOOK.md).
