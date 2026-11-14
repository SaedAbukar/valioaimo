-- =====================================================================
-- Aimo Agent Gateway — Order Process Data Model (3NF)
-- Version 1.1 · 2026-11-14 (adds capture layers, context, outcome labels, metric catalogue)
--
-- Purpose: everything saved during and after each order process, stored so
-- it can (a) make the ordering agent more precise and (b) give buyers and
-- Valio Aimo comprehensive, queryable insights.
--
-- Data layers (capture as much as possible, keep the store refined):
--   L1 RAW      append-only event stream from the gateway, agent and kitchen apps
--               (object store / Kafka topic, 90-day retention, NOT in this schema).
--   L2 REFINED  this 3NF model: typed, de-duplicated, unit-normalised, coded, labelled.
--   L3 INSIGHT  views (v_*, sig_*), outcome labels and governed metrics.
-- A raw field is promoted to L2 only when it has a typed home and a consumer
-- (@feeds); everything else expires with L1. That is the anti-bloat rule.
--
-- Normal form: base tables are in 3NF (no repeating groups, every non-key
-- column depends on the whole key and only the key). Anything computable
-- (totals, coverage, base-unit quantities, rates) is NOT stored in base
-- tables; it lives in the derived views at the end (prefix v_ / sig_).
--
-- Labels used on every table (in the header comment):
--   @domain   REF  reference / master data (slowly changing)
--             CFG  buyer configuration & governance (versioned)
--             TXN  order-process transactions (append-mostly)
--             OBS  observed outcomes after the order (delivery, usage, feedback)
--             AUD  tamper-evident audit evidence
--             DER  derived / analytics (views, rebuildable)
--   @feeds    AGENT    used by the planner/ranking/policy to decide better
--             INSIGHT  used for buyer / Valio Aimo dashboards and reports
--             TRUST    used for verification and accountability
--   @grain    one row per ...
--   @pii      none | low (user display name only)
--
-- Naming: snake_case, singular table names, <table>_id surrogate keys,
-- natural keys enforced with UNIQUE, codes as lookup tables (no free text
-- enums) so every dimension can be grouped and filtered.
-- Portable SQL: runs on SQLite for the MVP; PostgreSQL notes in comments
-- (partitioning, JSONB, BRIN indexes) for production.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- =====================================================================
-- 1. REFERENCE DATA  (@domain REF)
-- =====================================================================

-- @domain REF @feeds INSIGHT @grain one row per country
CREATE TABLE country (
  country_code   TEXT PRIMARY KEY CHECK (length(country_code) = 2),  -- ISO 3166-1 alpha-2
  name           TEXT NOT NULL,
  is_domestic    INTEGER NOT NULL DEFAULT 0 CHECK (is_domestic IN (0,1))  -- FI = 1, drives "domestic" preference
);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per unit of measure
CREATE TABLE unit (
  unit_code      TEXT PRIMARY KEY,                 -- 'L','ml','kg','g','pcs'
  dimension      TEXT NOT NULL CHECK (dimension IN ('volume','mass','count')),
  base_unit_code TEXT NOT NULL REFERENCES unit(unit_code),  -- 'L','kg','pcs'
  to_base_factor NUMERIC NOT NULL CHECK (to_base_factor > 0)
);

-- @domain REF @feeds INSIGHT @grain one row per organisation (buyer or Valio Aimo)
CREATE TABLE org_type (
  org_type_code  TEXT PRIMARY KEY,                 -- 'hotel','hospital','school','restaurant','catering','wholesaler'
  label          TEXT NOT NULL
);

CREATE TABLE organization (
  org_id         TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  org_type_code  TEXT NOT NULL REFERENCES org_type(org_type_code),
  country_code   TEXT NOT NULL REFERENCES country(country_code),
  aimo_customer_no TEXT UNIQUE,                    -- account at Valio Aimo
  created_at     TEXT NOT NULL
);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per kitchen / delivery site
CREATE TABLE site (
  site_id        TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES organization(org_id),
  name           TEXT NOT NULL,
  site_type      TEXT NOT NULL CHECK (site_type IN ('kitchen','central_kitchen','outlet','ward','school_kitchen')),
  city           TEXT NOT NULL,
  gln            TEXT UNIQUE,                      -- GS1 Global Location Number (delivery point)
  timezone       TEXT NOT NULL DEFAULT 'Europe/Helsinki',
  storage_cold_l NUMERIC,                          -- cold storage capacity; caps leftovers & orders
  storage_dry_kg NUMERIC
);
CREATE INDEX ix_site_org ON site(org_id);

-- @domain REF @feeds TRUST @grain one row per role
CREATE TABLE role (
  role_code      TEXT PRIMARY KEY,                 -- 'chef','procurement_admin','approver','aimo_ops'
  label          TEXT NOT NULL
);

