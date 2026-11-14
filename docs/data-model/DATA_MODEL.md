# Aimo Agent Gateway — Order Process Data Model

Version 1.1 · 14 Nov 2026 · 3NF base tables + derived analytics views

This model saves **everything an order process produces** — the request, every candidate and why it lost, signed offers, ranked plans with per-criterion scores, the policy decision and fired rules, human approvals and corrections, the order, delivery, usage and waste, feedback, recommendations and the audit chain — so it can be queried for two purposes:

- **@agent** — make the ordering agent more precise (right-sizing, substitution ranking, supplier reliability, price judgement, mandate tuning).
- **@insight** — give buyers and Valio Aimo comprehensive reports (past processes, scorecards, waste, approvals, sustainability).

**Principle: capture as much as possible, store only refined data.** Every signal is captured in a raw event stream; it is promoted into the refined model only once it is typed, unit-normalised, coded, de-duplicated, linked to its process and labelled with a consumer. Nothing is stored "just in case" in the refined layer, and nothing useful is thrown away before it has been refined. Personal data stays minimal (user id and display name for accountability, a 280-character request excerpt, no voice recordings or LLM transcripts).

## Data layers

| Layer | What | Retention |
| --- | --- | --- |
| L1 Raw | Append-only, schema-versioned event stream from agent, gateway, kitchen app, Valio Aimo backend and context feeds | 90 days |
| L2 Refined | This 3NF model: validated, typed, unit-normalised (L, kg, pcs), coded, de-duplicated, linked, labelled | 24 months |
| L3 Insight | Views (`v_*`, `sig_*`), outcome labels and governed metrics | Rebuildable |

```mermaid
---
title: "Data layers · capture everything, keep only refined, labelled data"
---
flowchart LR
    subgraph SRC["Sources"]
        A1["Buyer agent<br/>tool calls"]
        A2["Gateway<br/>offers, policy, orders"]
        A3["Kitchen app<br/>voice, approvals, usage"]
        A4["Valio Aimo backend<br/>stock, delivery"]
        A5["Context feeds<br/>calendar, weather, occupancy"]
    end
    subgraph L1["L1 RAW · event stream, 90 days"]
        R["Append-only events<br/>schema-versioned JSON"]
    end
    subgraph L2["L2 REFINED · 3NF model, 24 months"]
        C1["Validate and type"]
        C2["Normalise units<br/>to L, kg, pcs"]
        C3["Map codes<br/>GTIN, allergens, reasons"]
        C4["De-duplicate and link<br/>process, order, line"]
        T["67 labelled tables<br/>@domain @feeds @grain"]
    end
    subgraph L3["L3 INSIGHT · views, labels, metrics"]
        V["Views v_* and signals sig_*"]
        L["Outcome labels<br/>perfect_order, over_ordered ..."]
        M["Governed metrics<br/>one definition each"]
    end
    subgraph USE["Consumers"]
        U1["Ordering agent<br/>v_agent_features"]
        U2["Buyer insights<br/>scorecard, waste, history"]
        U3["Valio Aimo ops<br/>aggregates only"]
    end
    A1 & A2 & A3 & A4 & A5 --> R
    R --> C1 --> C2 --> C3 --> C4 --> T
    R -. "field with no consumer<br/>expires after 90 days" .-> X["Dropped"]
    T --> V --> L
    V --> M
    L --> U1
    V --> U1
    M --> U2
    L --> U2
    M --> U3
```


## Files

| File | Contents |
| --- | --- |
| `schema.sql` | Complete DDL: 67 base tables, indexes, 10 derived views (validated on SQLite; PostgreSQL notes inline) |
| `catalog_seed.sql` | 12 outcome-label definitions and 14 governed metric definitions |
| `queries.sql` | 10 example queries tagged @agent / @insight |
| `er_1_reference` … `er_5_insight` (.mmd/.svg/.png) | ER model split into five domains
| `data_layers` (.mmd/.svg/.png) | Raw → refined → insight pipeline |
| `class_diagram` (.mmd/.svg/.png) | Domain class model with behaviour |

## Labels on every table

| Label | Values | Meaning |
| --- | --- | --- |
| `@domain` | REF · CFG · TXN · OBS · AUD · DER | Reference/master · buyer configuration (versioned) · order-process transactions · observed outcomes after the order · tamper-evident audit · derived views |
| `@feeds` | AGENT · INSIGHT · TRUST | Which consumer needs the data; a field with no consumer is not stored |
| `@grain` | one row per … | What a row means, so aggregations never double-count |
| `@pii` | none · low | Personal-data exposure |

## Normalisation (3NF) rules applied

