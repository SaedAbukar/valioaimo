# Data model

The authoritative model lives in **[docs/data-model/](data-model/)** (v1.1):

- `DATA_MODEL.md` — full guide: three data layers (L1 raw stream 90 days → L2 refined 3NF → L3 insight), labels (`@domain`, `@feeds`, `@grain`, `@pii`), normalisation rules, retention and privacy, anti-bloat rule (a raw field is promoted only with a typed home and a named consumer).
- `schema.sql` — 67 base tables + 10 derived views (`v_*`, `sig_*`, `v_agent_features`), validated on SQLite, PostgreSQL notes inline.
- `catalog_seed.sql` — outcome `label_definition` (12) and governed `metric_definition` (14).
- `queries.sql` — tagged example queries (@agent / @insight).
- ER diagrams `er_1_reference` … `er_5_insight`, `data_layers`, `class_diagram` (.mmd / .svg / .png).

## How the MVP maps to the model

| MVP object (ui/src) | Model entities |
| --- | --- |
| ProcessRecord (`closeProcess`, seeded history) | `purchase_process`, `request_line`, `plan`, `plan_line`, `policy_decision`, `decision_rule_hit`, `approval`, `manual_change`, `process_exception`, `purchase_order`, `order_line`, `delivery_line`, `line_feedback` |
| Ranked candidates & “why ranked” | `offer`, `plan_score`, `criterion`, `preference_weight`, `candidate_exclusion`, `exclusion_reason` |
| Mandate / preference profile versions | `mandate` (+ allowed category, excluded allergen, required diet), `preference_profile`, `preference_weight`, `preference_filter`, `product_list` |
| Event Autopilot | `event`, `event_diet_count`, `event_allergy_count`, `event_dish`, `dish`, `recipe`, `recipe_ingredient` |
| Reconciliation & leftovers | `consumption`, `leftover_lot`, `waste_reason`, `emission_factor`, `v_usage_fact` |
| Outcome label chips | `outcome_label`, `label_definition` |
| Scorecard tiles | `metric_definition` → `v_process_fact`, `v_usage_fact`, `v_request_fulfilment`, `sig_*` |
| Day context in recommendations | `calendar_day`, `site_day_context`, `v_agent_features` |
| Learning signals | `sig_substitution_acceptance`, `sig_per_guest_consumption`, `sig_supplier_reliability`, `sig_price_history`, `sig_approval_pattern` |
| Recommendations | `recommendation` |
| Audit timeline | `audit_event` |

In the page, every “Data behind this” link opens *How it works → Data model* with the powering tables highlighted; tap an entity for its columns, keys and labels.

## Why each kept field matters
See the per-table “why kept / consumer” columns in `data-model/DATA_MODEL.md`. Personal data is limited to user id + display name (accountability) and a 280-character request excerpt; no voice recordings or LLM transcripts. Retention: raw stream 90 days, process records 24 months, signals rolling 12 months, audit ≥ 6 months; buyers can export (JSON/CSV) and delete their data.