-- @domain REF @feeds TRUST @pii low @grain one row per human user
CREATE TABLE app_user (
  user_id        TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES organization(org_id),
  role_code      TEXT NOT NULL REFERENCES role(role_code),
  display_name   TEXT NOT NULL,                    -- only personal datum kept: accountability
  active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE INDEX ix_user_org ON app_user(org_id);

-- @domain REF @feeds TRUST,INSIGHT @grain one row per software purchasing agent
CREATE TABLE agent (
  agent_id       TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES organization(org_id),
  name           TEXT NOT NULL,
  vendor         TEXT,                             -- which platform built it (interop insight)
  protocol       TEXT NOT NULL CHECK (protocol IN ('rest','mcp','a2a')),
  public_key_jwk TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('active','suspended','revoked'))  -- kill switch
);
CREATE INDEX ix_agent_org ON agent(org_id);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per supplier to Valio Aimo
CREATE TABLE supplier (
  supplier_id    TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  country_code   TEXT NOT NULL REFERENCES country(country_code)
);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per brand
CREATE TABLE brand (
  brand_id       TEXT PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  owner_supplier_id TEXT REFERENCES supplier(supplier_id)
);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per category node (tree)
CREATE TABLE category (
  category_id    TEXT PRIMARY KEY,
  parent_category_id TEXT REFERENCES category(category_id),
  name           TEXT NOT NULL,
  level          INTEGER NOT NULL CHECK (level BETWEEN 1 AND 4)  -- 1 = dairy, 2 = milk, 3 = lactose-free milk ...
);
CREATE INDEX ix_category_parent ON category(parent_category_id);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per need group (products that meet the same need)
CREATE TABLE need_group (
  need_group_id  TEXT PRIMARY KEY,
  category_id    TEXT NOT NULL REFERENCES category(category_id),
  name           TEXT NOT NULL UNIQUE,             -- 'lactose-free semi-skimmed milk'
  base_unit_code TEXT NOT NULL REFERENCES unit(unit_code),
  perishability  TEXT NOT NULL CHECK (perishability IN ('fresh','chilled','frozen','ambient'))
);
CREATE INDEX ix_need_group_category ON need_group(category_id);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per GTIN (sellable product)
CREATE TABLE product (
  product_id     TEXT PRIMARY KEY,
  gtin           TEXT NOT NULL UNIQUE CHECK (length(gtin) IN (8,12,13,14)),  -- GS1 key
  aimo_sku       TEXT NOT NULL UNIQUE,
  name           TEXT NOT NULL,
  brand_id       TEXT NOT NULL REFERENCES brand(brand_id),
  supplier_id    TEXT NOT NULL REFERENCES supplier(supplier_id),
  need_group_id  TEXT NOT NULL REFERENCES need_group(need_group_id),  -- category via need_group (3NF)
  origin_country_code TEXT NOT NULL REFERENCES country(country_code),
  pack_size      NUMERIC NOT NULL CHECK (pack_size > 0),     -- in pack_unit
  pack_unit_code TEXT NOT NULL REFERENCES unit(unit_code),
  units_per_case INTEGER NOT NULL CHECK (units_per_case > 0),
  shelf_life_days INTEGER,
  quality_grade  TEXT CHECK (quality_grade IN ('A','B','C')),
  net_weight_kg_per_pack NUMERIC,                  -- converts volume waste to kg and CO2e
  active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE INDEX ix_product_need_group ON product(need_group_id);
CREATE INDEX ix_product_brand ON product(brand_id);
CREATE INDEX ix_product_supplier ON product(supplier_id);

-- @domain REF @feeds AGENT @grain one row per EU FIC Annex II allergen (14)
CREATE TABLE allergen (
  allergen_code  TEXT PRIMARY KEY,                 -- 'milk','nuts','cereals_gluten', ...
  label          TEXT NOT NULL
);

-- @domain REF @feeds AGENT @grain one row per product × allergen
CREATE TABLE product_allergen (
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  allergen_code  TEXT NOT NULL REFERENCES allergen(allergen_code),
  presence       TEXT NOT NULL CHECK (presence IN ('contains','may_contain')),
  PRIMARY KEY (product_id, allergen_code)
);
CREATE INDEX ix_product_allergen_code ON product_allergen(allergen_code);

-- @domain REF @feeds AGENT @grain one row per diet tag
CREATE TABLE diet_tag (
  diet_code      TEXT PRIMARY KEY,                 -- 'lactose_free','vegan','vegetarian','gluten_free','halal'
  label          TEXT NOT NULL
);

CREATE TABLE product_diet (
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  diet_code      TEXT NOT NULL REFERENCES diet_tag(diet_code),
  PRIMARY KEY (product_id, diet_code)
);
CREATE INDEX ix_product_diet_code ON product_diet(diet_code);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per certificate / label scheme
CREATE TABLE certificate (
  certificate_code TEXT PRIMARY KEY,               -- 'eu_organic','msc','fairtrade','hyvaa_suomesta'
  label          TEXT NOT NULL,
  issuer         TEXT NOT NULL,
  is_sustainability INTEGER NOT NULL DEFAULT 1 CHECK (is_sustainability IN (0,1))
);

CREATE TABLE product_certificate (
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  certificate_code TEXT NOT NULL REFERENCES certificate(certificate_code),
  valid_until    TEXT NOT NULL,
  credential_ref TEXT,                             -- VC id from the certifier (trust level L2)
  PRIMARY KEY (product_id, certificate_code)
);

-- @domain REF @feeds INSIGHT @grain one row per category (stretch: category carbon ranges)
CREATE TABLE emission_factor (
  category_id    TEXT PRIMARY KEY REFERENCES category(category_id),
  kg_co2e_per_kg_low  NUMERIC NOT NULL,
  kg_co2e_per_kg_high NUMERIC NOT NULL,
  source         TEXT NOT NULL
);

-- @domain REF @feeds AGENT,INSIGHT @grain one row per dish (menu item)
CREATE TABLE dish (
  dish_id        TEXT PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,             -- 'Beef tenderloin', 'Rosolli'
  course         TEXT CHECK (course IN ('starter','main','side','dessert','breakfast','drink','buffet'))
);

-- @domain CFG @feeds AGENT @grain one row per recipe version (Aimo default or kitchen-owned)
CREATE TABLE recipe (
  recipe_id      TEXT PRIMARY KEY,
  dish_id        TEXT NOT NULL REFERENCES dish(dish_id),
  owner_org_id   TEXT REFERENCES organization(org_id),   -- NULL = Valio Aimo default recipe
  version        INTEGER NOT NULL,
  diet_variant   TEXT REFERENCES diet_tag(diet_code),    -- NULL = standard version
  portion_g      NUMERIC,
  UNIQUE (dish_id, owner_org_id, version, diet_variant)
);

-- @domain CFG @feeds AGENT @grain one row per recipe × ingredient need group
CREATE TABLE recipe_ingredient (
  recipe_id      TEXT NOT NULL REFERENCES recipe(recipe_id),
  need_group_id  TEXT NOT NULL REFERENCES need_group(need_group_id),
  qty_per_portion NUMERIC NOT NULL CHECK (qty_per_portion > 0),  -- in need_group base unit
  yield_factor   NUMERIC NOT NULL DEFAULT 1.0 CHECK (yield_factor > 0 AND yield_factor <= 1),
  PRIMARY KEY (recipe_id, need_group_id)
);


-- @domain REF @feeds AGENT,INSIGHT @grain one row per calendar day
-- Context that explains consumption: weekday, season, holidays (FI).
CREATE TABLE calendar_day (
  day            TEXT PRIMARY KEY,                 -- ISO date
  iso_week       INTEGER NOT NULL,
  weekday        INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
  month          INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  season         TEXT NOT NULL CHECK (season IN ('winter','spring','summer','autumn')),
  is_public_holiday INTEGER NOT NULL DEFAULT 0 CHECK (is_public_holiday IN (0,1)),
  is_school_holiday INTEGER NOT NULL DEFAULT 0 CHECK (is_school_holiday IN (0,1)),
  holiday_name   TEXT                              -- 'Juhannus', 'Itsenaisyyspaiva'
);

-- @domain REF @feeds INSIGHT @grain one row per outcome label definition
CREATE TABLE label_definition (
  label_code     TEXT PRIMARY KEY,                 -- 'right_sized','over_ordered','under_ordered','perfect_order','good_substitute','bad_substitute','price_good','late_delivery','autonomous','corrected'
  level          TEXT NOT NULL CHECK (level IN ('process','order_line','event')),
  definition     TEXT NOT NULL,                    -- human-readable rule, e.g. 'utilisation >= 0.95 and no shortage'
  rule_version   TEXT NOT NULL
);

-- @domain REF @feeds INSIGHT @grain one row per governed metric (semantic layer)
CREATE TABLE metric_definition (
  metric_code    TEXT PRIMARY KEY,                 -- 'autonomous_rate','manual_correction_rate','utilisation','waste_eur','need_by_hit_rate', ...
  name           TEXT NOT NULL,
  formula        TEXT NOT NULL,                    -- SQL expression over a named view
  source_view    TEXT NOT NULL,
  grain          TEXT NOT NULL,
  unit           TEXT NOT NULL,                    -- '%','EUR','kg','min'
  better_when    TEXT NOT NULL CHECK (better_when IN ('higher','lower','target')),
  audience       TEXT NOT NULL CHECK (audience IN ('buyer','aimo_ops','both'))
);

-- Lookup tables for codes used in transactions
CREATE TABLE policy_rule (
  rule_id        TEXT PRIMARY KEY,                 -- 'R0'..'R9','R10_non_favourite'
  name           TEXT NOT NULL,
  default_outcome TEXT NOT NULL CHECK (default_outcome IN ('AUTO','NOTIFY','APPROVE','BLOCK')),
  description    TEXT NOT NULL
);

CREATE TABLE criterion (
  criterion_code TEXT PRIMARY KEY,                 -- 'price','spec_match','delivery','quality','sustainability','brand','pack_fit','history'
  label          TEXT NOT NULL
);

CREATE TABLE exclusion_reason (
  reason_code    TEXT PRIMARY KEY,                 -- 'allergen','diet','late_delivery','never_buy','price_ceiling','out_of_stock'
  label          TEXT NOT NULL
);

CREATE TABLE exception_type (
  exception_code TEXT PRIMARY KEY,                 -- 'offer_expired','price_changed','insufficient_stock','delivery_unavailable','rate_limited'
  label          TEXT NOT NULL
);

CREATE TABLE waste_reason (
  waste_reason_code TEXT PRIMARY KEY,              -- 'expired','over_ordered','quality','prep_waste','plate_waste','damaged'
  label          TEXT NOT NULL
);

CREATE TABLE quality_issue (
  quality_issue_code TEXT PRIMARY KEY,             -- 'damaged','temperature','short_dated','wrong_item'
  label          TEXT NOT NULL
);

-- =====================================================================
-- 2. CONFIGURATION & GOVERNANCE  (@domain CFG) — versioned, never updated in place
-- =====================================================================

-- @domain CFG @feeds AGENT,TRUST @grain one row per signed mandate version
CREATE TABLE mandate (
  mandate_id     TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES organization(org_id),
  version        INTEGER NOT NULL,
  issued_by_user_id TEXT NOT NULL REFERENCES app_user(user_id),
  valid_from     TEXT NOT NULL,
  valid_until    TEXT NOT NULL,
  per_order_limit_eur  NUMERIC NOT NULL,
  per_month_limit_eur  NUMERIC NOT NULL,
  per_event_limit_eur  NUMERIC,
  max_sub_price_delta_pct NUMERIC NOT NULL DEFAULT 5,
  allow_brand_switch   INTEGER NOT NULL DEFAULT 1 CHECK (allow_brand_switch IN (0,1)),
  allow_pack_change    INTEGER NOT NULL DEFAULT 1 CHECK (allow_pack_change IN (0,1)),
  same_category_only   INTEGER NOT NULL DEFAULT 1 CHECK (same_category_only IN (0,1)),
  signature_jws  TEXT NOT NULL,
  supersedes_mandate_id TEXT REFERENCES mandate(mandate_id),
  change_source  TEXT CHECK (change_source IN ('manual','recommendation')),  -- did an insight cause this?
  UNIQUE (org_id, version)
);

CREATE TABLE mandate_allowed_category (
  mandate_id     TEXT NOT NULL REFERENCES mandate(mandate_id),
  category_id    TEXT NOT NULL REFERENCES category(category_id),
  PRIMARY KEY (mandate_id, category_id)
);

CREATE TABLE mandate_excluded_allergen (
  mandate_id     TEXT NOT NULL REFERENCES mandate(mandate_id),
  allergen_code  TEXT NOT NULL REFERENCES allergen(allergen_code),
  PRIMARY KEY (mandate_id, allergen_code)
);

CREATE TABLE mandate_required_diet (
  mandate_id     TEXT NOT NULL REFERENCES mandate(mandate_id),
  diet_code      TEXT NOT NULL REFERENCES diet_tag(diet_code),
  PRIMARY KEY (mandate_id, diet_code)
);

-- @domain CFG @feeds AGENT @grain one row per preference profile version and scope
CREATE TABLE preference_profile (
  profile_id     TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES organization(org_id),
  site_id        TEXT REFERENCES site(site_id),           -- NULL = org-wide
  category_id    TEXT REFERENCES category(category_id),   -- NULL = all categories
  version        INTEGER NOT NULL,
  preset         TEXT CHECK (preset IN ('lowest_price','balanced','premium_quality','domestic_sustainable','fastest_delivery','custom')),
  created_by_user_id TEXT NOT NULL REFERENCES app_user(user_id),
  created_at     TEXT NOT NULL,
  UNIQUE (org_id, site_id, category_id, version)
);

-- @grain one row per profile × criterion (weights sum to 1 per profile)
CREATE TABLE preference_weight (
  profile_id     TEXT NOT NULL REFERENCES preference_profile(profile_id),
  criterion_code TEXT NOT NULL REFERENCES criterion(criterion_code),
  weight         NUMERIC NOT NULL CHECK (weight >= 0 AND weight <= 1),
  PRIMARY KEY (profile_id, criterion_code)
);

-- @grain one row per filter in a profile
CREATE TABLE preference_filter (
  filter_id      TEXT PRIMARY KEY,
  profile_id     TEXT NOT NULL REFERENCES preference_profile(profile_id),
  filter_type    TEXT NOT NULL CHECK (filter_type IN ('price_ceiling','brand','supplier','certificate','origin','quality_min','pack_size','max_lead_days')),
  mode           TEXT NOT NULL CHECK (mode IN ('required','preferred','excluded')),
  brand_id       TEXT REFERENCES brand(brand_id),
  supplier_id    TEXT REFERENCES supplier(supplier_id),
  certificate_code TEXT REFERENCES certificate(certificate_code),
  country_code   TEXT REFERENCES country(country_code),
  numeric_value  NUMERIC,                          -- ceiling EUR/base unit, lead days, pack size
  text_value     TEXT                              -- quality grade
);
CREATE INDEX ix_pref_filter_profile ON preference_filter(profile_id);

-- @grain one row per profile × product list membership
CREATE TABLE product_list (
  list_id        TEXT PRIMARY KEY,
  profile_id     TEXT NOT NULL REFERENCES preference_profile(profile_id),
  name           TEXT NOT NULL,                    -- 'Favourites','Never buy','Breakfast buffet'
  list_kind      TEXT NOT NULL CHECK (list_kind IN ('favourite','never_buy','pinned_default','custom'))
);

CREATE TABLE product_list_item (
  list_id        TEXT NOT NULL REFERENCES product_list(list_id),
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  rank           INTEGER,                          -- fallback order within a need group (pinned lists)
  added_at       TEXT NOT NULL,
  PRIMARY KEY (list_id, product_id)
);

-- =====================================================================
-- 3. ORDER PROCESS TRANSACTIONS  (@domain TXN)
-- =====================================================================

-- @domain TXN @feeds AGENT,INSIGHT @grain one row per event (gala, breakfast service, pikkujoulut)
CREATE TABLE event (
  event_id       TEXT PRIMARY KEY,
  site_id        TEXT NOT NULL REFERENCES site(site_id),
  name           TEXT NOT NULL,
  event_type     TEXT NOT NULL CHECK (event_type IN ('gala','banquet','buffet','breakfast','conference','christmas_party','weekly_service','other')),
  service_style  TEXT NOT NULL CHECK (service_style IN ('plated','buffet','family','takeaway')),
  starts_at      TEXT NOT NULL,
  expected_guests INTEGER NOT NULL CHECK (expected_guests > 0),
  actual_guests  INTEGER,                          -- filled at reconciliation (forecast accuracy)
  created_by_user_id TEXT NOT NULL REFERENCES app_user(user_id)
);
CREATE INDEX ix_event_site_date ON event(site_id, starts_at);

CREATE TABLE event_diet_count (
  event_id       TEXT NOT NULL REFERENCES event(event_id),
  diet_code      TEXT NOT NULL REFERENCES diet_tag(diet_code),
  guests         INTEGER NOT NULL CHECK (guests >= 0),
  PRIMARY KEY (event_id, diet_code)
);

CREATE TABLE event_allergy_count (
  event_id       TEXT NOT NULL REFERENCES event(event_id),
  allergen_code  TEXT NOT NULL REFERENCES allergen(allergen_code),
  guests         INTEGER NOT NULL CHECK (guests >= 0),
  PRIMARY KEY (event_id, allergen_code)
);

-- @grain one row per dish (and diet variant) served at an event
CREATE TABLE event_dish (
  event_dish_id  TEXT PRIMARY KEY,
  event_id       TEXT NOT NULL REFERENCES event(event_id),
  recipe_id      TEXT NOT NULL REFERENCES recipe(recipe_id),   -- dish & diet variant via recipe
  planned_portions INTEGER NOT NULL CHECK (planned_portions > 0),
  served_portions INTEGER,                         -- reconciliation, optional
  UNIQUE (event_id, recipe_id)
);

-- @domain TXN @feeds AGENT,INSIGHT,TRUST @grain one row per buyer request (one process / trace)
CREATE TABLE purchase_process (
  process_id     TEXT PRIMARY KEY,                 -- = traceId in audit
  site_id        TEXT NOT NULL REFERENCES site(site_id),     -- org via site (3NF)
  agent_id       TEXT NOT NULL REFERENCES agent(agent_id),
  requested_by_user_id TEXT REFERENCES app_user(user_id),
  event_id       TEXT REFERENCES event(event_id),
  context_type   TEXT NOT NULL CHECK (context_type IN ('event','standing','ad_hoc','replenishment')),
  channel        TEXT NOT NULL CHECK (channel IN ('voice','text','api','standing_order')),
  language       TEXT CHECK (language IN ('en','fi','sv')),
  request_excerpt TEXT,                            -- max 280 chars; no transcripts
  mandate_id     TEXT NOT NULL REFERENCES mandate(mandate_id),
  profile_id     TEXT NOT NULL REFERENCES preference_profile(profile_id),
  need_by        TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('open','awaiting_approval','ordered','rejected','blocked','expired','delivered','reconciled')),
  created_at     TEXT NOT NULL,
  closed_at      TEXT,
  tool_call_count INTEGER                          -- agent effort (efficiency insight)
);
CREATE INDEX ix_process_site_created ON purchase_process(site_id, created_at);
CREATE INDEX ix_process_status ON purchase_process(status);
CREATE INDEX ix_process_event ON purchase_process(event_id);

