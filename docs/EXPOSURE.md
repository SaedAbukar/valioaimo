# What an agent can and cannot see

The brief asks how agents can order "without exposing real systems, confidential data or the marketplace roadmap". The gateway answers this by design.

**Agents talk only to the gateway.** Only one module, [`gateway/adapter.py`](../gateway/adapter.py), talks to Valio Aimo systems. It holds the API key and the backend URL, and only for its own calls. A test proves that no other module can reach the backend and that no response carries the key or the URL (`test_5_agents_never_reach_backend_or_secrets`).

## Who can call

| Caller | Credential (demo) | Can | Cannot |
|---|---|---|---|
| Buyer's agent | `Authorization: Bearer demo-key-pohjola`, bound to one buyer and one agent | look up, start sessions, follow the playbook, place orders within authority, request approval, read its own offers, orders and audit | approve, see other buyers, change prices, skip steps, act once paused |
| Named approver | `demo-human-usr-lvirtanen` | see their inbox, approve or decline with a note, read the buyer's mandate, orders and audit | order, act for another buyer |
| Valio Aimo operations | `demo-ops` | read every buyer's audit trail, pause or resume an agent (V3) | approve for a buyer |
| Anyone | – | the `.well-known` documents, `/openapi.json`, `/v1/rules`, `/v1/playbook`, `/v1/tools`, `/health` | anything with customer data |

The demo credentials are synthetic and public. In production each agent would get OAuth 2.1 client credentials (as in the MCP authorization spec), and approvers would sign in through the buyer's own identity provider.

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

## Known demo shortcuts

- The chef chat app's own endpoints (`/v1/chat`, `/v1/board`, `/v1/insights`, `/v1/kitchens`, `/v1/demo/reset`) are the buyer's first-party app. They run without a token in the demo; in production they would sit behind the buyer's sign-in. Agents never need them.
- The signed offers from the playbook include the availability promise for the buyer's need-by date (`availability.qtyAvailable`). That figure is bounded by what the gateway would deliver by that date, not the whole stock level.
- Keys are generated when the gateway starts, so the JWKS changes on restart. Production would use KMS-held keys with rotation.
