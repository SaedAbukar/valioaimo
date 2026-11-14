"""MCP gives the same rails as REST: lookup, the enforced playbook, cited offers, and no way to approve."""
import json
import os

os.environ["AIMO_LIVE"] = "0"
os.environ["AIMO_AGENT_TOKEN"] = "demo-key-pohjola"
import asyncio  # noqa: E402

import gateway.mcp_server as m  # noqa: E402

BRIEF = "I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability."


def test_mcp_tool_set_covers_the_journey_and_has_no_approve_tool():
    names = {t.name for t in asyncio.run(m.mcp.list_tools())}
    assert {"discover_gateway", "whoami", "get_rules", "lookup_products", "get_price_availability", "start_session",
            "parse_request", "recall", "plan_basket", "check_basket", "place_order", "request_approval",
            "get_offer", "verify_offer", "get_order", "get_audit_log"} <= names
    assert not [n for n in names if "approve" in n and n != "request_approval"]


def test_mcp_brief_request_end_to_end():
    found = json.loads(m.lookup_products("lactose-free milk", 1000, "2026-11-16"))
    assert found["products"] and found["products"][0]["price"]["perUnit"] > 0
    assert json.loads(m.start_session("BUY-KOULU"))["status"] == 403  # bound to its own customer
    sid = json.loads(m.start_session())["sessionId"]
    assert json.loads(m._run(sid, "place_order", {}))["error"] == "step_not_allowed"
    for t, a in (("parse_request", {"text": BRIEF}), ("recall", {})):
        json.loads(m._run(sid, t, a))
    plan = json.loads(m._run(sid, "plan_basket", {}))["output"]
    assert json.loads(m._run(sid, "check_basket", {}))["output"]["decision"] in ("auto", "tell_me")
    json.loads(m._run(sid, "render_cards", {}))
    order = json.loads(m._run(sid, "place_order", {"offerIds": [o["offerId"] for o in plan["offers"]]}))["output"]
    got = json.loads(m.get_order(order["orderId"]))
    assert got["confirmationVerified"] and json.loads(m.verify_offer(plan["offers"][0]["offerId"]))["checks"]


def test_mcp_place_order_is_retry_safe_with_an_idempotency_key():
    m.GW.backend.reset()  # the earlier test bought the milk; start from full stock
    sid = json.loads(m.start_session())["sessionId"]
    for t, a in (("parse_request", {"text": BRIEF}), ("recall", {}), ("plan_basket", {}), ("check_basket", {}), ("render_cards", {})):
        out = json.loads(m._run(sid, t, a))
        if t == "plan_basket":
            ids = [o["offerId"] for o in out["output"]["offers"]]
    a = json.loads(m.call_tool(sid, "place_order", json.dumps({"offerIds": ids}), idempotencyKey="mcp-1"))
    assert "output" in a, a
    b = json.loads(m.call_tool(sid, "place_order", json.dumps({"offerIds": ids}), idempotencyKey="mcp-1"))
    assert a["output"]["orderId"] == b["output"]["orderId"] and b["idempotentReplay"]
