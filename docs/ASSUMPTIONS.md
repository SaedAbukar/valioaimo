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