-- @grain one row per requested need (line) in a process
CREATE TABLE request_line (
  request_line_id TEXT PRIMARY KEY,
  process_id     TEXT NOT NULL REFERENCES purchase_process(process_id),
  need_group_id  TEXT NOT NULL REFERENCES need_group(need_group_id),
  requested_product_id TEXT REFERENCES product(product_id),  -- set when buyer named a product
  event_dish_id  TEXT REFERENCES event_dish(event_dish_id),   -- set when derived from a recipe
  qty_requested  NUMERIC NOT NULL CHECK (qty_requested > 0),
  unit_code      TEXT NOT NULL REFERENCES unit(unit_code),
  qty_from_leftovers NUMERIC NOT NULL DEFAULT 0,               -- netted from leftover stock
  history_adjustment_pct NUMERIC                               -- right-sizing applied (+/-)
);
CREATE INDEX ix_request_line_process ON request_line(process_id);
CREATE INDEX ix_request_line_need ON request_line(need_group_id);

-- @grain one row per candidate product excluded before scoring (why-not evidence)
CREATE TABLE candidate_exclusion (
  process_id     TEXT NOT NULL REFERENCES purchase_process(process_id),
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  reason_code    TEXT NOT NULL REFERENCES exclusion_reason(reason_code),
  PRIMARY KEY (process_id, product_id, reason_code)
);

