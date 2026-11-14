# Open standards: what we use, where, and why

The brief asks for an interface "built on open, verifiable standards rather than a single platform's black box". Each choice below is something an outside agent can read or verify without our code. Each is proven by a test in `tests/gateway/` (see [CHALLENGE_CHECKLIST.md](CHALLENGE_CHECKLIST.md)).

| Standard | Where in the gateway | Why we chose it | Production path |
|---|---|---|---|
| **OpenAPI 3.1** (JSON Schema 2020-12) | `GET /openapi.json` ([`gateway/discovery.py`](../gateway/discovery.py)): every agent-facing path, the bearer security scheme, schemas for products, offers, orders, approvals and errors | Any HTTP agent or code generator can call the gateway with no SDK. 3.1 uses plain JSON Schema, the same dialect as the playbook's output schemas. | Generate from typed models, version the spec, contract tests in CI |
| **MCP** (Model Context Protocol) | `python -m gateway.mcp_server` (40 tools): lookup, the playbook steps, offers, orders, rules, audit and insights. The identity comes from `AIMO_AGENT_TOKEN`. | It is the de-facto tool interface for LLM agents (Claude, and others through adapters). Same handlers and same state machine as REST, so the two can't drift apart. | Remote MCP (Streamable HTTP) with OAuth 2.1, as in the MCP authorization spec |
| **UCP-style business profile** | `GET /.well-known/ucp`: services (REST, MCP, A2A), capabilities (catalog, checkout, order, approval, playbook), trust keys, rules, payment terms | Commerce agents look for a well-known profile first. Shaping ours like the Universal Commerce Protocol keeps Valio Aimo discoverable without a platform lock-in. | Conform to the published UCP schemas as they stabilise |
| **A2A agent card**, JWS-signed | `GET /.well-known/agent-card.json`: skills (lookup, order, approval), security scheme, signature | Lets another agent find out what this gateway can do and check it really is Valio Aimo's. It also leaves room for a Valio Aimo seller agent later (proactive offers). | Card served from the real domain, `did:web` issuer |
| **JWKS + JWS ES256** (RFC 7515/7517/7518) | `GET /.well-known/jwks.json`. Signed offers (`vc+jwt`), order confirmations (`order+jwt`), the agent card, buyer mandates | Verifiable with any JOSE library and no shared secret: the agent checks a price or a confirmation itself (demo A does this client-side). | Keys in KMS/HSM, rotation, `kid` per period |
| **W3C Verifiable Credentials 2.0** | Each offer is an `OfferAttestation` VC: price, validity (15 min), availability as of a timestamp, origin, certificates, `credentialStatus` for revocation | Answers the organisers' "trust protocol" question with an existing data model, so claims about price, stock and origin are checkable without a manual call. | Bitstring Status List for revocation; certificate VCs issued by the certifiers themselves |
| **AP2-style Intent Mandate** (agent payments protocol) | Signed by a named buyer admin: limits per order, month, event and guest, allergen exclusions, substitution tolerance. `GET /v1/mandate`, MCP `whoami`. Checked on every session (rule R0). | Binds the agent's authority to a human signature, the "signed authority" in trust both ways. The signed order confirmation plays the role of a Cart Mandate. | Mandates issued from the buyer's identity provider, with revocation and delegation |
| **OAuth-style bearer credentials** | `Authorization: Bearer …` bound to one buyer and one agent, or a named approver, or operations ([`gateway/auth.py`](../gateway/auth.py)) | One header is enough for any HTTP or MCP client, and it ties identity to a customer account. | OAuth 2.1 client credentials, DPoP or mTLS for sender-constrained tokens |
| **GS1** (GTIN, Digital Link, GDSN fields) | Real product GTINs, `packagingMarkedLabel` labels (Hyvää Suomesta, Avainlippu, EU organic, MSC…), GS1 allergen codes mapped to EU-14 | The organisers' product data is GS1/Synkka-based, so we keep its identifiers rather than invent new ones. | GDSN master data; EPCIS 2.0 events for traceability |
| **EU FIC 1169/2011 Annex II** | The 14 allergens as a closed list in products, mandates and guest needs; "may contain" honoured | Allergen safety (school and hospital scenarios) must use the regulatory list. | Allergen data verified at the supplier |
| **Policy as code** | [`gateway/rules.yaml`](../gateway/rules.yaml) plus a deterministic evaluator, published at `GET /v1/rules` as an autonomy matrix | Rules an agent can read before acting, and a gateway (not an LLM) that applies them. | OPA/Rego bundles, signed and versioned, with policy tests |
| **Hash-chained audit** (EU AI Act Art. 12 and 14 as good practice) | Every call is an `audit_event` with the playbook version, actor, plain reason and SHA-256 chain. `GET /v1/audit` verifies the chain. | A log both the buyer and Valio Aimo can trust and read. | Retention policy, external anchoring of the chain |

**Not used, on purpose.** x402 and other agent-payment rails are left out: foodservice B2B orders are invoiced on the customer's account, and the brief lists payment standards as context only.

## Pilot metrics (what we would measure with Valio Aimo)

- Share of orders the agent completes alone (AUTO plus tell-me)
- Manual-correction rate
- Approval wait time, median and 90th percentile
- Need-by hit rate and fill rate
- Substitute acceptance
- Offer re-quote rate
- Blocked requests, and how many of those blocks turn out to be false on review
- Time from request to confirmed order
