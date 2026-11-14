# API contract (summary)

One handler set, two facades: **REST** described by OpenAPI 3.1 (JSON Schema 2020-12, UCP-shaped capabilities) and **MCP** tools with the same semantics. The reference server (`python -m gateway`) implements the endpoints marked ✅; the MVP page implements all of them client-side (`ui/src/flows.js`).

## Discovery
| Endpoint | Purpose | |
| --- | --- | --- |
| `GET /.well-known/ucp` | Capability profile (protocols, capabilities, trust parameters) | ✅ |
| `GET /.well-known/agent-card.json` | A2A-style agent card, signed (JWS ES256) | ✅ |
| `GET /.well-known/jwks.json` | Gateway public keys for verifying offers, cards, confirmations | ✅ |
| `GET /openapi.json` | Contract | ✅ (sketch) |

## Auth
`Authorization: Bearer <agent credential>` bound to exactly one buyer account; every request is evaluated against that buyer's current signed Intent Mandate (R0). Per-agent rate limit → `429 rate_limited` + `Retry-After`. Kill switch → `403 policy_blocked` (V3).

## Buying
| Method & path | MCP tool | Notes |
| --- | --- | --- |
| `POST /v1/catalog/search` ✅ | `search_products` | L0, browse-only; `{query, category, diet, excludeAllergens}` |
| `GET /v1/products/{gtin}` | `get_product` | GS1 Digital Link in payload |
| `POST /v1/offers` | `request_offers` | Offer Attestations (VC 2.0, `vc+jwt`), valid 15 min |
| `POST /v1/offers/verify`, `GET /v1/offers/status` | — | six checks; revocation status list |
| `POST /v1/plans` ✅ | `plan_fulfilment` | ranked candidates with score breakdown, exclusions with reasons, ≤3 plans, policy preview |
| `POST /v1/compare` | `compare_products` | 2–4 products with buyer history |
| `POST /v1/checkout-sessions` | `create_checkout` | `status: ready \| requires_approval \| blocked`, decisions, `approvalId` (URL-mode elicitation) |
| `POST /v1/checkout-sessions/{id}/complete` | `complete_checkout` | re-verifies; errors `offer_expired`, `price_changed`, `insufficient_stock`, `delivery_unavailable` |
| `GET /v1/orders/{id}` | `get_order` | signed order confirmation (Cart Mandate) |
| `GET /v1/approvals?status=pending`, `POST /v1/approvals/{id}/decision` | — | per-line approve / reject / modify, approver id + reason |
| `GET /v1/decisions/{id}/explain` | `explain_decision` | rule hits with templated reasons |

## Governance
`POST /v1/mandates` (signed by buyer key; versions) · `GET/PUT /v1/preferences` (org / site / category scope; versions) · `POST /v1/preferences/favourites` · `GET /v1/need-groups/{id}/products` · `GET /v1/rules` ✅ · `GET /v1/audit?traceId=` · `GET /v1/audit/verify` ✅ · `POST /v1/ops/agents/{id}/kill-switch`.

## Events, usage & insights
`POST /v1/events/intake` · `POST /v1/events/{id}/plan` · `PATCH /v1/events/{id}` · `POST /v1/orders/{id}/reconciliation` · `GET /v1/events/{id}/report` · `GET /v1/leftovers` · `GET /v1/insights/waste` · `GET /v1/processes` (+ `/{id}`, `/export?format=csv|json`) · `GET /v1/insights/summary` · `GET /v1/insights/recommendations` (+ `POST …/{id}/apply`) · `GET /v1/signals` · `DELETE /v1/buyers/{id}/data?scope=` · MCP `plan_event_from_brief`, `record_consumption`, `get_waste_insights`, `get_leftovers`, `get_buying_insights`, `get_preferences`.

## Error codes
`offer_expired` · `price_changed` · `insufficient_stock` · `delivery_unavailable` · `policy_blocked` (rule ids) · `approval_required` (approvalId) · `mandate_invalid` · `rate_limited` (Retry-After).

## Example: plan with policy preview
```bash
curl -s -X POST localhost:8000/v1/plans -H 'content-type: application/json' \
  -d '{"buyerId":"BUY-POHJOLA","lines":[{"lineId":"L1","text":"lactose-free milk","qty":1000,"unit":"L"}],"needBy":"2026-11-16"}'
# P1 640 L Kaarna Meijeri + 360 L Maitokaari — €1,304.40 → NOTIFY [R4, R6]
# P2 1,000 L Tunturi Dairy — €1,410.00 → APPROVE [R5, R8]
# P3 640 L Mon + 360 L Wed — €1,290.00 → APPROVE [R7]
```
