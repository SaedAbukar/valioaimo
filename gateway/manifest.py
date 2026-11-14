"""One tool manifest for any agent: the whole journey from the first prompt to the order
(order playbook) and from a question to a chart (insight playbook). Served at GET /v1/tools
and used to register the MCP tools."""
from __future__ import annotations

from .analytics.engine import insight_playbook
from .playbook.engine import playbook


def tools() -> dict:
    out = []
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
            "howTo": ["Order: start_session -> parse_request -> recall -> (request_offers only for gaps) -> plan_basket -> "
                      "check_basket -> render_cards -> place_order | request_approval -> record_usage.",
                      "Insight: start_analysis -> describe_data -> run_query -> suggest_chart -> build_chart -> explain_result.",
                      "Every response lists next_allowed_tools; errors carry a 'fix' to follow."]}
