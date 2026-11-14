# Progress — Aimo Agent Gateway MVP

## Published
- Artifact: https://claude.ai/artifact/4PYHao2tm2PPmvCVTekwTp — slug `1b710f3e-6284-4874-8781-8bbf027c6d73`, version `1794608519-366b` (MVP v1).
  Republish: `python3 ui/build.py` then publish_files with slug + base_version (latest version above).

## Done
- Python reference core (gateway/): catalog (97 products, GTIN-14), need resolution, preferences, planner, policy (rules.yaml R0–R14, V1–V3), trust (VC 2.0 + JWS ES256 offers, 6 checks), audit hash chain, signals, thin server `python -m gateway`. Tests: `pytest -q tests` → 27 passed.
- Client-side engine (ui/src/engine.js, flows.js) mirroring the core + seeded 12-week history (3 buyers), Event Autopilot, approvals, outcome store, recommendations, waste/usage, ops, outcome labels, metric definitions, day context.
- UI (ui/src/app.js, app2.js, styles.css, index.html) — 10 screens + guided demo (13 steps) + data model view; build `python3 ui/build.py` → ui/dist/index.html. Inline SVG icons (react-icons md paths, offline).
- Data model v1.1 copied to docs/data-model/.
- Screenshots: docs/screenshots (10 screens × 390/1280 × light/dark + 5 interaction shots).

- Docs written (README, ARCHITECTURE, UX, PROBLEM_SOLUTION, EVENT_AUTOPILOT, DATA_MODEL, API, STANDARDS, ROADMAP, ASSUMPTIONS); Mermaid validated with mmdc.
- Zip: /home/claude/aimo-agent-gateway.zip

## Next
- Done. Optional polish only.

## Decisions
- Demo clock anchored Fri 13 Nov 2026 09:00 EET for repeatable scenes.
- Event budget (hotel) €3,300 per event / €26 per guest so 180 guests → auto-order (NOTIFY) and 200 → one approval.
- Backend kept as thin reference skeleton per priority change; MVP page is the deliverable.

## DESIGN DIRECTION — user feedback 2026-11-14 00:40 (TOP PRIORITY for next refinement run)
The UI/UX is too bloated, too "AI-looking" and messy. Next run must:
- Clean and simplify as much as possible: minimal design following Material 3 (fewer screens/elements, one primary action per screen, generous whitespace, no decorative gradients/glows/emoji/badges overload, short copy, progressive disclosure for detail).
- Palette: three main colours only — turquoise blue (primary), white (surface), sky blue (secondary/container). Same three-colour identity in dark mode (dark surface tuned to the same hues; turquoise and sky blue adapted for contrast). Semantic status colours only where strictly needed (block/approve), muted.
- Keep all requirements reachable, but behind cleaner navigation (consider: Autopilot, Orders, Insights, Settings + "How it works").

## Redesign run (2026-11-14 03:55 →)
- v1 UI backed up to /home/claude/scratch/v1ui (not in repo).
- Plan: new ui.js + styles.css; IA = Autopilot · Orders · Insights · Settings; one input handles events and plain orders; detail in bottom sheets.
- 05:22 published redesign v2 → version `1794626575-65a7` (base for next publish).
  Decisions: tokens in styles.css (turquoise #087a85 / white / sky #dcf0fa + #87ceeb; dark #0e1a1d surface, #6fd3dc primary); single font Figtree;
  one input handles events AND plain orders (units L/kg → agent order; else event brief); detail moved into bottom sheets;
  approvals live at top of Orders; catalog explorer removed (offers open from product rows); guided overlay replaced by Settings › Demo scenarios;
  planner: relaxed (other-variant) products never outrank strict ones (bug fix, also in planner.py); hotel monthly budget €45,000 so R3 doesn't swamp demo.
  Old UI kept in /home/claude/scratch/v1ui (app.js/app2.js removed from build).
- 05:44 published polish 1 → version `1794627866-cca2`.
- 06:47 published polish 2 → version `1794631623-5e82` (metrics list, reconcile layout, org-scoped result card, snackbar cleared by sheets).
- 06:52 published polish 3–5 → latest version `1794631926-c9a6`: sentence-case chips, Esc closes menus, quieter usage report (labels only where waste/shortage), textarea aria-label, boot error state.
- Docs: UX.md rewritten for v2 (tokens, IA, components, states, a11y); README/PROBLEM_SOLUTION locations updated; 65 new screenshots in docs/screenshots (11 screens + 6 sheets × 390/1280 × light/dark).
- Next (if more time): optional desktop two-pane Autopilot; focus return after closing sheets.
- 06:54 published polish 6 → version `1794632039-db5c`: Autopilot two panes ≥1100px (summary | detail list), focus returns after sheets close, sentence-case rule rows; screenshots regenerated.
- 06:55 published polish 7 → version `1794632084-103a`: mobile architecture lanes wrap, data-model entity scrolls into view.
- 06:56 published polish 8 → latest version `1794632184-da18`.
- 07:03 focused pass published → version `1794632620-560a`:
  1. Insights chart: y-axis labels (0/50/100%), x labels end at "This week" (to 13 Nov); KPI tiles say "4-week avg" (waste "Last 12 weeks") so they don't contradict the weekly end value.
  2. Orders badge uses primary turquoise, not red.
  3. Focus trap in sheets (Tab/Shift+Tab cycle, Esc closes, focus returns to opener).
  4. Finnish parser: "lauantaina 21.11.", "ensi perjantaina", "huomenna", hengelle/henkilölle/vieraalle, vegaani(a), gluteeniton/-tonta, laktoositon/-tonta, keliaakikko, pähkinä-/kala-allergia(kko); brief gets lang 'fi' and the card shows "la 21.11. · 120 hengelle · noutopöytä", menu shows the Finnish dish word. Tests: tests/js/parser.test.js (6 cases, EN+FI) run via pytest (tests/test_js_parser.py) → 28 passed.
  5. Phone Autopilot: after planning the input collapses to a one-line field (tap to edit); card numbers + status/order/primary action above the fold at 390×844.
  6. Bug: event card lost its order/usage rows after reconciliation; now shows "Done · usage recorded". 13 scenarios re-run OK; 65 screenshots regenerated.
