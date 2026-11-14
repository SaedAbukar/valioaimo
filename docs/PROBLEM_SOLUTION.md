# Problem → solution map

| # | Challenge question / insight problem | How we solve it | Where in the MVP | Judging criterion |
| --- | --- | --- | --- | --- |
| 1 | Structured product, price and availability lookup | GS1 GTIN-14 catalog with need groups (L0, browse-only); signed Offer Attestations with `availability{qtyAvailable, byDate, asOf, confidence, schedule}`, delivery and certificates | Autopilot → order → Products | End-to-end demo |
| 2 | Inquiry → commitment at **fixed prices**, no negotiation | Offers are commitments for 15 min; checkout re-verifies and refuses (`offer_expired`, `price_changed`) rather than charging differently; signed order confirmation | Demo X1; order detail | Robustness, openness |
| 3 | Permission & human-approval management | Signed Intent Mandate by a named admin; policy engine R0–R14 + V1–V3, strictest wins; one consolidated approval card; overrides logged with name and reason | Settings › Mandate; Orders (approvals first); S3 | Autonomy & controls |
| 4 | Trust protocol | Six checks: signature, validity, freshness, binding, status, live re-verify; trust levels L0–L3; reverse trust via credential + mandate | Products → Signed offer; Settings › How it works › Trust | Openness |
| 5 | Guardrails model | rules.yaml with templated reasons; buyer-side and Valio Aimo-side rules; kill switch, credit, sanity cap, rate limit | Rules sheet; Settings › Agents, Valio Aimo view | Autonomy & controls |
| 6 | Partial availability & good-better-best | Relaxation only when needed; BEST/BETTER/GOOD with trade-off sentence; up to 3 plans; case rounding explicit | S2 | Matching need; robustness |
| 7 | Human-readable audit trail for buyer **and** Valio Aimo | Gateway-written hash chain; sentences + rule ids; two views; tamper test | Order detail › Audit trail; Settings › Audit log; T | Openness |
| 8 | Need → recipe → order | **Event Autopilot**: text/voice → brief → recipe KB → scaled, diet-split, right-sized → leftovers netted → sourced → scheduled → one decision | Autopilot (S0) | End-to-end; least correction |
| 9 | Last-minute event | Multi-line parse, delivery tomorrow, one approval for the whole basket | S3, S0+ | Controls |
| 10 | Supplier stock-out | Signed stock by date; substitutes ranked with learned acceptance; date-split alternative | S2, S4 | Robustness |
| 11 | Allergen-safe substitution (school/hospital) | Mandate hard exclusions + guest allergy constraints as hard filters; R1 BLOCK on forced unsafe lines; safety panel | S4; Autopilot › Allergen check | Robustness |
| 12 | Standing-order drift | R10 vs 8-week median; V2 sanity cap; recommendation to update standing quantity with context | S5; Insights › Recommendations (school) | Controls; least correction |
| 13 | Proactive selling agent | Ops: stock-outs causing substitutions & pack sizes driving waste as replenishment/assortment signals; recommendations (order by Thursday cut-off) | Settings › Valio Aimo view; Insights | Production path |
| 14 | Choice between equivalent products, buyer customisation | Preference profile (weights, presets, hard/soft filters, favourites, never-buy, pinned defaults, fallback lists, per-category overrides); live re-ranking; compare; manual choice recorded as preference | Settings › Preferences; Products › Compare; S7 | Matching need |
| 15 | Learning from past orders | Curated ProcessRecords, outcome labels, governed metrics, signals with evidence, one-tap recommendations creating new signed versions | Insights; S6 | Least manual correction |
| 16 | Waste & right-sizing | Reconciliation (used / kept / redistributed / wasted / shortage), CO₂e estimate, per-guest learning, leftover lots netted next time | Autopilot › After the event; Insights › See all metrics; S8 | Least correction; sustainability |
| 17 | Openness, not one platform's black box | OpenAPI 3.1 + MCP over one handler set; VC 2.0/JWS; AP2 mandates; A2A card; GS1; EU FIC; deterministic rules; documented 3NF data model | Settings › How it works; docs/ | Openness & production path |