1. **1NF** — no lists in columns: allergens, diets, certificates, mandate exclusions, weights, list items, rule hits and dietary guest counts are their own junction tables.
2. **2NF** — composite keys (e.g. `product_allergen`, `plan_score`, `decision_rule_hit`) carry only attributes of the whole key.
3. **3NF** — no transitive dependencies: org comes via `site`, category via `need_group`, product and price via `offer`, process via `plan`. Totals, coverage, base-unit quantities, utilisation and rates are **never stored**; they are computed in `v_*` views.
4. **Snapshots that are not duplicates** — `plan_score.weight` and offer prices are facts *at decision time* (profiles and prices change later), so storing them is correct, not redundant.
5. **Codes are lookup tables** (policy rules, criteria, exclusion/waste/exception reasons, allergens, diets, certificates) so every dimension can be grouped and filtered reliably.
6. **Versioned configuration** — mandates and preference profiles are new rows per change (`supersedes_*`, `version`), so every past decision can be explained with the rules that applied then.

## Table catalogue

| Table | Domain / feeds |
| --- | --- |
| `country` | REF @feeds INSIGHT |
| `unit` | REF @feeds AGENT,INSIGHT |
| `org_type` | REF @feeds INSIGHT |
| `organization` | lookup / junction |
| `site` | REF @feeds AGENT,INSIGHT |
| `role` | REF @feeds TRUST |
| `app_user` | REF @feeds TRUST @pii low |
| `agent` | REF @feeds TRUST,INSIGHT |
| `supplier` | REF @feeds AGENT,INSIGHT |
| `brand` | REF @feeds AGENT,INSIGHT |
| `category` | REF @feeds AGENT,INSIGHT |
| `need_group` | REF @feeds AGENT,INSIGHT |
| `product` | REF @feeds AGENT,INSIGHT |
| `allergen` | REF @feeds AGENT |
| `product_allergen` | REF @feeds AGENT |
| `diet_tag` | REF @feeds AGENT |
| `product_diet` | lookup / junction |
| `certificate` | REF @feeds AGENT,INSIGHT |
| `product_certificate` | lookup / junction |
| `emission_factor` | REF @feeds INSIGHT |
| `dish` | REF @feeds AGENT,INSIGHT |
| `recipe` | CFG @feeds AGENT |
| `recipe_ingredient` | CFG @feeds AGENT |
| `calendar_day` | REF @feeds AGENT,INSIGHT |
| `label_definition` | REF @feeds INSIGHT |
| `metric_definition` | REF @feeds INSIGHT |
| `policy_rule` | lookup / junction |
| `criterion` | lookup / junction |
| `exclusion_reason` | lookup / junction |
| `exception_type` | lookup / junction |
| `waste_reason` | lookup / junction |
| `quality_issue` | lookup / junction |
| `mandate` | CFG @feeds AGENT,TRUST |
| `mandate_allowed_category` | lookup / junction |
| `mandate_excluded_allergen` | lookup / junction |
| `mandate_required_diet` | lookup / junction |
| `preference_profile` | CFG @feeds AGENT |
| `preference_weight` | lookup / junction |
| `preference_filter` | lookup / junction |
| `product_list` | lookup / junction |
| `product_list_item` | lookup / junction |
| `event` | TXN @feeds AGENT,INSIGHT |
| `event_diet_count` | lookup / junction |
| `event_allergy_count` | lookup / junction |
| `event_dish` | lookup / junction |
| `purchase_process` | TXN @feeds AGENT,INSIGHT,TRUST |
| `request_line` | lookup / junction |
| `candidate_exclusion` | lookup / junction |
| `offer` | TXN @feeds AGENT,TRUST,INSIGHT |
| `plan` | lookup / junction |
| `plan_score` | lookup / junction |
| `plan_line` | lookup / junction |
| `policy_decision` | TXN @feeds AGENT,TRUST,INSIGHT |
| `decision_rule_hit` | lookup / junction |
| `approval` | TXN @feeds AGENT,INSIGHT,TRUST |
| `manual_change` | lookup / junction |
| `process_exception` | lookup / junction |
| `purchase_order` | TXN @feeds INSIGHT,TRUST |
| `order_line` | lookup / junction |
| `delivery_line` | OBS @feeds AGENT,INSIGHT |
| `consumption` | OBS @feeds AGENT,INSIGHT |
| `leftover_lot` | OBS @feeds AGENT |
| `line_feedback` | OBS @feeds AGENT,INSIGHT |
| `recommendation` | lookup / junction |
| `site_day_context` | OBS @feeds AGENT,INSIGHT |
| `outcome_label` | lookup / junction |
| `audit_event` | lookup / junction |

## Derived views (fast query layer)

