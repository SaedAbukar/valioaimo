# Assumptions & decisions

- **Synthetic data only.** 97 products with fictional brands (Kaarna Meijeri, Maitokaari, Tunturi Dairy, Kaura&Co, …) and suppliers; GTINs use a fictional prefix with valid check digits. “Valio Aimo” is used only as the challenge's wholesaler name. Certification labels are real label names used illustratively.
- **Demo clock** anchored at Friday 13 Nov 2026 09:00 EET so “by Monday”, “tomorrow” and “Saturday the 21st” are repeatable. “+16 min” buttons advance it to show expiry.
- **Worked example** reproduced exactly: A 640 L @ €1.29 (preferred), B 800 L @ €1.33 (+3.1 %), C 1,200 L @ €1.41 (+9.3 %), D regular milk filtered (not lactose-free), E barista oat drink filtered (not milk / may contain nuts). Plans P1 €1,304.40 NOTIFY, P2 €1,410 APPROVE, P3 €1,290 APPROVE.
- **Buyers:** Hotelli Pohjola Group (per order €2,000, month €45,000, event €3,300, €26/guest), Kaari Hospital (milk- & nut-free, per order €1,500), Kaarela School Kitchens (no peanuts/nuts/sesame). Names of people are fictional.
- **Event budget calibration:** the gala at 180 guests (~€3,110) auto-orders with NOTIFY; at 200 guests the whole basket exceeds the €3,300 event budget, producing exactly one approval.
- **Substitution primary** = the top-ranked product for the need; deltas are relative to it.
- **Variants:** explicitly requested variants (e.g. “tenderloin”, “oat”) are hard unless strict stock cannot cover the need, then other variants become flagged substitutes (R5).
- **Broken cases** allowed only in Event Autopilot when case rounding would over-order > 10 %.
- **Diet groups** in event briefs are treated as disjoint (a vegan guest is not also counted as gluten-free).
- **Learned per-guest factors** use the median of the last 3 reconciled events of the same type, clamped to 0.6–1.15, and only act with ≥ 2 events.
- **CO₂e** uses rounded category-level kg CO₂e/kg factors (estimates, labelled as such).
- **Day context** (weather, occupancy, local events) is synthetic and deterministic per date.
- **No LLM required.** Parsing is regex/rule-based (EN + basic FI). An optional LLM parsing mode (ANTHROPIC_API_KEY) is a roadmap item; the demo never depends on it.
- **Keys** are generated at start (server) or page load (MVP) and never written to the repository.
- **Backend scope** was reduced to a reference skeleton after the priority change (architecture, UX and problem-solving first); the MVP page carries the full logic.
- **Microphone** is blocked inside the artifact sandbox; the page shows a labelled simulated transcript instead.

## v2 (14 Nov 2026)

- **Two assortments.** The seeded customers (Pohjola, Kaari, Kaarela) keep the curated demo assortment so the golden scenarios are repeatable. The new kitchen (Kahvila Uusi, `assortment: aimo`) and any need the curated set lacks use the **real Valio Aimo product data**. Real product names are never attached to synthetic allergen or stock facts.
- **Mock API live (14 Nov, 09:55).** Key in `.env` (git-ignored). Real products use live price and availability; demo values (median price of the need kind × 0.85–1.2 by product id) are only a fallback when the API fails. The portal password was not used by the agent. Ample stock (999999 / 9999999999) is capped at 100,000 sales units.
- **Understood card does not block.** When nothing critical is missing, the assistant continues straight to Recall and Plan; "Looks right" is an acknowledgement and "Change" lets the chef correct it in words.
- **Basket needs a tap.** Even for "auto" and "tell me", the chef taps Order. Agents calling the API may order directly when Check allows it.
- **Recall order** is fixed: favourites → similar past orders → learned quantities → standing orders → leftovers. Standing orders are shown, not netted (they are separate deliveries).
- **A past event "went well"** when ≥ 60 % of its lines are `right_sized`/`good_substitute` and none `under_ordered`.
- **Learning:** learned per-guest factors only from `right_sized` lines (median of last 3, needs ≥ 2, clamped 0.6–1.15, ignored within ±5 %). Three `over_ordered` in a row → Tip (cut rounded to 5 %, between 5 and 30 %).
- **How did it go?** Used it all = 97 % used (`right_sized`), Some left = 82 % (`over_ordered`), Ran out = 110 % (`under_ordered`).
- **Weekly restock.** Fixture stock is restocked weekly to its starting level for planning further ahead; a guest change releases the earlier order's stock before re-planning.
- **Event limit** stays €3,300 for Pohjola: 180 guests ≈ €3,205 (tell me), 200 guests ≈ €3,329 (needs OK).
- **Can't do this** fires when nothing of the requested kind is safe and on time and an allergen removed the only other candidate; the safe alternative is the best on-time product of the same group.
- **Product choice** appears only for needs with no memory (new kitchen or new item) and at least two on-time options; for orders ≥ 150 packs, tiny packs are skipped.
- **Delivery window** is shown as "in the morning"; the mock API's `closingTime` is not shown yet.
- **Offline page** plays recorded gateway runs (`scripts/record_replays.py`); typed text it has no recording for gets the example requests as tap answers.

## v4 (14 Nov 2026): challenge audit, gateway first

- **The gateway is the product.** README, demo and checklist lead with an external agent; the chef app is one client.
- **Credentials.** Bearer tokens bound to one buyer and one agent (the agent's existing `apiKey` in buyers.json), `demo-human-<personId>` for approvers, `demo-ops` for Valio Aimo operations. Synthetic and public on purpose; production → OAuth 2.1 / buyer SSO (docs/EXPOSURE.md).
- **Agents can never approve.** `POST /v1/approvals/{id}` needs the named approver's credential (403 for agents and for approvers of other buyers); MCP has no approve tool. For API sessions the agent places the order after the OK; for chat sessions the assistant places it straight away.
- **Orders cite offers.** `place_order` needs `offerIds` equal to the checked basket's signed offers; price fields are rejected (`fixed_prices`); stale ids → 409 `offer_mismatch`; expired/changed price → 409 `price_locked`. Both lead to `plan_basket`, which re-quotes.
- **Lookup is outside the playbook.** It is read-only and commits nothing, so any agent may call it at any time; ordering still has to follow the playbook. Lookup returns availability as a status + "can you cover my quantity" (capped at the asked quantity), never the stock level.
- **Live pricing for recalled favourites.** Curated demo products with a real counterpart carry `aimoId` (the three lactose-free milks). In live mode `plan_basket` refreshes their price per L and availability from the mock API (one batch call each), so the brief's request is priced on live data while the golden scenarios stay repeatable offline. Each offer says `priceSource`.
- **The mock API has no order endpoint.** Orders are confirmed by the gateway's order book (`FixtureBackend.place_order`, reference `AIMO-SO-…`) and signed by the gateway; in production this is the ERP/webshop order API behind the adapter.
- **Labels.** Pack labels come from GS1 `packagingMarkedLabel` (temperature marks dropped) and are shown as certificates; their validity is not in the data, so they are treated as valid.
- **Organiser data stays out of git.** `gateway/data/aimo_products.json` is git-ignored (Junction-only data in a public repo); `make index` rebuilds it from `data_raw/`.
- **Keys are per process.** The JWKS changes on restart or demo reset; agents fetch it per run.