-- @domain TXN @feeds AGENT,TRUST,INSIGHT @grain one row per signed offer attestation
-- PostgreSQL: partition by month on valid_from; BRIN index on valid_from.
CREATE TABLE offer (
  offer_id       TEXT PRIMARY KEY,
  process_id     TEXT NOT NULL REFERENCES purchase_process(process_id),
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  unit_price_eur NUMERIC NOT NULL CHECK (unit_price_eur >= 0),   -- per pack
  qty_available_packs INTEGER NOT NULL CHECK (qty_available_packs >= 0),
  availability_as_of TEXT NOT NULL,
  stock_confidence TEXT NOT NULL CHECK (stock_confidence IN ('high','medium','low')),
  earliest_delivery TEXT NOT NULL,
  order_cutoff   TEXT,
  claimed_on_time_rate NUMERIC CHECK (claimed_on_time_rate BETWEEN 0 AND 1),
  valid_from     TEXT NOT NULL,
  valid_until    TEXT NOT NULL,
  jws_sha256     TEXT NOT NULL,                    -- hash of the signed attestation (full JWS in object store)
  verification   TEXT NOT NULL CHECK (verification IN ('valid','expired','bad_signature','revoked'))
);
CREATE INDEX ix_offer_process ON offer(process_id);
CREATE INDEX ix_offer_product_time ON offer(product_id, valid_from);   -- price history