| View | Grain | Powers |
| --- | --- | --- |
| `v_order_line_fact` | ordered line | Base-unit qty, value, price per base unit, substitute flag |
| `v_process_fact` | process | Scorecard: outcome, tier, rank chosen, value, corrections, exceptions |
| `v_usage_fact` | ordered line with usage | Utilisation, waste rate and value |
| `v_request_fulfilment` | request line | Coverage, case-rounding overage, leftovers netted |
| `sig_substitution_acceptance` | org × from → to product | Ranking bonus/penalty with evidence n |
| `sig_per_guest_consumption` | org × event type × style × need | Right-sizing next events |
| `sig_supplier_reliability` | org × supplier | Experienced on-time, fill and quality rates |
| `sig_price_history` | org × product × month | "Is today's price good?" |
| `sig_approval_pattern` | org × rule | Mandate tuning recommendations |
| `v_agent_features` | org × need group | One row of everything the planner reads (use per guest, waste rate, substitute acceptance, over-order count) |

In production these become materialised views refreshed when a process closes; `audit_event` and `offer` are partitioned by month.


## Outcome labels (refined "was this good?" layer)

Labels are materialised by versioned rules when a process, line or event closes (humans can override). They make insight queries one-liners and give the agent a labelled evaluation set.

| Label | Level | Rule (v1) |
| --- | --- | --- |
| perfect_order | event | utilisation ≥ 95% on every line, no shortage |
| right_sized | line | utilisation 90–100%, no shortage |
| over_ordered | line | kept + wasted > 10% of ordered |
| under_ordered | line | shortage or emergency purchase |
| good_substitute / bad_substitute | line | substitute accepted and rated ≥ 4 / rejected or rated ≤ 2 |
| price_good | line | price ≤ buyer's 8-week average |
| late_delivery | line | delivered after need-by |
| autonomous · corrected · top_choice · exception_free | process | AUTO/NOTIFY · error correction made · rank-1 plan ordered · no exceptions |

## Context data (explains demand)

`calendar_day` (weekday, season, Finnish public and school holidays) and `site_day_context` (covers served, occupancy, temperature, rain, local events) let the agent learn that, for example, breakfast milk per guest drops in summer or rises on conference days.

## Governed metrics (semantic layer)

`metric_definition` holds the single definition of each KPI (formula, source view, grain, unit, better-when, audience): autonomous rate, manual-correction rate, top-choice rate, utilisation, waste value and rate, coverage, rounding overage, need-by hit rate, fill rate, approval latency, substitute acceptance, spend, exceptions per process. Dashboards may only use these, so every number means the same thing everywhere.

## ER model

```mermaid
---
title: "ER 1/5 · Reference data (REF) — products, need groups, allergens, labels"
---
erDiagram
    COUNTRY ||--o{ SUPPLIER : "based in"
    COUNTRY ||--o{ PRODUCT : "origin of"
    SUPPLIER ||--o{ BRAND : owns
    SUPPLIER ||--o{ PRODUCT : supplies
    BRAND ||--o{ PRODUCT : brands
    CATEGORY ||--o{ CATEGORY : "parent of"
    CATEGORY ||--o{ NEED_GROUP : contains
    CATEGORY ||--o| EMISSION_FACTOR : "has range"
    NEED_GROUP ||--o{ PRODUCT : "met by"
    UNIT ||--o{ NEED_GROUP : "base unit"
    UNIT ||--o{ PRODUCT : "pack unit"
    PRODUCT ||--o{ PRODUCT_ALLERGEN : declares
    ALLERGEN ||--o{ PRODUCT_ALLERGEN : "declared in"
    PRODUCT ||--o{ PRODUCT_DIET : tagged
    DIET_TAG ||--o{ PRODUCT_DIET : tags
    PRODUCT ||--o{ PRODUCT_CERTIFICATE : carries
    CERTIFICATE ||--o{ PRODUCT_CERTIFICATE : "granted as"
    DISH ||--o{ RECIPE : "made by"
    RECIPE ||--o{ RECIPE_INGREDIENT : lists
    NEED_GROUP ||--o{ RECIPE_INGREDIENT : "used in"

    PRODUCT {
        text product_id PK
        text gtin UK "GS1 key"
        text aimo_sku UK
        text name
        text brand_id FK
        text supplier_id FK
        text need_group_id FK
        text origin_country_code FK
        numeric pack_size
        text pack_unit_code FK
        int units_per_case
        int shelf_life_days
        text quality_grade "A B C"
        numeric net_weight_kg_per_pack
    }
    NEED_GROUP {
        text need_group_id PK
        text category_id FK
        text name UK "lactose-free semi-skimmed milk"
        text base_unit_code FK
        text perishability
    }
    CATEGORY {
        text category_id PK
        text parent_category_id FK
        text name
        int level
    }
    UNIT {
        text unit_code PK
        text dimension "volume mass count"
        text base_unit_code FK
        numeric to_base_factor
    }
    PRODUCT_ALLERGEN {
        text product_id PK,FK
        text allergen_code PK,FK
        text presence "contains may_contain"
    }
    ALLERGEN {
        text allergen_code PK "EU FIC Annex II, 14 codes"
        text label
    }
    PRODUCT_DIET {
        text product_id PK,FK
        text diet_code PK,FK
    }
    DIET_TAG {
        text diet_code PK
        text label
    }
    PRODUCT_CERTIFICATE {
        text product_id PK,FK
        text certificate_code PK,FK
        text valid_until
        text credential_ref "VC id"
    }
    CERTIFICATE {
        text certificate_code PK
        text label
        text issuer
        int is_sustainability
    }
    SUPPLIER {
        text supplier_id PK
        text name
        text country_code FK
    }
    BRAND {
        text brand_id PK
        text name UK
        text owner_supplier_id FK
    }
    COUNTRY {
        text country_code PK
        text name
        int is_domestic
    }
    EMISSION_FACTOR {
        text category_id PK,FK
        numeric kg_co2e_per_kg_low
        numeric kg_co2e_per_kg_high
        text source
    }
    DISH {
        text dish_id PK
        text name UK
        text course
    }
    RECIPE {
        text recipe_id PK
        text dish_id FK
        text owner_org_id FK "null = Aimo default"
        int version
        text diet_variant FK
        numeric portion_g
    }
    RECIPE_INGREDIENT {
        text recipe_id PK,FK
        text need_group_id PK,FK
        numeric qty_per_portion
        numeric yield_factor
    }
```

