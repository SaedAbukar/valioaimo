"""One tool manifest for any agent: the whole journey from the first prompt to the order
(order playbook) and from a question to a chart (insight playbook). Served at GET /v1/tools
and used to register the MCP tools."""
from __future__ import annotations

from .analytics.engine import insight_playbook
from .playbook.engine import playbook


FREE = [  # read-only or trust tools, usable at any time (no commitment, so outside the playbook)
    ("discover_gateway", "GET /.well-known/ucp", "Find services, capabilities, keys, rules and the playbook."),
    ("whoami", "GET /v1/mandate", "The customer account this agent acts for and its signed authority (mandate)."),
    ("get_rules", "GET /v1/rules", "What the agent decides alone, what needs a named human, what is never allowed."),
    ("lookup_products", "POST /v1/products/search", "Search products with price and availability for a need-by date."),
    ("get_price_availability", "POST /v1/products/price-availability", "Price and availability for known product ids."),
    ("get_offer", "GET /v1/offers/{offerId}", "A signed, time-limited offer (vc+jwt)."),
    ("verify_offer", "POST /v1/offers/{offerId}/verify", "Six trust checks on an offer."),
    ("get_order", "GET /v1/orders/{orderId}", "An order with its signed confirmation."),
    ("get_audit_log", "GET /v1/audit", "This buyer's hash-chained audit log."),
]


def tools() -> dict:
    out = [{"name": n, "playbook": None, "step": "any", "n": None, "description": d, "rest": r} for n, r, d in FREE]
    op = playbook()
    for st in op["steps"]:
        for t in st["tools"]:
            out.append({"name": t, "playbook": "order", "step": st["id"], "n": st["n"], "description": st["does"],
                        "rest": "POST /v1/sessions" if t == "start_session" else f"POST /v1/sessions/{{id}}/tools/{t}"})
    ip = insight_playbook()
    for st in ip["steps"]:
        for t in st["tools"]:
            inp = st.get("input")
            out.append({"name": t, "playbook": "insight", "step": st["id"], "n": st["n"], "description": st["does"],
                        "input": inp.get(t, inp) if isinstance(inp, dict) and t in inp else inp,
                        "rest": "POST /v1/insights/sessions" if t == "start_analysis" else f"POST /v1/insights/sessions/{{id}}/tools/{t}"})
    return {"playbooks": {"order": op["version"], "insight": ip["version"]}, "tools": out,
            "howTo": ["Look up any time: lookup_products / get_price_availability (read-only).",
                      "Order: start_session -> parse_request -> recall -> (request_offers only for gaps) -> plan_basket -> "
                      "check_basket -> render_cards -> place_order {offerIds} | request_approval -> (named human approves) -> place_order -> record_usage.",
                      "Insight: start_analysis -> describe_data -> run_query -> suggest_chart -> build_chart -> explain_result.",
                      "Every response lists next_allowed_tools; errors carry a 'fix' to follow."]}