-- @grain one row per alternative plan proposed
CREATE TABLE plan (
  plan_id        TEXT PRIMARY KEY,
  process_id     TEXT NOT NULL REFERENCES purchase_process(process_id),
  plan_label     TEXT NOT NULL,                    -- 'P1'
  strategy       TEXT NOT NULL CHECK (strategy IN ('single','split_products','split_dates','partial_substitute')),
  tier           TEXT NOT NULL CHECK (tier IN ('BEST','BETTER','GOOD')),
  rank           INTEGER NOT NULL CHECK (rank >= 1),
  total_score    NUMERIC NOT NULL,
  tradeoff_text  TEXT NOT NULL,
  UNIQUE (process_id, plan_label)
);
CREATE INDEX ix_plan_process ON plan(process_id);

-- @grain one row per plan × criterion (explainability of ranking)
CREATE TABLE plan_score (
  plan_id        TEXT NOT NULL REFERENCES plan(plan_id),
  criterion_code TEXT NOT NULL REFERENCES criterion(criterion_code),
  raw_score      NUMERIC NOT NULL CHECK (raw_score BETWEEN 0 AND 1),
  weight         NUMERIC NOT NULL,                 -- snapshot: profile weights may change later
  PRIMARY KEY (plan_id, criterion_code)
);

-- @grain one row per line in a plan
CREATE TABLE plan_line (
  plan_line_id   TEXT PRIMARY KEY,
  plan_id        TEXT NOT NULL REFERENCES plan(plan_id),
  request_line_id TEXT NOT NULL REFERENCES request_line(request_line_id),
  offer_id       TEXT NOT NULL REFERENCES offer(offer_id),       -- product & price via offer (3NF)
  qty_cases      INTEGER NOT NULL CHECK (qty_cases > 0),
  delivery_date  TEXT NOT NULL,
  signal_note    TEXT                              -- 'learned: kitchen accepted this swap 3/3'
);
CREATE INDEX ix_plan_line_plan ON plan_line(plan_id);

-- @domain TXN @feeds AGENT,TRUST,INSIGHT @grain one row per policy evaluation of a plan
CREATE TABLE policy_decision (
  decision_id    TEXT PRIMARY KEY,
  plan_id        TEXT NOT NULL REFERENCES plan(plan_id),          -- process via plan
  outcome        TEXT NOT NULL CHECK (outcome IN ('AUTO','NOTIFY','APPROVE','BLOCK')),
  evaluated_at   TEXT NOT NULL,
  policy_version TEXT NOT NULL
);
CREATE INDEX ix_decision_plan ON policy_decision(plan_id);

-- @grain one row per rule that fired in a decision
CREATE TABLE decision_rule_hit (
  decision_id    TEXT NOT NULL REFERENCES policy_decision(decision_id),
  rule_id        TEXT NOT NULL REFERENCES policy_rule(rule_id),
  plan_line_id   TEXT REFERENCES plan_line(plan_line_id),         -- NULL = whole-basket rule
  reason_text    TEXT NOT NULL,
  PRIMARY KEY (decision_id, rule_id, plan_line_id)
);
CREATE INDEX ix_rule_hit_rule ON decision_rule_hit(rule_id);

-- @domain TXN @feeds AGENT,INSIGHT,TRUST @grain one row per human approval task
CREATE TABLE approval (
  approval_id    TEXT PRIMARY KEY,
  decision_id    TEXT NOT NULL UNIQUE REFERENCES policy_decision(decision_id),
  approver_user_id TEXT REFERENCES app_user(user_id),
  requested_at   TEXT NOT NULL,
  decided_at     TEXT,
  action         TEXT CHECK (action IN ('approve','reject','modify','expired')),
  comment        TEXT
);
CREATE INDEX ix_approval_open ON approval(decided_at);

-- @grain one row per field a human changed (manual corrections and preference choices)
CREATE TABLE manual_change (
  change_id      TEXT PRIMARY KEY,
  process_id     TEXT NOT NULL REFERENCES purchase_process(process_id),
  approval_id    TEXT REFERENCES approval(approval_id),
  plan_line_id   TEXT REFERENCES plan_line(plan_line_id),
  changed_by_user_id TEXT NOT NULL REFERENCES app_user(user_id),
  change_kind    TEXT NOT NULL CHECK (change_kind IN ('preference_choice','error_correction')),
  field          TEXT NOT NULL CHECK (field IN ('product','qty','delivery_date','supplier','removed_line','added_line')),
  old_value      TEXT,
  new_value      TEXT,
  changed_at     TEXT NOT NULL
);
CREATE INDEX ix_manual_change_process ON manual_change(process_id);

-- @grain one row per exception during a process
CREATE TABLE process_exception (
  exception_id   TEXT PRIMARY KEY,
  process_id     TEXT NOT NULL REFERENCES purchase_process(process_id),
  exception_code TEXT NOT NULL REFERENCES exception_type(exception_code),
  offer_id       TEXT REFERENCES offer(offer_id),
  occurred_at    TEXT NOT NULL,
  resolved_by    TEXT CHECK (resolved_by IN ('requote','replan','substitute','human','none'))
);
CREATE INDEX ix_exception_process ON process_exception(process_id);

-- @domain TXN @feeds INSIGHT,TRUST @grain one row per order placed at Valio Aimo
CREATE TABLE purchase_order (
  order_id       TEXT PRIMARY KEY,
  plan_id        TEXT NOT NULL UNIQUE REFERENCES plan(plan_id),   -- process via plan; chosen plan = ordered plan
  aimo_order_ref TEXT NOT NULL UNIQUE,
  placed_at      TEXT NOT NULL,
  confirmation_jws_sha256 TEXT NOT NULL
);

