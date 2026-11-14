# What an agent can and cannot see

The brief asks how agents can order "without exposing real systems, confidential data or the marketplace roadmap". The gateway answers this by design.

**Agents talk only to the gateway.** Only one module, [`gateway/adapter.py`](../gateway/adapter.py), talks to Valio Aimo systems. It holds the API key and the backend URL, and only for its own calls. A test proves that no other module can reach the backend and that no response carries the key or the URL (`test_5_agents_never_reach_backend_or_secrets`).

## Who can call

| Caller | Credential (demo) | Can | Cannot |
|---|---|---|---|
| Buyer's agent | `Authorization: Bearer demo-key-pohjola`, bound to one buyer and one agent | look up, start sessions, follow the playbook, place orders within authority, request approval, read its own offers, orders and audit | approve, see other buyers, change prices, skip steps, act once paused |
| Named approver | `demo-human-usr-lvirtanen` | see their inbox, approve or decline with a note, read the buyer's mandate, orders and audit | order, act for another buyer |
| Buyer's chef-app user | `demo-user-buy-pohjola` | chat with the built-in assistant, read the buyer's own board, history, insights and kitchens | approve, see other buyers |
| Valio Aimo operations | `demo-ops` | read every buyer's audit trail, pause or resume an agent (V3), read the cross-customer operations views (`/v1/ops/*`, aggregated) | approve for a buyer, see one customer's demand in the operations views |
| Anyone | – | the `.well-known` documents, `/openapi.json`, `/v1/rules`, `/v1/playbook`, `/v1/tools`, `/health` | anything with customer data |

The demo credentials are synthetic and public, and they work only in demo mode (`AIMO_DEMO=1`, the default for `make run`). With `AIMO_DEMO=0` they are refused and only tokens from `AIMO_TOKENS_FILE` work; tokens are compared in constant time. In production each agent would get OAuth 2.1 client credentials (as in the MCP authorization spec), and approvers would sign in through the buyer's own identity provider.

## What an agent sees

| Data | Exposed | Notes |
|---|---|---|
| Product master data | Name (fi/en), brand, content per sales unit, allergens and may-contain, diet claims, pack labels, origin | The same information the webshop shows |
| Price | Price per sales unit, price per kg/L, VAT rate, validity, and where it came from (`valio-aimo-mock-api` or `demo-values`) | Only the buyer's own price. No list-price or net-price internals beyond what the offer carries |
| Availability | Status (`available`, `partial`, `not_by_date`, `not_deliverable`), earliest delivery, order cutoff, and whether **your quantity** can be covered | Lookup caps the quantity at what you asked for. The planner can use more inside the gateway. |
| Delivery reliability, CO₂ | Per product, from the organisers' files | – |
| Signed offers | Price, validity, the availability promise for your need-by date, certificates | Each one is bound to the buyer that asked for it |
| Decision | Outcome plus plain reasons, rule ids and the named approver | The rules are published anyway (`/v1/rules`) |
| Own mandate, orders, audit | Yes | Only for the credential's own buyer |

## What an agent never sees

- The Valio Aimo API key, the backend URL, or raw backend responses.
- Warehouse stock levels, inbound supply, supplier names behind the terminal model, or other customers' demand.
- Other buyers' prices, orders, mandates, approvals, chats or analytics.
- Credit-limit headroom of other buyers, internal margins, cost prices.
- The marketplace roadmap: no endpoint exposes plans, supplier onboarding or unpublished assortment.
- Write access to prices, rules, mandates or approvals.

## Operations data: what Valio Aimo sees across customers

Agents state their need before they order, so the gateway sees forward demand, including needs it could not meet. `GET /v1/ops/metrics`, `/v1/ops/demand` and `/v1/ops/lost-sales` (operations credential only, MCP `ops_*` tools) show it **aggregated across customers with k ≥ 3**: a group (a day, a category, a reason) with fewer than 3 customers is suppressed and counted as `suppressed`, and nothing can be grouped by customer, kitchen, agent or approver. Buyers query the same datasets through the insight rails, but only their own rows.

## The Valio Aimo seller agent: what it may use and what it may never do

- **Uses** only the buyer's own data with Valio Aimo (favourites, past orders, the signed mandate and preferences) and the public assortment with its prices from the adapter.
- **Never** suggests anything the mandate excludes (allergens, diet, categories), the buyer's never-buy list or avoided suppliers; never adds to a basket or orders; never negotiates prices; never uses another customer's data.
- At most 3 open suggestions per buyer; a dismissed product is not suggested again for 30 days; buyers opt out with `preferences.sellerSuggestions: false` in the signed mandate (or the profile flag).
- Every suggestion is signed (`suggestion+jwt`, issuer "Valio Aimo seller agent", `promotional: true`) and every one created, shown, accepted or dismissed is audited.

## Known demo shortcuts

- The chef chat app's own endpoints (`/v1/chat`, `/v1/board`, `/v1/insights`, `/v1/kitchens`, `/v1/orders/history`) need the buyer's chef-app credential, and approving in chat needs the approver's own credential. The bundled demo page holds the demo tokens; production would use the buyer's sign-in. `/v1/demo/reset` and `/v1/demo/clock` work for operations, or for a buyer user in demo mode.
- The signed offers from the playbook include the availability promise for the buyer's need-by date (`availability.qtyAvailable`). That figure is bounded by what the gateway would deliver by that date, not the whole stock level.
- Signing keys are PEM files in `data/keys/` (git-ignored) when `AIMO_DB` is set (`make run`), so the JWKS survives a restart; in-memory test gateways generate fresh keys. Production would use KMS-held keys with rotation.