```mermaid
---
title: "ER 2/5 · Buyer configuration & governance (CFG) — versioned, never edited in place"
---
erDiagram
    ORGANIZATION ||--o{ SITE : runs
    ORGANIZATION ||--o{ APP_USER : employs
    ORGANIZATION ||--o{ AGENT : authorises
    ROLE ||--o{ APP_USER : "assigned to"
    ORGANIZATION ||--o{ MANDATE : signs
    APP_USER ||--o{ MANDATE : issues
    MANDATE ||--o| MANDATE : supersedes
    MANDATE ||--o{ MANDATE_ALLOWED_CATEGORY : allows
    MANDATE ||--o{ MANDATE_EXCLUDED_ALLERGEN : excludes
    MANDATE ||--o{ MANDATE_REQUIRED_DIET : requires
    ORGANIZATION ||--o{ PREFERENCE_PROFILE : owns
    SITE |o--o{ PREFERENCE_PROFILE : "scoped to"
    PREFERENCE_PROFILE ||--o{ PREFERENCE_WEIGHT : weights
    CRITERION ||--o{ PREFERENCE_WEIGHT : "weighted in"
    PREFERENCE_PROFILE ||--o{ PREFERENCE_FILTER : filters
    PREFERENCE_PROFILE ||--o{ PRODUCT_LIST : keeps
    PRODUCT_LIST ||--o{ PRODUCT_LIST_ITEM : contains
    PRODUCT ||--o{ PRODUCT_LIST_ITEM : "listed in"

    ORGANIZATION {
        text org_id PK
        text name
        text org_type_code FK "hotel hospital school"
        text country_code FK
        text aimo_customer_no UK
    }
    SITE {
        text site_id PK
        text org_id FK
        text name
        text site_type
        text city
        text gln UK "GS1 location"
        numeric storage_cold_l
        numeric storage_dry_kg
    }
    APP_USER {
        text user_id PK
        text org_id FK
        text role_code FK
        text display_name "only PII kept"
    }
    ROLE {
        text role_code PK "chef admin approver aimo_ops"
    }
    AGENT {
        text agent_id PK
        text org_id FK
        text vendor
        text protocol "rest mcp a2a"
        text public_key_jwk
        text status "kill switch"
    }
    MANDATE {
        text mandate_id PK
        text org_id FK
        int version
        text issued_by_user_id FK
        text valid_from
        text valid_until
        numeric per_order_limit_eur
        numeric per_month_limit_eur
        numeric per_event_limit_eur
        numeric max_sub_price_delta_pct
        int allow_brand_switch
        int allow_pack_change
        text signature_jws
        text supersedes_mandate_id FK
        text change_source "manual recommendation"
    }
    MANDATE_ALLOWED_CATEGORY {
        text mandate_id PK,FK
        text category_id PK,FK
    }
    MANDATE_EXCLUDED_ALLERGEN {
        text mandate_id PK,FK
        text allergen_code PK,FK
    }
    MANDATE_REQUIRED_DIET {
        text mandate_id PK,FK
        text diet_code PK,FK
    }
    PREFERENCE_PROFILE {
        text profile_id PK
        text org_id FK
        text site_id FK "null = org-wide"
        text category_id FK "null = all"
        int version
        text preset
        text created_by_user_id FK
    }
    PREFERENCE_WEIGHT {
        text profile_id PK,FK
        text criterion_code PK,FK
        numeric weight "sums to 1"
    }
    CRITERION {
        text criterion_code PK "price quality delivery ..."
    }
    PREFERENCE_FILTER {
        text filter_id PK
        text profile_id FK
        text filter_type
        text mode "required preferred excluded"
        text brand_id FK
        text supplier_id FK
        text certificate_code FK
        text country_code FK
        numeric numeric_value
    }
    PRODUCT_LIST {
        text list_id PK
        text profile_id FK
        text name
        text list_kind "favourite never_buy pinned custom"
    }
    PRODUCT_LIST_ITEM {
        text list_id PK,FK
        text product_id PK,FK
        int rank "fallback order"
    }
    PRODUCT {
        text product_id PK
    }
```