-- @grain one row per ordered line (final, after human modifications)
CREATE TABLE order_line (
  order_line_id  TEXT PRIMARY KEY,
  order_id       TEXT NOT NULL REFERENCES purchase_order(order_id),
  request_line_id TEXT NOT NULL REFERENCES request_line(request_line_id),
  offer_id       TEXT NOT NULL REFERENCES offer(offer_id),        -- product & price via offer
  qty_cases      INTEGER NOT NULL CHECK (qty_cases > 0),
  delivery_date  TEXT NOT NULL
);
CREATE INDEX ix_order_line_order ON order_line(order_id);
CREATE INDEX ix_order_line_offer ON order_line(offer_id);

-- =====================================================================
-- 4. OBSERVED OUTCOMES  (@domain OBS)
-- =====================================================================

-- @domain OBS @feeds AGENT,INSIGHT @grain one row per delivery of an order line
CREATE TABLE delivery_line (
  delivery_line_id TEXT PRIMARY KEY,
  order_line_id  TEXT NOT NULL REFERENCES order_line(order_line_id),
  delivered_at   TEXT,
  qty_delivered_packs INTEGER NOT NULL CHECK (qty_delivered_packs >= 0),
  quality_issue_code TEXT REFERENCES quality_issue(quality_issue_code),
  best_before    TEXT
);
CREATE INDEX ix_delivery_order_line ON delivery_line(order_line_id);

-- @domain OBS @feeds AGENT,INSIGHT @grain one row per order line reconciliation (after use)
CREATE TABLE consumption (
  consumption_id TEXT PRIMARY KEY,
  order_line_id  TEXT NOT NULL UNIQUE REFERENCES order_line(order_line_id),
  qty_used       NUMERIC NOT NULL CHECK (qty_used >= 0),           -- base units
  qty_kept       NUMERIC NOT NULL DEFAULT 0 CHECK (qty_kept >= 0),
  qty_redistributed NUMERIC NOT NULL DEFAULT 0 CHECK (qty_redistributed >= 0),
  qty_wasted     NUMERIC NOT NULL DEFAULT 0 CHECK (qty_wasted >= 0),
  waste_reason_code TEXT REFERENCES waste_reason(waste_reason_code),
  shortage_qty   NUMERIC NOT NULL DEFAULT 0 CHECK (shortage_qty >= 0),
  emergency_purchase INTEGER NOT NULL DEFAULT 0 CHECK (emergency_purchase IN (0,1)),
  recorded_by_user_id TEXT NOT NULL REFERENCES app_user(user_id),
  recorded_at    TEXT NOT NULL,
  method         TEXT NOT NULL CHECK (method IN ('one_tap_all_used','manual','prefilled_estimate','scale'))
);

-- @domain OBS @feeds AGENT @grain one row per leftover lot available at a site
CREATE TABLE leftover_lot (
  lot_id         TEXT PRIMARY KEY,
  site_id        TEXT NOT NULL REFERENCES site(site_id),
  product_id     TEXT NOT NULL REFERENCES product(product_id),
  source_consumption_id TEXT REFERENCES consumption(consumption_id),
  qty_base       NUMERIC NOT NULL CHECK (qty_base >= 0),
  best_before    TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('available','used','wasted','redistributed')),
  used_in_process_id TEXT REFERENCES purchase_process(process_id)
);
CREATE INDEX ix_leftover_site_status ON leftover_lot(site_id, status, best_before);

-- @domain OBS @feeds AGENT,INSIGHT @grain one row per kitchen feedback on an order line
CREATE TABLE line_feedback (
  order_line_id  TEXT PRIMARY KEY REFERENCES order_line(order_line_id),
  rating         INTEGER CHECK (rating BETWEEN 1 AND 5),
  substitute_accepted INTEGER CHECK (substitute_accepted IN (0,1)),  -- NULL if not a substitute
  given_by_user_id TEXT NOT NULL REFERENCES app_user(user_id),
  given_at       TEXT NOT NULL
);

-- @grain one row per recommendation shown to the buyer (closes the insight loop)
CREATE TABLE recommendation (
  recommendation_id TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES organization(org_id),
  kind           TEXT NOT NULL CHECK (kind IN ('mandate_change','preference_change','quantity_rightsizing','supplier_switch','ordering_cutoff','favourite_add','drift_alert')),
  title          TEXT NOT NULL,
  evidence_json  TEXT NOT NULL,                    -- {n, period, process_ids} (PostgreSQL: JSONB)
  expected_impact_eur NUMERIC,
  created_at     TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('open','applied','dismissed')),
  applied_mandate_id TEXT REFERENCES mandate(mandate_id),
  applied_profile_id TEXT REFERENCES preference_profile(profile_id)
);
CREATE INDEX ix_reco_org_status ON recommendation(org_id, status);


-- @domain OBS @feeds AGENT,INSIGHT @grain one row per site × day
-- Demand drivers captured daily; explains why use per guest varies.
CREATE TABLE site_day_context (
  site_id        TEXT NOT NULL REFERENCES site(site_id),
  day            TEXT NOT NULL REFERENCES calendar_day(day),
  covers_served  INTEGER,                          -- meals actually served that day
  occupancy_rate NUMERIC CHECK (occupancy_rate BETWEEN 0 AND 1),  -- hotels, hospitals
  temp_c_max     NUMERIC,                          -- weather drives cold drinks, ice cream, soups
  precipitation_mm NUMERIC,
  local_event_flag INTEGER NOT NULL DEFAULT 0 CHECK (local_event_flag IN (0,1)),
  source         TEXT NOT NULL CHECK (source IN ('pms','pos','manual','weather_api')),
  PRIMARY KEY (site_id, day)
);

-- @domain DER @feeds AGENT,INSIGHT @grain one row per label applied to a process, line or event
-- Materialised outcome labels: the refined, queryable "was this good?" layer and
-- the training/evaluation set for the agent. Computed by versioned rules; humans may override.
CREATE TABLE outcome_label (
  label_id       TEXT PRIMARY KEY,
  label_code     TEXT NOT NULL REFERENCES label_definition(label_code),
  process_id     TEXT REFERENCES purchase_process(process_id),
  order_line_id  TEXT REFERENCES order_line(order_line_id),
  event_id       TEXT REFERENCES event(event_id),
  value          NUMERIC,                          -- e.g. utilisation 0.97 behind 'right_sized'
  source         TEXT NOT NULL CHECK (source IN ('rule','human','model')),
  labelled_at    TEXT NOT NULL,
  CHECK ((process_id IS NOT NULL) + (order_line_id IS NOT NULL) + (event_id IS NOT NULL) = 1)
);
CREATE INDEX ix_label_code ON outcome_label(label_code);
CREATE INDEX ix_label_process ON outcome_label(process_id);
CREATE INDEX ix_label_line ON outcome_label(order_line_id);
CREATE INDEX ix_label_event ON outcome_label(event_id);

