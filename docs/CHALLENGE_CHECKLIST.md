# Challenge checklist

The product being judged is the **agent-facing gateway** and its rules. The chef chat app is one example client of that gateway; the brief says this is "not about replacing the webshop with a chatbot".

Status as of 14 Nov 2026 (v5). Every PASS is proven by a test (`make test`) or a demo command. Every check here holds over all three interfaces:

| Interface | How an agent uses it |
|---|---|
| REST | OpenAPI 3.1 at `/openapi.json` |
| MCP | Streamable HTTP at `/mcp` on the same gateway (Bearer agent token), or `make mcp` (stdio proxy to it); 44 typed tools generated from the playbook input schemas |
| Tool calls | the playbook tools through `POST /v1/sessions/{id}/tools/{tool}` |

**Demo commands used below**

| Name | Command |
|---|---|
| A | `python scripts/agent_demo.py` (the brief's milk request, ends in an order) |
| B | `python scripts/agent_demo.py --over-limit` (3,000 L, ends in an approval) |
| L | `AIMO_LIVE_TESTS=1 pytest tests/gateway/test_live_e2e.py` (the same flow on the real mock API) |
| C | `python scripts/agent_demo.py --suggestions` (the buyer's agent pulls and verifies Valio Aimo's seller suggestions) |
| D | `make bench` with `make run` up (10 agents at once, all scenarios, invariants from the gateway's records → docs/BENCH.md) |

All tests named below live in `tests/gateway/test_challenge.py` unless another file is given. "MCP parity" means `tests/gateway/test_mcp_parity.py`.

## Summary

| Area | PASS | PARTIAL | Not built |
|---|---|---|---|
| Core (1–4) | 4 | – | – |
| Underlying requirements (5–8) | 4 | – | – |
| Optional (9–11) | 3 | – | – |
| Organiser insights (4) | 4 | – | – |
| Robustness (v5, 10) | 10 | – | – |
| Example scenarios (6) | 4 | 2 | – |
| Judging criteria (5) | 5 | – | – |
| Deliverables | 5 | – | – |

---

## Core: the solution must enable these

### 1. Structured product, price and availability lookup: PASS

| Check | Where | Proof |
|---|---|---|
| Search over JSON: name, brand, content, price per sales unit and per kg/L, availability status for a need-by date, earliest delivery, order cutoff, reliability, CO₂, labels, allergens, diet | `POST /v1/products/search` in [`gateway/lookup.py`](../gateway/lookup.py) | `test_1_lookup_is_documented_json_and_needs_a_credential` |
| Price and availability for known product ids | `POST /v1/products/price-availability` | same test |
| Documented in OpenAPI 3.1 | `/openapi.json`, built by [`gateway/discovery.py`](../gateway/discovery.py) | `test_6_openapi_31_and_every_documented_path_is_served` |
| Same lookup over MCP | `lookup_products`, `get_price_availability` | MCP parity: `test_mcp_brief_request_end_to_end` |
| Uses the real mock API through `gateway/adapter.py`, one price call and one availability call per lookup | `AimoApiClient.prices` / `.availability` | `test_1_lookup_goes_through_the_adapter_in_one_batch_per_call`; demo L |
| Results ranked good-better-best | tags `best_price`, `most_reliable`, `lowest_co2` | demo A, "lookup" lines |

### 2. Inquiry to commitment at fixed prices: PASS

| Check | Where | Proof |
|---|---|---|
| Each basket line stands on a signed offer (W3C VC 2.0 as `vc+jwt`, ES256) that expires after 15 min | [`gateway/trust.py`](../gateway/trust.py) `issue_offer`; `GET /v1/offers/{id}`; MCP `get_offer` | `test_2_order_must_cite_the_signed_offers_and_prices_are_not_negotiable` |
| The agent can verify an offer itself (JWKS) or ask the gateway for the six checks | `POST /v1/offers/{id}/verify`; MCP `verify_offer` | same test; `tests/test_core.py::test_tampered_price_fails_binding` |
| `place_order` must cite exactly the offer ids of the checked basket | `place_order {offerIds}`, guard `cite_offers` (422 with `fix`) | same test |
| Wrong or stale offer ids send the agent back to re-quote | guard `offer_mismatch` (409, next `plan_basket`) | same test |
| An expired offer or a changed price means re-quote, never a silent new price | `_lock_prices`, guard `price_locked` | `test_2_changed_price_means_requote_never_a_silent_new_price`; `tests/playbook/test_rails.py::test_price_lock_stops_expired_offers` |
| No negotiation: any price field sent with an order is rejected | guard `fixed_prices` (422) | `test_2_order_must_cite…` |
| Signed order confirmation (`order+jwt`) naming offers, mandate, total and approver | `GET /v1/orders/{id}`; MCP `get_order` | `test_4_brief_request_end_to_end_over_http_under_a_minute`; demo A, "verify" line |

### 3. Permissions and human approval: PASS

| Check | Where | Proof |
|---|---|---|
| Published rules saying what the agent decides alone, what it decides and reports, what needs a named human (spend limit, monthly budget, substitution outside tolerance, delivery after need-by, category outside the mandate, standing-order drift, event cost per guest) and what is never allowed (allergen, no mandate, credit limit, sanity cap, paused agent) | `GET /v1/rules` (`autonomy`, `limitsPerBuyer`), [`gateway/rules.yaml`](../gateway/rules.yaml); MCP `get_rules` | `test_3_rules_are_published_and_cover_the_brief` |
| The gateway decides, not the agent: `check_basket` runs as `system:gateway` and the agent cannot skip it | [`gateway/policy.py`](../gateway/policy.py), engine | `tests/playbook/test_rails.py::test_check_is_gateway_run_and_agent_cannot_skip_it` |
| The approval reaches a named person (Laura Virtanen, Head of Procurement) through an inbox | `request_approval`, then `GET /v1/approvals` with her credential | `test_3_over_limit_reaches_a_named_human_and_the_agent_cannot_approve` |
| The agent cannot approve. An agent credential gets 403, and so does an approver from another customer. MCP has no approve tool. | [`gateway/auth.py`](../gateway/auth.py); `POST /v1/approvals/{id}` | same test; MCP parity: `test_mcp_tool_set_covers_the_journey_and_has_no_approve_tool`; demo B |
| The decision is recorded: who, when, an optional note, a hash-chained audit event, and `approvedBy` in the signed confirmation | `decide_approval`, `GET /v1/audit` | same test; demo B |

### 4. End to end in under a minute: PASS

The request is the brief's own: *"I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability."*

| Check | Where | Proof |
|---|---|---|
| Request, lookup, then order or approval, by a script that calls only the gateway (stdlib HTTP, no UI) | [`scripts/agent_demo.py`](../scripts/agent_demo.py) | demo A ends in an order; demo B ends in an approval, then an order |
| Runs against the mock backend | live run: favourite milk at €1.37/L from the mock API, delivery Mon 16.11., €1,370, decided AUTO, under 1 s | demo L, which checks every offer is `priceSource: valio-aimo-mock-api` |
| Under a minute | asserted | `test_4_brief_request_end_to_end_over_http_under_a_minute` (offline); demo L (live) |

---

## Underlying requirements

### 5. No exposure of backend systems: PASS

| Check | Where | Proof |
|---|---|---|
| Only `gateway/adapter.py` can reach Valio Aimo systems; the API key and backend URL never leave it | adapter | `test_5_agents_never_reach_backend_or_secrets` scans the code and the responses |
| Availability is shown as a status plus "can you cover MY quantity", never the warehouse stock level | `lookup._row` | same test (`canCoverQty <= qty`) |
| Each credential sees one customer account | `auth.same_buyer` | `test_7_agent_is_bound_to_its_customer_account` |
| What is and isn't exposed is written down | [docs/EXPOSURE.md](EXPOSURE.md) | – |

### 6. Open, verifiable standards: PASS

| Standard | Endpoint | Proof |
|---|---|---|
| OpenAPI 3.1 (JSON Schema 2020-12) | `/openapi.json` | `test_6_openapi_31_and_every_documented_path_is_served` checks every schema and that every documented path is served |
| MCP | `python -m gateway.mcp_server` | MCP parity tests |
| UCP-style profile | `/.well-known/ucp` | `test_6_well_known_profile_agent_card_and_jwks` |
| A2A agent card, JWS-signed | `/.well-known/agent-card.json` | same test |
| JWKS | `/.well-known/jwks.json` | same test |
| JWS ES256 offers (VC 2.0) and order confirmations | – | tests 2 and 4 |
| Signed buyer mandate (AP2-style Intent Mandate) | `GET /v1/mandate` | `test_7_agent_is_bound_to_its_customer_account` |

[docs/STANDARDS.md](STANDARDS.md) lists each standard and why it was chosen.

### 7. Trust both ways: PASS

| Direction | How | Proof |
|---|---|---|
| Agent to Valio Aimo | The bearer credential is bound to one buyer and one registered agent. The buyer's signed mandate (named issuer, limits, exclusions) is checked on every session (R0). Valio Aimo operations can pause an agent (V3). | `test_7_agent_is_bound…`; `test_7_valio_aimo_operations_can_pause_an_agent`; `tests/playbook/test_rails.py::test_unknown_agent_cannot_start`; `tests/test_core.py::test_mandate_signature_required` |
| Valio Aimo to agent | Offers, confirmations and the agent card are signed with the published JWKS. The six offer checks are signature, validity window, stock freshness, field binding, revocation status and live re-check. Each offer states `priceSource`. | tests 2 and 6; `tests/test_core.py::test_tampered_signature_fails`; demo A verifies the confirmation client-side |

### 8. Agent playbook served and enforced: PASS

| Check | Where | Proof |
|---|---|---|
| Understand, Recall, Discover, Plan, Check, Present, Act, Learn (steps 0–8) is served | `GET /v1/playbook`; MCP `get_playbook`; `GET /v1/tools` | `test_8_playbook_served_and_out_of_order_rejected_over_http` |
| Out-of-order calls get 409 `step_not_allowed` with `next_allowed_tools` | [`gateway/playbook/engine.py`](../gateway/playbook/engine.py) | same test; `tests/playbook/test_rails.py` |
| Discover stays locked while recall has no gaps | engine | `tests/playbook/test_rails.py::test_discover_locked_when_recall_has_no_gaps` |
| Every output is checked against a schema and audited with the playbook version | engine | `tests/playbook/test_rails.py::test_every_step_is_audited_with_playbook_version` |
| Any agent can follow it: demo A is a 100-line client that only obeys `next_allowed_tools` | `scripts/agent_demo.py` | demos A and B; MCP parity |

---

## Optional

| # | Item | Status | Where | Proof |
|---|---|---|---|---|
| 9 | Delivery reliability, certificates and sustainability labels in comparisons | **PASS** | Lookup returns `deliveryReliability` and `co2eKgPerKg` (organiser CSVs), plus `labels` from the pack: Hyvää Suomesta, Avainlippu, Sydänmerkki, EU organic, MSC, Fairtrade and others. Offers carry `certificates` and `delivery.onTimeRate`. The planner weighs reliability. | `test_1_lookup_is_documented_json…`; demo A shows reliability |
| 10 | Substitutions and partial availability, each with a stated reason | **PASS** | Recall uses a past `good_substitute` for the rest (s1 offline: 640 L favourite plus 360 L stand-in). Substitution rules R4 (tell) and R5 (needs OK). Allergen-safe alternative (s4). Lookup status `partial` with `canCoverQty`. | `tests/playbook/test_golden.py` s1 and s4; `tests/test_core.py::test_hospital_allergen_safe_substitution`; `test_1_lookup_goes_through_the_adapter…` |
| 11 | Human-readable log of what the agent did and why, for the buyer and for Valio Aimo | **PASS** | Buyer: `GET /v1/sessions/{id}/log` (plain timeline plus one sentence per call). Valio Aimo: `GET /v1/audit` with the ops credential (every buyer, hash chain verified). | `test_11_plain_log_for_the_buyer`; `test_7_valio_aimo_operations…`; `tests/test_core.py::test_audit_chain_and_tamper` |

## Organiser insights

| Insight | Status | Answer in the gateway |
|---|---|---|
| Trust protocol: the minimum data an agent needs to trust stock, price and origin claims | **PASS** | Signed offer with price, validity, availability as of a timestamp, origin and certificates, plus six checks the agent can run itself (tests 2 and 7) |
| Guardrails model | **PASS** | `/v1/rules` autonomy matrix with four outcomes, strictest wins; limits per buyer in the signed mandate (test 3) |
| Response logic for partial availability and good-better-best substitution | **PASS** | Ranking tags in lookup, recall fallbacks and substitution tolerance rules (items 9–10) |
| Audit trail for buyer and Valio Aimo | **PASS** | Item 11; tamper-evident chain |

## Robustness (v5: many agents at once, in production conditions)

| # | Item | Status | Where | Proof |
|---|---|---|---|---|
| R1 | No overselling: stock re-checked and reserved when the order is placed | **PASS** | `_lock_prices` + `FixtureBackend.reserve` under `gw.lock`; 409 `stock_changed` → re-quote; restock and re-registered live stock deplete | `tests/gateway/test_hardening.py::test_concurrent_orders_never_oversell`, `…restock…`, `…re_registering…`; demo D |
| R2 | No double orders: `Idempotency-Key` (header or `idempotencyKey`) | **PASS** | `Engine.idempotent`: same key + body → stored response, `Idempotent-Replay: true`; other body → 422 | `test_retried_place_order_returns_same_order`, `test_same_key_different_body_is_422`, `test_approval_decision_is_idempotent` |
| R3 | Typed tools: a JSON Schema per tool, 422 `bad_input` with `fix.expected` + `fix.example` | **PASS** | playbooks 1.1.0 `inputs:`; MCP tools generated from them | `test_every_tool_has_an_input_schema`, `test_bad_input_has_a_fix_with_an_example`, `test_mcp_order_tools_are_typed` |
| R4 | Push, not polling: session events and long-poll | **PASS** | `GET /v1/sessions/{id}/events?after=&wait=`, MCP `wait_for_update` | `test_agent_is_woken_by_approval`, `tests/gateway/test_mcp_http.py` |
| R5 | State survives a restart; old confirmations still verify | **PASS** | `gateway/persist.py`, keys in `data/keys` | `test_restart_keeps_pending_approval_and_keys` |
| R6 | Rate limits per credential (429 + `Retry-After`) | **PASS** | `gateway/ratelimit.py` | `test_burst_over_limit_is_429_with_retry_after` |
| R7 | One gateway for REST and MCP; locked-down chef-app routes; demo tokens only in demo mode | **PASS** | `/mcp` (Streamable HTTP), `gateway/auth.py`, `gateway/authz.py` | `tests/gateway/test_mcp_http.py`, `tests/gateway/test_lockdown.py` |
| R8 | Clock ticks, kill switch on every call, atomic steps, per-session lock | **PASS** | `core.py`, `playbook/engine.py` | `test_server_clock_ticks_so_offers_expire`, `test_paused_agent_is_blocked_mid_session`, `test_failed_step_leaves_the_session_unchanged` |
| R9 | Resilient mock-API adapter: retry with jitter, circuit breaker, deadline, work off the event loop | **PASS** | `gateway/adapter.py`, `off_loop` in `__main__.py` | `tests/gateway/test_adapter_resilience.py` |
| R10 | Observability: rejected calls audited, JSON logs with `traceparent`, ops metrics; multi-agent benchmark | **PASS** | `gateway/observability.py`, `/v1/ops/metrics`, `scripts/agent_bench.py` | `tests/gateway/test_observability.py`, `tests/gateway/test_bench.py`; demo D (live: 100 % completion, every invariant holds) |

## Example scenarios

| Scenario | Status | Where |
|---|---|---|
| Need → recipe → order | **PARTIAL** | The chef names the dishes; the gateway turns them into ingredients and quantities (`recipes.json`, learned use per guest), uses leftovers first, then orders (golden s2). Suggesting recipes around a seasonal ingredient is not built. |
| Last-minute event | **PARTIAL** | R7 flags anything that arrives after the need-by date, and the menu logic warns about dishes it can't source. A "tomorrow" booking is not one of the golden scenarios. |
| Supplier stock-out | **PASS** (reactive) | s1 covers the gap with the past good substitute and explains it; R4/R5 apply. There is no background monitor that warns before the kitchen notices. |
| Proactive selling agent (Valio Aimo's own agent) | **PASS** | `gateway/seller.py`: at most 3 signed (`suggestion+jwt`), clearly promotional suggestions per buyer: seasonal, new but similar, better on the buyer's own criteria (CO2e, Hyvää Suomesta, delivery reliability), priced through the adapter. Never outside the signed mandate, never added to a basket: `plan_basket {acceptSuggestion}` re-plans and must pass `check_basket` (first-time product → R8). REST `GET /v1/suggestions`, `POST /v1/suggestions/{id}/feedback`; MCP `get_suggestions`, `suggestion_feedback`; A2A skill `proactive-offers`; event `suggestion.created`; audited as `agent:valio-aimo-seller`. Proof: `tests/gateway/test_seller.py`; demo C. |
| Allergen-safe substitution under pressure | **PASS** | s4 (school): "Can't do this" with a safe alternative; R1 blocks; `tests/test_core.py::test_hospital_allergen_safe_substitution` |
| Standing-order drift detection | **PASS** | R10 pauses auto-renew when quantity drifts more than 20 % from the 8-week median (`tests/test_core.py::test_policy_rules`, case `drift`) |

## Judging criteria

| Criterion (weight) | Evidence |
|---|---|
| Working end-to-end demo (30 %) | Demos A, B and L; `test_4`; the chef app as one client |
| Solving the problem and user need (20 %) | Recall first (favourites, past good orders), the brief's sentence parsed, one question at most, golden scenarios |
| Autonomy and controls (20 %) | Items 3, 7 and 8, `/v1/rules`, kill switch, hash-chained audit |
| Robustness to exceptions (15 %) | Partial cover, substitutes, allergen block, late delivery, expired or changed price or stock means re-quote, wrong offer ids, out-of-order calls, retries, restarts, rate limits, a failing mock API; the Robustness section and `make bench` |
| Openness and path to production (15 %) | OpenAPI 3.1, MCP, `.well-known` documents, JWS/VC, docs/STANDARDS.md, docs/EXPOSURE.md, docs/ASSUMPTIONS.md, docs/ROADMAP.md |

## Deliverables

| Deliverable | Status |
|---|---|
| This checklist | PASS |
| 3-minute demo script in the README, leading with an external agent | PASS ([README](../README.md#3-minute-demo)) |
| docs/STANDARDS.md and docs/EXPOSURE.md | PASS |
| Decisions in docs/ASSUMPTIONS.md, PROGRESS.md current | PASS |
| `.env` holds the endpoint and key, git-ignored, never committed | PASS (`.gitignore`; key scan before every push) |