```mermaid
---
title: "ER 3/5 · Order process (TXN) — request → offers → plans → decision → order"
---
erDiagram
    SITE ||--o{ EVENT : hosts
    EVENT ||--o{ EVENT_DIET_COUNT : "guests by diet"
    EVENT ||--o{ EVENT_ALLERGY_COUNT : "guests by allergy"
    EVENT ||--o{ EVENT_DISH : serves
    RECIPE ||--o{ EVENT_DISH : "cooked as"
    SITE ||--o{ PURCHASE_PROCESS : requests
    AGENT ||--o{ PURCHASE_PROCESS : runs
    EVENT |o--o{ PURCHASE_PROCESS : "sourced by"
    MANDATE ||--o{ PURCHASE_PROCESS : governs
    PREFERENCE_PROFILE ||--o{ PURCHASE_PROCESS : ranks
    PURCHASE_PROCESS ||--|{ REQUEST_LINE : asks
    EVENT_DISH |o--o{ REQUEST_LINE : "derived from"
    NEED_GROUP ||--o{ REQUEST_LINE : "need for"
    PURCHASE_PROCESS ||--o{ CANDIDATE_EXCLUSION : "why not"
    PURCHASE_PROCESS ||--o{ OFFER : "receives signed"
    PRODUCT ||--o{ OFFER : "offered as"
    PURCHASE_PROCESS ||--|{ PLAN : "ranks alternatives"
    PLAN ||--|{ PLAN_LINE : contains
    PLAN ||--|{ PLAN_SCORE : "explained by"
    REQUEST_LINE ||--o{ PLAN_LINE : "covered by"
    OFFER ||--o{ PLAN_LINE : "priced by"
    PLAN ||--o{ POLICY_DECISION : "evaluated by"
    POLICY_DECISION ||--o{ DECISION_RULE_HIT : "fired"
    POLICY_RULE ||--o{ DECISION_RULE_HIT : "fires as"
    POLICY_DECISION ||--o| APPROVAL : "needs"
    APPROVAL ||--o{ MANUAL_CHANGE : records
    PURCHASE_PROCESS ||--o{ MANUAL_CHANGE : "corrected by"
    PURCHASE_PROCESS ||--o{ PROCESS_EXCEPTION : "hit"
    PLAN ||--o| PURCHASE_ORDER : "becomes"
    PURCHASE_ORDER ||--|{ ORDER_LINE : contains
    OFFER ||--o{ ORDER_LINE : "price-locked by"
    REQUEST_LINE ||--o{ ORDER_LINE : fulfils

    EVENT {
        text event_id PK
        text site_id FK
        text name
        text event_type
        text service_style "plated buffet"
        text starts_at
        int expected_guests
        int actual_guests
    }
    EVENT_DISH {
        text event_dish_id PK
        text event_id FK
        text recipe_id FK
        int planned_portions
        int served_portions
    }
    PURCHASE_PROCESS {
        text process_id PK "= audit traceId"
        text site_id FK
        text agent_id FK
        text event_id FK
        text context_type "event standing ad_hoc"
        text channel "voice text api"
        text language
        text request_excerpt "max 280 chars"
        text mandate_id FK
        text profile_id FK
        text need_by
        text status
        text created_at
        text closed_at
        int tool_call_count
    }
    REQUEST_LINE {
        text request_line_id PK
        text process_id FK
        text need_group_id FK
        text requested_product_id FK
        text event_dish_id FK
        numeric qty_requested
        text unit_code FK
        numeric qty_from_leftovers
        numeric history_adjustment_pct
    }
    CANDIDATE_EXCLUSION {
        text process_id PK,FK
        text product_id PK,FK
        text reason_code PK,FK
    }
    OFFER {
        text offer_id PK
        text process_id FK
        text product_id FK
        numeric unit_price_eur
        int qty_available_packs
        text availability_as_of
        text stock_confidence
        text earliest_delivery
        numeric claimed_on_time_rate
        text valid_until
        text jws_sha256
        text verification
    }
    PLAN {
        text plan_id PK
        text process_id FK
        text strategy "single split partial"
        text tier "BEST BETTER GOOD"
        int rank
        numeric total_score
        text tradeoff_text
    }
    PLAN_SCORE {
        text plan_id PK,FK
        text criterion_code PK,FK
        numeric raw_score
        numeric weight "snapshot"
    }
    PLAN_LINE {
        text plan_line_id PK
        text plan_id FK
        text request_line_id FK
        text offer_id FK
        int qty_cases
        text delivery_date
        text signal_note
    }
    POLICY_DECISION {
        text decision_id PK
        text plan_id FK
        text outcome "AUTO NOTIFY APPROVE BLOCK"
        text evaluated_at
        text policy_version
    }
    DECISION_RULE_HIT {
        text decision_id PK,FK
        text rule_id PK,FK
        text plan_line_id PK,FK
        text reason_text
    }
    APPROVAL {
        text approval_id PK
        text decision_id FK,UK
        text approver_user_id FK
        text requested_at
        text decided_at
        text action
    }
    MANUAL_CHANGE {
        text change_id PK
        text process_id FK
        text approval_id FK
        text plan_line_id FK
        text change_kind "preference_choice error_correction"
        text field
        text old_value
        text new_value
    }
    PROCESS_EXCEPTION {
        text exception_id PK
        text process_id FK
        text exception_code FK
        text offer_id FK
        text resolved_by
    }
    PURCHASE_ORDER {
        text order_id PK
        text plan_id FK,UK
        text aimo_order_ref UK
        text placed_at
        text confirmation_jws_sha256
    }
    ORDER_LINE {
        text order_line_id PK
        text order_id FK
        text request_line_id FK
        text offer_id FK
        int qty_cases
        text delivery_date
    }
```