-- =====================================================================
-- 5. AUDIT  (@domain AUD) — append-only, hash-chained
-- PostgreSQL: partition by month; revoke UPDATE/DELETE; retention >= 6 months.
-- =====================================================================
CREATE TABLE audit_event (
  audit_event_id TEXT PRIMARY KEY,
  process_id     TEXT REFERENCES purchase_process(process_id),
  seq            INTEGER NOT NULL,
  ts             TEXT NOT NULL,
  actor_type     TEXT NOT NULL CHECK (actor_type IN ('agent','human','system')),
  actor_ref      TEXT NOT NULL,                    -- agent_id / user_id / 'policy'
  action         TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  prev_hash      TEXT NOT NULL,
  hash           TEXT NOT NULL UNIQUE,
  UNIQUE (process_id, seq)
);
CREATE INDEX ix_audit_ts ON audit_event(ts);

-- =====================================================================
-- 6. DERIVED VIEWS  (@domain DER) — denormalised for fast queries.
-- In production these become materialised views refreshed per process close.
-- =====================================================================

-- Base-unit quantity and value per ordered line
CREATE VIEW v_order_line_fact AS
SELECT ol.order_line_id,
       po.order_id,
       pl.process_id,
       pp.site_id,
       s.org_id,
       pp.event_id,
       pp.context_type,
       p.product_id, p.gtin, p.name AS product_name,
       p.brand_id, p.supplier_id, p.need_group_id, ng.category_id,
       p.origin_country_code,
       ol.qty_cases,
       ol.qty_cases * p.units_per_case                         AS qty_packs,
       ol.qty_cases * p.units_per_case * p.pack_size * u.to_base_factor AS qty_base,
       o.unit_price_eur,
       ol.qty_cases * p.units_per_case * o.unit_price_eur       AS line_value_eur,
       o.unit_price_eur / (p.pack_size * u.to_base_factor)      AS price_per_base_unit,
       CASE WHEN rl.requested_product_id IS NOT NULL
             AND rl.requested_product_id <> p.product_id THEN 1 ELSE 0 END AS is_substitute,
       rl.qty_requested * ru.to_base_factor                    AS qty_requested_base,
       ol.delivery_date,
       pp.need_by,
       po.placed_at
FROM order_line ol
JOIN purchase_order po ON po.order_id = ol.order_id
JOIN plan pl           ON pl.plan_id = po.plan_id
JOIN purchase_process pp ON pp.process_id = pl.process_id
JOIN site s            ON s.site_id = pp.site_id
JOIN offer o           ON o.offer_id = ol.offer_id
JOIN product p         ON p.product_id = o.product_id
JOIN unit u            ON u.unit_code = p.pack_unit_code
JOIN need_group ng     ON ng.need_group_id = p.need_group_id
JOIN request_line rl   ON rl.request_line_id = ol.request_line_id
JOIN unit ru           ON ru.unit_code = rl.unit_code;

-- One row per process with outcome KPIs (the "process scorecard")
CREATE VIEW v_process_fact AS
SELECT pp.process_id, pp.site_id, s.org_id, pp.event_id, pp.context_type, pp.channel,
       pp.status, pp.created_at, pp.closed_at, pp.need_by,
       (SELECT pd.outcome FROM plan pl2 JOIN policy_decision pd ON pd.plan_id = pl2.plan_id
          JOIN purchase_order po2 ON po2.plan_id = pl2.plan_id
         WHERE pl2.process_id = pp.process_id ORDER BY pd.evaluated_at DESC LIMIT 1) AS final_outcome,
       (SELECT pl3.tier FROM plan pl3 JOIN purchase_order po3 ON po3.plan_id = pl3.plan_id
         WHERE pl3.process_id = pp.process_id) AS chosen_tier,
       (SELECT pl4.rank FROM plan pl4 JOIN purchase_order po4 ON po4.plan_id = pl4.plan_id
         WHERE pl4.process_id = pp.process_id) AS chosen_rank,
       (SELECT SUM(f.line_value_eur) FROM v_order_line_fact f WHERE f.process_id = pp.process_id) AS order_value_eur,
       (SELECT COUNT(*) FROM manual_change mc WHERE mc.process_id = pp.process_id AND mc.change_kind = 'error_correction') AS corrections,
       (SELECT COUNT(*) FROM manual_change mc WHERE mc.process_id = pp.process_id AND mc.change_kind = 'preference_choice') AS preference_choices,
       (SELECT COUNT(*) FROM process_exception pe WHERE pe.process_id = pp.process_id) AS exceptions,
       pp.tool_call_count
FROM purchase_process pp
JOIN site s ON s.site_id = pp.site_id;

-- Usage & waste per ordered line (event reports, waste dashboard)
CREATE VIEW v_usage_fact AS
SELECT f.order_line_id, f.process_id, f.site_id, f.org_id, f.event_id, f.product_id,
       f.need_group_id, f.category_id, f.qty_base AS qty_ordered_base, f.line_value_eur,
       c.qty_used, c.qty_kept, c.qty_redistributed, c.qty_wasted, c.shortage_qty,
       c.waste_reason_code, c.emergency_purchase,
       CASE WHEN f.qty_base > 0 THEN 1.0 * c.qty_used / f.qty_base END          AS utilisation,
       CASE WHEN f.qty_base > 0 THEN 1.0 * c.qty_wasted / f.qty_base END        AS waste_rate,
       c.qty_wasted * f.price_per_base_unit                                     AS waste_value_eur
FROM v_order_line_fact f
JOIN consumption c ON c.order_line_id = f.order_line_id;

-- Requested vs ordered per request line (case-rounding overage, coverage)
CREATE VIEW v_request_fulfilment AS
SELECT rl.request_line_id, rl.process_id, rl.need_group_id,
       rl.qty_requested * u.to_base_factor          AS qty_requested_base,
       rl.qty_from_leftovers,
       COALESCE(SUM(f.qty_base), 0)                 AS qty_ordered_base,
       COALESCE(SUM(f.qty_base), 0) + rl.qty_from_leftovers - rl.qty_requested * u.to_base_factor AS overage_base,
       1.0 * (COALESCE(SUM(f.qty_base), 0) + rl.qty_from_leftovers) / (rl.qty_requested * u.to_base_factor) AS coverage,
       MAX(f.is_substitute)                         AS has_substitute
