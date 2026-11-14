"""Task 14: MCP over Streamable HTTP at /mcp shares ONE Gateway with REST (approvals, stock, audit)."""
import json
import os
import threading
import time

from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402

AGENT = {"Authorization": "Bearer demo-key-pohjola"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
OVER = "I need 3,000 litres of lactose-free milk by Monday."
BRIEF = "I need 1,000 litres of lactose-free milk by Monday."


def mcp(c, name, args=None, token="demo-key-pohjola"):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}},
               headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return json.loads(res["content"][0]["text"])


def to_present(c, text):
    sid = mcp(c, "start_session")["sessionId"]
    mcp(c, "parse_request", {"sessionId": sid, "text": text})
    for t in ("recall", "plan_basket", "check_basket", "render_cards"):
        out = mcp(c, t, {"sessionId": sid})
        if t == "plan_basket":
            plan = out["output"]
    return sid, plan


def test_mcp_agent_is_approved_over_rest_and_woken():
    with TestClient(make_app(live=False)) as c:
        sid, plan = to_present(c, OVER)
        aid = mcp(c, "request_approval", {"sessionId": sid})["output"]["approval"]["approvalId"]
        assert [p["approvalId"] for p in c.get("/v1/approvals", headers=LAURA).json()["pending"]] == [aid]  # same inbox
        cursor = max(e["seq"] for e in mcp(c, "wait_for_update", {"sessionId": sid, "timeoutSeconds": 0})["events"])
        got = {}

        def waiter():
            t0 = time.perf_counter()
            got["r"] = mcp(c, "wait_for_update", {"sessionId": sid, "after": cursor, "timeoutSeconds": 5})
            got["s"] = time.perf_counter() - t0

        th = threading.Thread(target=waiter)
        th.start()
        time.sleep(0.2)
        assert c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=LAURA).status_code == 200
        th.join(6)
        assert got["s"] < 1.5 and any(e["type"] == "approval.decided" for e in got["r"]["events"])
        o = mcp(c, "place_order", {"sessionId": sid, "offerIds": [x["offerId"] for x in plan["offers"]]})["output"]
        assert o["approvedBy"] == "Laura Virtanen"
        assert c.get(f"/v1/orders/{o['orderId']}", headers=AGENT).json()["confirmationVerified"]  # REST sees the MCP order


def test_stock_is_shared_between_channels():
    with TestClient(make_app(live=False)) as c:
        gw = c.app.state.gw()
        sid, plan = to_present(c, BRIEF)
        gtin = plan["lines"][0]["gtin"]
        before = gw.backend.stock[gtin]
        mcp(c, "place_order", {"sessionId": sid, "offerIds": [x["offerId"] for x in plan["offers"]]})
        assert gw.backend.stock[gtin] < before
        r = c.post("/v1/products/search", json={"query": "lactose-free milk"}, headers=AGENT)
        assert r.status_code == 200
        assert any(e["action"] == "playbook.place_order" for e in c.get(f"/v1/audit?sessionId={sid}", headers=AGENT).json()["events"])


def test_mcp_http_needs_an_agent_credential():
    with TestClient(make_app(live=False)) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 401
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={**LAURA, "Accept": "application/json, text/event-stream"})
        assert r.status_code == 403
        # identity is per request: Kaari's agent cannot touch Pohjola's session
        sid = mcp(c, "start_session")["sessionId"]
        assert mcp(c, "parse_request", {"sessionId": sid, "text": BRIEF}, token="demo-key-kaari")["status"] == 403


def test_stdio_proxy_forwards_to_the_shared_gateway():
    from scripts.mcp_stdio_proxy import forward
    with TestClient(make_app(live=False)) as c:
        def post(msg):
            r = c.post("/mcp", json=msg, headers={**AGENT, "Accept": "application/json, text/event-stream"})
            return r.status_code, r.text
        init = json.loads(forward(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}), post))
        assert init["result"]["serverInfo"]["name"] == "aimo-agent-gateway"
        assert forward(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), post) is None
        out = json.loads(forward(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                             "params": {"name": "start_session", "arguments": {}}}), post))
        sid = json.loads(out["result"]["content"][0]["text"])["sessionId"]
        assert c.get(f"/v1/sessions/{sid}", headers=AGENT).status_code == 200  # the REST side sees it