```mermaid
---
title: "ER 4/5 · Observed outcomes (OBS), learning loop & audit (AUD)"
---
erDiagram
    ORDER_LINE ||--o{ DELIVERY_LINE : "delivered as"
    QUALITY_ISSUE |o--o{ DELIVERY_LINE : "flags"
    ORDER_LINE ||--o| CONSUMPTION : "reconciled by"
    WASTE_REASON |o--o{ CONSUMPTION : explains
    CONSUMPTION |o--o{ LEFTOVER_LOT : "creates"
    SITE ||--o{ LEFTOVER_LOT : stores
    PRODUCT ||--o{ LEFTOVER_LOT : "is"
    PURCHASE_PROCESS |o--o{ LEFTOVER_LOT : "uses up"
    ORDER_LINE ||--o| LINE_FEEDBACK : "rated by"
    ORGANIZATION ||--o{ RECOMMENDATION : receives
    RECOMMENDATION |o--o| MANDATE : "applied as"
    RECOMMENDATION |o--o| PREFERENCE_PROFILE : "applied as"
    PURCHASE_PROCESS ||--o{ AUDIT_EVENT : "evidenced by"

    DELIVERY_LINE {
        text delivery_line_id PK
        text order_line_id FK
        text delivered_at
        int qty_delivered_packs
        text quality_issue_code FK
        text best_before
    }
    CONSUMPTION {
        text consumption_id PK
        text order_line_id FK,UK
        numeric qty_used
        numeric qty_kept
        numeric qty_redistributed
        numeric qty_wasted
        text waste_reason_code FK
        numeric shortage_qty
        int emergency_purchase
        text recorded_by_user_id FK
        text method "one_tap prefilled manual"
    }
    LEFTOVER_LOT {
        text lot_id PK
        text site_id FK
        text product_id FK
        text source_consumption_id FK
        numeric qty_base
        text best_before
        text status
        text used_in_process_id FK
    }
    LINE_FEEDBACK {
        text order_line_id PK,FK
        int rating "1-5"
        int substitute_accepted
        text given_by_user_id FK
    }
    RECOMMENDATION {
        text recommendation_id PK
        text org_id FK
        text kind
        text title
        text evidence_json "n, period, process ids"
        numeric expected_impact_eur
        text status "open applied dismissed"
        text applied_mandate_id FK
        text applied_profile_id FK
    }
    AUDIT_EVENT {
        text audit_event_id PK
        text process_id FK
        int seq
        text ts
        text actor_type
        text actor_ref
        text action
        text payload_json
        text prev_hash
        text hash UK
    }
    ORDER_LINE {
        text order_line_id PK
    }
```

