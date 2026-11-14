# Open standards and the production path

| Standard | How the MVP uses it | Production path |
| --- | --- | --- |
| **OpenAPI 3.1 / JSON Schema 2020-12** | Contract for the REST facade (`docs/API.md`, `/openapi.json` sketch) | Generate from typed models; publish versioned spec; contract tests in CI |
| **UCP (Universal Commerce Protocol)-shaped capabilities** | `/.well-known/ucp` profile; catalog → offers → checkout → order lifecycle | Conformance to the published UCP checkout capability once stable; certification against reference agents |
| **MCP** | Same handler set as tools (`search_products`, `request_offers`, `plan_fulfilment`, `create_checkout`, `complete_checkout`, `get_order`, `explain_decision`, `plan_event_from_brief`, …); approvals returned as `requires_approval` + `approvalId` (URL-mode elicitation) | Remote MCP server with OAuth; elicitation to a Valio Aimo-hosted approval page |
| **A2A agent card** | Signed agent card at `/.well-known/agent-card.json` | Seller agent (A2A) for proactive offers: stock-out alerts, replenishment suggestions |
| **AP2 mandates** | Intent Mandate signed by a named human (limits, exclusions, tolerance, preference-profile reference); signed order confirmation = Cart Mandate | Mandates issued from the buyer's IdP; revocation; delegated approver chains |
| **W3C VC 2.0 + JOSE (JWS ES256)** | Offer Attestations as `vc+jwt` with `credentialSubject`, `validFrom/validUntil`, `credentialStatus` | `did:web:gateway.valioaimo.fi` issuer; HSM/KMS keys; **Bitstring Status List** for revocation; certificate credentials issued by certifiers (EU Organic, MSC, Fairtrade, Hyvää Suomesta) → trust level L2 |
| **GS1 GTIN & Digital Link** | GTIN-14 keys (valid check digits, fictional prefix) and `https://id.gs1.org/01/{gtin}` links | Master data from **GS1 GDSN**; **EPCIS 2.0** events for traceability → trust level L3 |
| **EU FIC 1169/2011 Annex II** | 14-allergen closed enum for products, mandate exclusions and guest allergies; “may contain” honoured | Allergen data from supplier PIM with verification status |
| **EU AI Act Art. 12 & 14 (best practice)** | Hash-chained logging; human oversight via one consolidated approval with override, name and reason | Retention policy, log anchoring, model cards for any LLM component |
| **Policy as code** | `rules.yaml` + deterministic evaluator, templated reasons | **OPA/Rego** bundles, signed and versioned; policy tests; buyer-specific packs |

x402 / agent payments are out of scope: B2B foodservice invoices on account.

## Pilot metrics (what we would measure with Valio Aimo)
Autonomous rate (AUTO + NOTIFY share), manual-correction rate, approval latency p50/p90, need-by hit and fill rate, substitute acceptance, utilisation & waste € per event, offer re-quote rate, blocked-request rate and false-block reviews, time from request to confirmed order, cost per guest vs target.
