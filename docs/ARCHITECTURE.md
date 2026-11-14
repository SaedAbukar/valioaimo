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

## 9. v2: the playbook rails and the chat-first app

Since v2 every agent works through a **versioned playbook** enforced by the gateway.

```mermaid
flowchart LR
  chef([Chef: chat / voice]) --> app[Chat-first app<br/>ui/dist/index.html]
  app -->|POST /v1/chat| asst[Built-in chef assistant<br/>playbook/agent.py]
  ext[Any external agent<br/>Claude · GPT · Gemini · script] -->|REST /v1/sessions/*/tools/*<br/>or MCP| eng
  asst --> eng[[Playbook state machine<br/>playbook/engine.py<br/>order_playbook.v1.yaml]]
  eng --> s1[1 Understand<br/>understand.py]
  eng --> s2[2 Recall<br/>recall.py + history.json]
  eng --> s3[3 Discover<br/>discover.py]
  eng --> s4[4 Plan<br/>planner.py + menu.py]
  eng --> s5[5 Check<br/>trust.py + policy.py + rules.yaml]
  eng --> s6[6 Present<br/>cards.py + lint]
  eng --> s7[7 Act / 8 Learn<br/>tools.py]
  eng --> L[(audit_event<br/>hash chain + playbook version)]
  s3 --> idx[(Valio Aimo product index<br/>17,546 products)]
  s3 --> api[Mock API<br/>/api/price · /api/availability]
```

- **One state machine, three facades.** The chat assistant, REST and MCP all call
  `Engine.call(session, tool, args)`. Order is enforced there: out-of-order → 409
  `step_not_allowed` with `next_allowed_tools`; wrong output shape → 422.
- **Check is gateway-run.** `check_basket` is audited as `system:gateway`; Act only
  accepts what Check decided (auto / tell me directly, needs OK after an approval).
- **Rewinds.** Chef changes go back to the right step (new guest count → Understand;
  pick, tip or safe alternative → Plan) and everything downstream runs again.
- **Two assortments, one shape.** Seeded customers use the curated demo assortment
  (repeatable golden tests). Kitchens on the live assortment, and needs the curated
  set lacks, use the real Valio Aimo product data, bridged into the planner's product
  shape (`discover.bridge`) with live price and availability when the API key is set.
- **Replayable.** Each call is an `audit_event` with step, playbook version, inputs
  and duration; the golden scenarios in `tests/playbook/` replay whole runs.
- **Data model.** Sessions map to `purchase_process` (`process_id` = session id,
  `tool_call_count`), outcome labels to `outcome_label`, audit to `audit_event`.
  Storage in the MVP is in-memory + SQLite for the audit chain.

| ADR | Decision | Why |
|---|---|---|
| ADR-10 | Versioned playbook file + server-side state machine | Any agent vendor can follow it; refinements are diffs to one file guarded by golden tests |
| ADR-11 | Recall before Discover; Discover locked without gaps | Least manual correction: start from what the kitchen already trusts; fewer API calls |
| ADR-12 | Answers as linted cards | Plain language is enforced, not hoped for |
| ADR-13 | Learn silently only from right-sized runs; ask (Tip) after repeated over-ordering | Chefs stay in control of changes they did not ask for |
| ADR-14 | Recorded gateway runs for the offline page | The artifact shows real gateway output without a server |

## 10. v4: the agent-facing surface (challenge audit)

```mermaid
flowchart LR
  ext[External agent<br/>script · Claude · any MCP client] -->|Bearer agent token| api
  human([Named approver]) -->|Bearer human token| api
  ops([Valio Aimo operations]) -->|Bearer ops token| api
  subgraph Gateway
    api[REST /v1 + MCP<br/>auth.py binds caller to one buyer] --> look[lookup.py<br/>search · price-availability]
    api --> eng[Playbook engine<br/>409 out of order]
    eng --> pol[policy.py + rules.yaml<br/>gateway decides]
    eng --> trust[trust.py<br/>signed offers · confirmations]
    eng --> audit[(Hash-chained audit)]
    disc[/.well-known: ucp · agent card · jwks<br/>/openapi.json/]
  end
  look --> ad[adapter.py<br/>only module that talks to Valio Aimo]
  eng --> ad
  ad -->|X-API-Key, never exposed| mock[(Valio Aimo mock API<br/>/api/price · /api/availability)]
```

Commitment path (v4): `plan_basket` issues signed offers (15 min) → `check_basket` (gateway) → `place_order {offerIds}` or `request_approval` → named human's inbox → `POST /v1/approvals/{id}` (human only) → `place_order {offerIds}` → signed `order+jwt` confirmation. Checklist: [CHALLENGE_CHECKLIST.md](CHALLENGE_CHECKLIST.md); exposure: [EXPOSURE.md](EXPOSURE.md).

## 11. v5: many agents at once, the seller agent and the operations view

```mermaid
flowchart LR
  ext[External agents<br/>REST · MCP /mcp · chat] -->|Bearer token| edge
  subgraph Gateway[One gateway process]
    edge[RequestLog · rate limit · auth/authz<br/>traceparent, JSON logs] --> eng[Playbook engine<br/>input schemas · idempotency · per-session lock<br/>atomic steps · kill switch · rejections audited]
    eng --> res[reserve stock under gw.lock<br/>409 stock_changed]
    eng --> ev[events.py<br/>long-poll per session]
    eng --> per[(persist.py<br/>SQLite: sessions, orders, inbox, stock, events, keys)]
    seller[seller.py<br/>Valio Aimo seller agent] -->|suggestion+jwt| ev
    ds[analytics/datasets.py<br/>agent_activity · demand] --> ops[ops.py<br/>metrics · forward demand · lost sales, k ≥ 3]
    eng --> ds
  end
  eng --> ad[adapter.py<br/>retry · circuit breaker · deadline]
  ad --> mock[(Valio Aimo mock API)]
  bench[scripts/agent_bench.py<br/>N agents, invariants] -->|REST| edge
```

- **Order time is the moment of truth.** `place_order` re-verifies every offer with the planned quantity and reserves the stock atomically; a loser gets `409 stock_changed` and re-quotes. Retries with an `Idempotency-Key` return the first order.
- **Agents are told, not polled.** Every step, decision, approval, order, expiring offer and seller suggestion is a session event; `GET /v1/sessions/{id}/events?wait=25` or MCP `wait_for_update` wakes the agent.
- **The seller is another agent with less power.** It writes signed, promotional suggestions into the buyer's event stream; only the buyer's agent can use one, and only through `plan_basket` → `check_basket`.
- **Valio Aimo learns from the channel.** Sessions and plans become the `agent_activity` and `demand` datasets: buyers query their own rows through the insight rails; operations see cross-customer aggregates with k ≥ 3.
- **Proof.** `make bench` runs N agents at once over REST and checks no oversell, one order per key, verified offers, authority, named approvers and the audit chain from the gateway's own records ([BENCH.md](BENCH.md)).