```mermaid
---
title: "ER 5/5 · Insight layer — context, outcome labels and governed metrics"
---
erDiagram
    CALENDAR_DAY ||--o{ SITE_DAY_CONTEXT : "context for"
    SITE ||--o{ SITE_DAY_CONTEXT : "measured at"
    LABEL_DEFINITION ||--o{ OUTCOME_LABEL : defines
    PURCHASE_PROCESS |o--o{ OUTCOME_LABEL : "labelled"
    ORDER_LINE |o--o{ OUTCOME_LABEL : "labelled"
    EVENT |o--o{ OUTCOME_LABEL : "labelled"
    CALENDAR_DAY ||--o{ EVENT : "falls on"

    CALENDAR_DAY {
        text day PK
        int iso_week
        int weekday
        int month
        text season
        int is_public_holiday
        int is_school_holiday
        text holiday_name "Juhannus"
    }
    SITE_DAY_CONTEXT {
        text site_id PK,FK
        text day PK,FK
        int covers_served
        numeric occupancy_rate
        numeric temp_c_max
        numeric precipitation_mm
        int local_event_flag
        text source "pms pos manual weather_api"
    }
    LABEL_DEFINITION {
        text label_code PK "perfect_order over_ordered good_substitute ..."
        text level "process order_line event"
        text definition
        text rule_version
    }
    OUTCOME_LABEL {
        text label_id PK
        text label_code FK
        text process_id FK "exactly one target"
        text order_line_id FK
        text event_id FK
        numeric value
        text source "rule human model"
        text labelled_at
    }
    METRIC_DEFINITION {
        text metric_code PK
        text name
        text formula
        text source_view
        text grain
        text unit
        text better_when
        text audience
    }
    SITE {
        text site_id PK
    }
    PURCHASE_PROCESS {
        text process_id PK
    }
    ORDER_LINE {
        text order_line_id PK
    }
    EVENT {
        text event_id PK
    }
```

## Class diagram

