# Architecture

Principle: **the agent proposes; the deterministic gateway decides.** Every claim the agent acts on is signed; every decision is a rule id with a templated reason; every step is written by the gateway into a hash-chained ledger.

## 1. Context (C4 level 1)

```mermaid
flowchart LR
  chef([Chef / kitchen manager<br/>voice or text]) --> agent
  admin([Procurement admin<br/>signs mandate & preferences]) --> wallet
  approver([Approver]) --> gw
  agent[Buyer purchasing agent<br/>any vendor, MCP/REST] -->|API credential bound to 1 buyer<br/>+ signed Intent Mandate| gw
  wallet[Buyer mandate wallet<br/>ES256 key] --> agent
  gw[[Aimo Agent Gateway]] -->|adapter| valio[(Valio Aimo systems<br/>catalog · price & stock · orders)]
  ops([Valio Aimo operations]) --> gw
```

## 2. Containers

```mermaid
flowchart TB
  subgraph Buyer side
    A[Purchasing agent]:::b
    W[Mandate wallet]:::b
    H[Approver UI]:::b
  end
  subgraph Gateway[Aimo Agent Gateway — trust boundary]
    D[Discovery<br/>/.well-known/ucp · agent-card.json · jwks.json]
    F[REST + MCP facade<br/>one handler set]
    EA[Event Autopilot]
    P[Planner & ranking]
    S[Offer signer<br/>VC 2.0 / JWS ES256]
    PE[Policy engine<br/>rules.yaml → OPA/Rego]
    L[Audit ledger<br/>SHA-256 chain]
    O[Outcome store & learning<br/>3NF model + sig_* views]
    AD[Backend adapter]
  end
  subgraph Valio Aimo
    C[(Catalog / PIM)]
    PS[(Price & stock)]
    OR[(Order & delivery)]
    OPS[Ops console]
  end
  A --> D & F
  W --> F
  H --> F
  F --> EA --> P
  F --> P --> S
  P --> PE
  F --> PE
  PE --> L
  F --> L
  F --> O
  O --> P
  S --> AD
  P --> AD
  AD --> C & PS & OR
  OPS --> PE
  classDef b fill:#ffd9de,stroke:#9a3b4e
```

## 3. Components and responsibilities

| Component | Responsibility | Standard | Code (MVP page / Python reference) |
| --- | --- | --- | --- |
| Discovery | Capability profile, signed agent card, JWKS | UCP-shaped profile, A2A agent card | `gateway/__main__.py` |
| Facade | One handler set as OpenAPI 3.1 REST and MCP tools | OpenAPI 3.1, JSON Schema 2020-12, MCP | `docs/API.md` |
| Planner | Need resolution → hard filters (logged) → case rounding → buyer-weighted score → tiers → ≤3 plans | GS1 GTIN, need groups | `engine.js planLine/buildPlans`, `gateway/planner.py` |
| Offer signer | Offer Attestations, 15-min price, 5-min stock freshness, status list | W3C VC 2.0 + JWS ES256 | `engine.js issueOffer/verifyOffer`, `gateway/trust.py` |
| Policy engine | R0–R14 (buyer mandate) + V1–V3 (Valio Aimo), strictest wins | rules.yaml (prod: OPA/Rego) | `engine.js policyEvaluate`, `gateway/policy.py` |
| Audit ledger | Append-only hash chain, templated sentences | EU AI Act Art. 12-style | `engine.js audit*`, `gateway/audit.py` |
| Event Autopilot | Brief → recipes → scaled, right-sized → leftovers → sourced → scheduled → one decision | — | `flows.js parseBrief/planEvent` (see EVENT_AUTOPILOT.md) |
| Outcome store | Curated ProcessRecord per request; labels, metrics, signals, recommendations | 3NF model in `docs/data-model` | `flows.js closeProcess/kpis/recommendations` |
| Adapter | Only place that touches Valio Aimo systems; fixtures or mock API | — | `gateway/adapter.py` |

## 4. Main sequence: request → order

