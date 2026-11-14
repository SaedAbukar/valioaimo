# Roadmap

| Phase | Build | Exit criteria |
| --- | --- | --- |
| **MVP (now)** | Clickable self-contained page with the full experience (Event Autopilot, agent console, signed offers & trust checks, policy & approvals, preferences & compare, insights & recommendations, waste loop, audit, ops, how it works); Python reference core (planner, policy, trust, audit) with tests; 3NF data model | Judges complete S0–S8 on a phone; every decision explainable by rule id |
| **Hackathon prototype** | Wire the page to the gateway REST API (same JSON shapes); MCP server over the same handlers; adapter to the organisers' mock API (`AIMO_BASE_URL`, `AIMO_API_KEY`); SQLite → Postgres; real Web Speech capture in the hosted app | One external agent (e.g. Claude via MCP) orders against the mock API within a mandate |
| **Pilot (2–3 customers, 8 weeks)** | did:web keys in KMS; OPA policies; Valio Aimo-hosted approval page; delivery & invoice feedback from order systems; recipe KB per kitchen; data export/delete; monitoring | Autonomous rate ≥ 60 %, manual corrections ≤ 10 %, zero allergen incidents, approval p50 ≤ 10 min, event waste −20 % |
| **Production** | UCP conformance, certifier-issued VCs (L2), EPCIS traceability (L3), A2A seller agent for proactive offers, multi-site org hierarchies, SLAs, rate plans | Third-party agent vendors onboard self-service |

## Open questions for Valio Aimo mentors
1. Which systems own customer-specific prices and allocations, and can they produce a signed, time-boxed price commitment?
2. How is stock-by-date (inbound) exposed today, and at what freshness?
3. Are broken cases (packs) orderable for foodservice customers, and at what surcharge?
4. Who at a customer may sign a mandate — and do customers already have approval hierarchies we should mirror?
5. Which certifications can be verified at source (e.g. MSC chain-of-custody numbers)?
6. What delivery and consumption feedback could kitchens realistically give (one tap after events)?
7. Credit limits and kill switch: which team operates them, and what response time is expected?
8. Data sharing: which aggregate demand/waste signals are acceptable to show back to buyers?