```mermaid
---
title: "Class diagram · Order process domain model (what is saved per order, and the behaviour around it)"
---
classDiagram
    direction LR

    class PurchaseProcess {
        +ProcessId id
        +SiteId site
        +AgentId agent
        +ContextType context
        +Channel channel
        +Date needBy
        +ProcessStatus status
        +Instant createdAt
        +Instant closedAt
        +requestLines() List~RequestLine~
        +chosenPlan() Plan
        +close(status)
        +toProcessFact() ProcessFact
    }
    class Event {
        +EventId id
        +EventType type
        +ServiceStyle style
        +Instant startsAt
        +int expectedGuests
        +int actualGuests
        +Map~Diet,int~ dietCounts
        +Map~Allergen,int~ allergyCounts
        +dishes() List~EventDish~
        +rescale(int guests) Delta
        +report() EventReport
    }
    class EventDish {
        +RecipeId recipe
        +int plannedPortions
        +int servedPortions
    }
    class RequestLine {
        +NeedGroupId need
        +ProductId requestedProduct
        +Quantity qtyRequested
        +Quantity qtyFromLeftovers
        +Percent historyAdjustment
        +coverage() Ratio
        +overage() Quantity
    }
    class OfferAttestation {
        +OfferId id
        +ProductId product
        +Money unitPrice
        +int qtyAvailablePacks
        +Instant availabilityAsOf
        +Confidence stockConfidence
        +Date earliestDelivery
        +Instant validUntil
        +Jws proof
        +verify(Jwks) Verification
        +isFresh(Instant now) bool
    }
    class Plan {
        +PlanLabel label
        +Strategy strategy
        +Tier tier
        +int rank
        +double totalScore
        +String tradeoff
        +lines() List~PlanLine~
        +scores() List~CriterionScore~
        +total() Money
        +whyRanked() Explanation
    }
    class PlanLine {
        +OfferId offer
        +int qtyCases
        +Date deliveryDate
        +String signalNote
        +qtyBase() Quantity
    }
    class CriterionScore {
        +Criterion criterion
        +double rawScore
        +double weight
        +contribution() double
    }
    class PolicyDecision {
        +Outcome outcome
        +String policyVersion
        +Instant evaluatedAt
        +ruleHits() List~RuleHit~
        +strictest() Outcome
    }
    class RuleHit {
        +RuleId rule
        +PlanLineId line
        +String reason
    }
    class Approval {
        +UserId approver
        +Instant requestedAt
        +Instant decidedAt
        +ApprovalAction action
        +latency() Duration
        +approve()
        +reject(reason)
        +modify(List~ManualChange~)
    }
    class ManualChange {
        +ChangeKind kind
        +Field field
        +String oldValue
        +String newValue
    }
    class ProcessException {
        +ExceptionType type
        +OfferId offer
        +Resolution resolvedBy
    }
    class PurchaseOrder {
        +String aimoOrderRef
        +Instant placedAt
        +Hash confirmationHash
        +lines() List~OrderLine~
        +value() Money
    }
    class OrderLine {
        +RequestLineId request
        +OfferId offer
        +int qtyCases
        +Date deliveryDate
        +qtyBase() Quantity
        +isSubstitute() bool
    }
    class DeliveryLine {
        +Instant deliveredAt
        +int qtyDeliveredPacks
        +QualityIssue issue
        +Date bestBefore
        +onTime(Date needBy) bool
        +fillRate() Ratio
    }
    class Consumption {
        +Quantity used
        +Quantity kept
        +Quantity redistributed
        +Quantity wasted
        +WasteReason reason
        +Quantity shortage
        +bool emergencyPurchase
        +Method method
        +utilisation() Ratio
        +wasteValue() Money
        +validate(Quantity ordered)
    }
    class LeftoverLot {
        +SiteId site
        +ProductId product
        +Quantity qty
        +Date bestBefore
        +LotStatus status
        +usableFor(Date needBy) bool
    }
    class LineFeedback {
        +int rating
        +bool substituteAccepted
    }
    class Mandate {
        +int version
        +Money perOrderLimit
        +Money perMonthLimit
        +Money perEventLimit
        +Percent maxSubPriceDelta
        +Set~Allergen~ excludedAllergens
        +Set~Diet~ requiredDiets
        +Jws signature
        +isValid(Instant now) bool
    }
    class PreferenceProfile {
        +int version
        +Scope scope
        +Preset preset
        +Map~Criterion,double~ weights
        +List~PreferenceFilter~ filters
        +List~ProductList~ lists
        +score(Plan) double
    }
    class Recommendation {
        +RecoKind kind
        +String title
        +Evidence evidence
        +Money expectedImpact
        +RecoStatus status
        +apply() Mandate or PreferenceProfile
    }
    class AuditEvent {
        +int seq
        +Actor actor
        +String action
        +Json payload
        +Hash prevHash
        +Hash hash
        +verifyChain(prev) bool
    }
    class LearningSignals {
        <<derived view>>
        +substitutionAcceptance(org, from, to) Ratio
        +perGuestConsumption(org, eventType, need) Quantity
        +supplierReliability(org, supplier) Ratio
        +priceHistory(org, product) Series
        +approvalPattern(org, rule) Stats
    }

    class OutcomeLabel {
        +LabelCode code
        +Target target
        +double value
        +LabelSource source
        +String ruleVersion
    }
    class SiteDayContext {
        +Date day
        +int coversServed
        +Ratio occupancy
        +double tempMax
        +bool localEvent
    }
    class Outcome {
        <<enumeration>>
        AUTO
        NOTIFY
        APPROVE
        BLOCK
    }
    class Tier {
        <<enumeration>>
        BEST
        BETTER
        GOOD
    }

    Event "1" *-- "1..*" EventDish
    Event "0..1" <-- "0..*" PurchaseProcess : sourced for
    PurchaseProcess "1" *-- "1..*" RequestLine
    EventDish "0..1" <.. "0..*" RequestLine : derived from
    PurchaseProcess "1" *-- "0..*" OfferAttestation
    PurchaseProcess "1" *-- "1..*" Plan
    PurchaseProcess "1" *-- "0..*" ProcessException
    PurchaseProcess "1" *-- "0..*" ManualChange
    PurchaseProcess --> Mandate : governed by
    PurchaseProcess --> PreferenceProfile : ranked by
    Plan "1" *-- "1..*" PlanLine
    Plan "1" *-- "1..*" CriterionScore
    PlanLine --> OfferAttestation
    PlanLine --> RequestLine
    Plan "1" -- "1..*" PolicyDecision
    PolicyDecision "1" *-- "0..*" RuleHit
    PolicyDecision --> Outcome
    Plan --> Tier
    PolicyDecision "1" -- "0..1" Approval
    Approval "1" o-- "0..*" ManualChange
    Plan "1" -- "0..1" PurchaseOrder : becomes
    PurchaseOrder "1" *-- "1..*" OrderLine
    OrderLine --> OfferAttestation : price-locked
    OrderLine --> RequestLine : fulfils
    OrderLine "1" *-- "0..*" DeliveryLine
    OrderLine "1" -- "0..1" Consumption
    OrderLine "1" -- "0..1" LineFeedback
    Consumption "1" --> "0..*" LeftoverLot : creates
    LeftoverLot ..> PurchaseProcess : netted into
    PurchaseProcess "1" *-- "1..*" AuditEvent
    LearningSignals ..> Consumption : reads
    LearningSignals ..> DeliveryLine : reads
    LearningSignals ..> LineFeedback : reads
    LearningSignals ..> Approval : reads
    LearningSignals ..> Recommendation : produces
    LearningSignals ..> SiteDayContext : explains demand
    Consumption ..> OutcomeLabel : labelled as
    PurchaseProcess ..> OutcomeLabel : labelled as
    Event ..> OutcomeLabel : labelled as
    OutcomeLabel ..> LearningSignals : trains
    Recommendation ..> Mandate : new version
    Recommendation ..> PreferenceProfile : new version
```

## Example queries

See `queries.sql` (Q1 event waste report · Q2 right-sizing · Q3 leftover netting · Q4 substitution evidence · Q5 supplier reliability · Q6 monthly scorecard · Q7 mandate tuning · Q8 price check · Q9 waste trend · Q10 why-not report).

## Retention

| Data | Retention |
| --- | --- |
| Process, order, outcome tables | 24 months |
| Raw event stream (L1) | 90 days |
| Learning signals (views) | rolling 12-month window |
| `audit_event` | at least 6 months (EU AI Act logging floor as best practice) |
| `app_user.display_name` | while the user is active; pseudonymised after |