```mermaid
sequenceDiagram
  autonumber
  participant Ag as Buyer agent
  participant GW as Gateway facade
  participant PL as Planner
  participant SG as Offer signer
  participant PE as Policy engine
  participant AU as Audit ledger
  participant H as Approver
  participant VA as Valio Aimo (adapter)
  Ag->>GW: discover (/.well-known), credential + Intent Mandate
  GW->>PE: R0 mandate signature & validity
  Ag->>GW: plan_fulfilment("1,000 L lactose-free milk by Mon")
  GW->>PL: resolve need, filter (reasons), rank with preferences
  PL->>VA: price & stock by date
  PL->>SG: sign offers (VC 2.0, ES256)
  GW->>PE: policy preview per plan
  GW-->>Ag: tiers + plans + verdicts (AUTO/NOTIFY/APPROVE/BLOCK)
  GW->>AU: search, filtered, quote, plan
  Ag->>GW: create_checkout(planId)
  GW->>SG: re-verify 6 checks (expired? price changed?)
  GW->>PE: evaluate → outcome + rule hits
  alt AUTO / NOTIFY
    GW->>VA: place order
    GW-->>Ag: signed order confirmation (Cart Mandate)
  else APPROVE
    GW->>H: one consolidated approval card
    H->>GW: approve / reject / modify per line (name + reason)
    GW->>VA: place approved lines
  else BLOCK
    GW-->>Ag: policy_blocked (rule ids)
  end
  GW->>AU: policy_decision, approval, order_placed (hash-chained)
```

## 5. Policy decision

```mermaid
flowchart TD
  start([checkout lines + mandate + profile + history]) --> v3{Agent suspended?} -->|yes| B[BLOCK V3]
  v3 -->|no| r0{Mandate signed & valid?} -->|no| B0[BLOCK R0]
  r0 -->|yes| r1{Allergen / diet exclusion?} -->|yes| B1[BLOCK R1]
  r1 -->|no| rest[Evaluate R2–R14, V1–V2 per line & basket]
  rest --> agg{Strictest fired rule}
  agg -->|BLOCK| BB[BLOCK]
  agg -->|APPROVE| AP[One approval card]
  agg -->|NOTIFY| NO[Order + notify]
  agg -->|none| AU[AUTO order]
```

## 6. Planner

```mermaid
flowchart LR
  q[free text need] --> n[resolve kind, variants, diet, certs]
  n --> c[candidates: catalog + keyword match]
  c --> f[hard filters: kind, allergens, diet, certs, never-buy, required filters, unit, blocked swaps, stock<br/>each exclusion logged with reason]
  f --> r{strict stock covers qty?}
  r -->|no| rx[relax explicit variant → substitutes, flagged]
  r -->|yes| s
  rx --> s[score = Σ weightᵢ·valueᵢ + bonuses<br/>spec · price · delivery · quality · sustainability · brand · pack fit · learned]
  s --> o[order: your choice > pinned > fallback list > score]
  o --> t[BEST / BETTER / GOOD + trade-off sentence]
  t --> p[plans: split products · single substitute · split dates<br/>whole cases, overage shown]
```

## 7. Trust boundaries & deployment view

- **Boundary 1 (agent → gateway):** mutual TLS / OAuth client credential bound to one buyer account; per-agent rate limit (429 + Retry-After); kill switch (V3).
- **Boundary 2 (human → gateway):** mandates and preference profiles are signed by a named admin; approvals carry user id + display name.
- **Boundary 3 (gateway → Valio Aimo):** read-mostly adapter; only `place_order` writes; no customer data leaves Valio Aimo except what the buyer already owns.

Production deployment sketch: stateless gateway pods behind an API gateway; PostgreSQL (3NF model, partitioned by month), append-only audit table with periodic hash anchoring; OPA sidecar for policy bundles; HSM/KMS-held ES256 keys published via did:web; event stream (L1 raw, 90 days) → refined L2 tables → L3 views.

## 8. Key decisions (short ADRs)

| # | Decision | Alternatives considered | Why |
| --- | --- | --- | --- |
| ADR-1 | Deterministic policy engine decides; LLM only proposes/parses | LLM-as-judge; human-only approval | Explainable, testable, auditable; rule ids map to plain language |
| ADR-2 | Offers as W3C VC 2.0 secured with compact JWS ES256 | Plain signed JSON; mTLS only; blockchain | Open, verifiable offline, works with JWKS/did:web; no platform lock-in |
| ADR-3 | One handler set, two facades (REST + MCP) | MCP only; REST only | Agent vendors differ; one behaviour, one audit |
| ADR-4 | Strictest-rule-wins outcome model | Weighted risk score | Predictable for buyers and Valio Aimo; easy to explain |
| ADR-5 | Hash-chained append-only audit written by the gateway | Agent-side logs; external ledger | Tamper evidence without new infrastructure; anchorable later |
| ADR-6 | Separate outcome store (3NF + views) from audit | Analytics on raw logs | Data minimisation; governed metrics; fast queries |
| ADR-7 | Preference profile separate from mandate, referenced by version | Preferences inside mandate | Mandate = authority (rarely changes); preferences = taste (often changes) |
| ADR-8 | Event Autopilot as a deterministic pipeline over the same planner/policy | Free-form LLM shopping list | Same guardrails; every quantity has a why |
| ADR-9 | MVP logic client-side in one page; Python core as reference | Server-only demo | Demo must run on a phone without localhost |