FROM request_line rl
JOIN unit u ON u.unit_code = rl.unit_code
LEFT JOIN order_line ol      ON ol.request_line_id = rl.request_line_id
LEFT JOIN v_order_line_fact f ON f.order_line_id = ol.order_line_id
GROUP BY rl.request_line_id, rl.process_id, rl.need_group_id, rl.qty_requested, u.to_base_factor, rl.qty_from_leftovers;

-- =====================================================================
-- 7. LEARNING SIGNALS  (@domain DER @feeds AGENT) — what makes the agent precise
-- =====================================================================

-- Substitution acceptance per org × (requested → substitute) product pair
CREATE VIEW sig_substitution_acceptance AS
SELECT f.org_id,
       rl.requested_product_id AS from_product_id,
       f.product_id            AS to_product_id,
       COUNT(*)                                      AS n,
       SUM(COALESCE(lf.substitute_accepted, 0))      AS accepted,
       1.0 * SUM(COALESCE(lf.substitute_accepted, 0)) / COUNT(*) AS acceptance_rate
FROM v_order_line_fact f
JOIN order_line ol   ON ol.order_line_id = f.order_line_id
JOIN request_line rl ON rl.request_line_id = ol.request_line_id
LEFT JOIN line_feedback lf ON lf.order_line_id = f.order_line_id
WHERE f.is_substitute = 1
GROUP BY f.org_id, rl.requested_product_id, f.product_id;

-- Actual consumption per guest by org × event type × need group (right-sizing)
CREATE VIEW sig_per_guest_consumption AS
WITH per_event AS (               -- aggregate lines to event level first (avoid double-counting guests)
  SELECT u.org_id, u.event_id, u.need_group_id,
         SUM(u.qty_used) AS used, SUM(u.qty_ordered_base) AS ordered, SUM(u.qty_wasted) AS wasted
  FROM v_usage_fact u
  WHERE u.event_id IS NOT NULL
  GROUP BY u.org_id, u.event_id, u.need_group_id)
SELECT pe.org_id, e.event_type, e.service_style, pe.need_group_id,
       COUNT(*)                                                             AS n_events,
       1.0 * SUM(pe.used) / SUM(COALESCE(e.actual_guests, e.expected_guests)) AS used_per_guest,
       1.0 * SUM(pe.ordered) / SUM(e.expected_guests)                       AS ordered_per_guest,
       1.0 * SUM(pe.wasted) / SUM(pe.ordered)                               AS waste_rate,
       MIN(e.starts_at) AS first_event, MAX(e.starts_at) AS last_event      -- evidence window
FROM per_event pe
JOIN event e ON e.event_id = pe.event_id
GROUP BY pe.org_id, e.event_type, e.service_style, pe.need_group_id;

-- Experienced delivery reliability per org × supplier (vs claimed in offers)
CREATE VIEW sig_supplier_reliability AS
SELECT f.org_id, f.supplier_id,
       COUNT(*)                                                  AS n_lines,
       AVG(CASE WHEN dl.delivered_at <= f.need_by THEN 1.0 ELSE 0.0 END) AS on_time_rate,
       AVG(1.0 * dl.qty_delivered_packs / f.qty_packs)           AS fill_rate,
       AVG(CASE WHEN dl.quality_issue_code IS NULL THEN 0.0 ELSE 1.0 END) AS quality_issue_rate
FROM v_order_line_fact f
JOIN delivery_line dl ON dl.order_line_id = f.order_line_id
GROUP BY f.org_id, f.supplier_id;

-- Price history per org × product (judge "is today's price good?")
CREATE VIEW sig_price_history AS
SELECT f.org_id, f.product_id, substr(f.placed_at, 1, 7) AS month,
       MIN(f.price_per_base_unit) AS min_price, AVG(f.price_per_base_unit) AS avg_price,
       MAX(f.price_per_base_unit) AS max_price, COUNT(*) AS n
FROM v_order_line_fact f
GROUP BY f.org_id, f.product_id, substr(f.placed_at, 1, 7);

-- Approval patterns per org × rule (mandate tuning recommendations)
CREATE VIEW sig_approval_pattern AS
SELECT s.org_id, h.rule_id,
       COUNT(*)                                                    AS n,
       AVG(CASE WHEN a.action = 'approve' THEN 1.0 ELSE 0.0 END)   AS approve_rate,
       AVG((julianday(a.decided_at) - julianday(a.requested_at)) * 1440) AS avg_latency_min
FROM decision_rule_hit h
JOIN policy_decision d ON d.decision_id = h.decision_id
JOIN approval a        ON a.decision_id = d.decision_id
JOIN plan pl           ON pl.plan_id = d.plan_id
JOIN purchase_process pp ON pp.process_id = pl.process_id
JOIN site s            ON s.site_id = pp.site_id
WHERE a.decided_at IS NOT NULL
GROUP BY s.org_id, h.rule_id;

-- Agent feature view: one row per org × need group with everything the planner reads
CREATE VIEW v_agent_features AS
SELECT ng.need_group_id, o.org_id,
       (SELECT AVG(g.used_per_guest) FROM sig_per_guest_consumption g
         WHERE g.org_id = o.org_id AND g.need_group_id = ng.need_group_id)            AS used_per_guest,
       (SELECT 1.0 * SUM(u.qty_wasted) / NULLIF(SUM(u.qty_ordered_base),0) FROM v_usage_fact u
         WHERE u.org_id = o.org_id AND u.need_group_id = ng.need_group_id)            AS waste_rate,
       (SELECT 1.0 * SUM(a.accepted) / NULLIF(SUM(a.n),0) FROM sig_substitution_acceptance a
         JOIN product p ON p.product_id = a.to_product_id
         WHERE a.org_id = o.org_id AND p.need_group_id = ng.need_group_id)            AS substitute_acceptance,
       (SELECT COUNT(*) FROM outcome_label l JOIN order_line ol ON ol.order_line_id = l.order_line_id
         JOIN offer of2 ON of2.offer_id = ol.offer_id JOIN product p2 ON p2.product_id = of2.product_id
         JOIN purchase_order po ON po.order_id = ol.order_id JOIN plan pl ON pl.plan_id = po.plan_id
         JOIN purchase_process pp ON pp.process_id = pl.process_id JOIN site s2 ON s2.site_id = pp.site_id
         WHERE s2.org_id = o.org_id AND p2.need_group_id = ng.need_group_id
           AND l.label_code = 'over_ordered')                                          AS over_ordered_count
FROM need_group ng CROSS JOIN organization o;
