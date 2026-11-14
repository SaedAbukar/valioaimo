"""Task 21 (audit M5, M6, L1-L6): one authz module for REST and MCP, a Backend protocol, domain logic out of the
HTTP layer, no hidden side effects, configured base URL, idempotent start_session, MCP protocol-level errors."""
import json
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway import authz  # noqa: E402
from gateway.__main__ import make_app  # noqa: E402
from gateway.adapter import Backend, FixtureBackend  # noqa: E402
from gateway.core import Gateway  # noqa: E402

AGENT = {"Authorization": "Bearer demo-key-pohjola"}
BRIEF = "I need 1,000 litres of lactose-free milk by Monday."


def mcp(c, name, args=None, token="demo-key-pohjola"):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}},
               headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
    return r.json()["result"]


def test_rest_and_mcp_share_one_authz_for_orders():
    with TestClient(make_app(live=False)) as c:
        sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
        for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards"):
            r = c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": BRIEF} if t == "parse_request" else {}, headers=AGENT)
            if t == "plan_basket":
                ids = [o["offerId"] for o in r.json()["output"]["offers"]]
        oid = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids}, headers=AGENT).json()["output"]["orderId"]
        for token, ok in (("demo-key-pohjola", True), ("demo-key-kaari", False)):
            rest = c.get(f"/v1/orders/{oid}", headers={"Authorization": f"Bearer {token}"}).status_code
            res = mcp(c, "get_order", {"orderId": oid}, token)
            assert (rest == 200) == ok and (not res.get("isError")) == ok, (token, rest, res)
        assert authz.can_read_order


def test_fixture_backend_is_a_backend():
    assert isinstance(FixtureBackend(Gateway().clock), Backend)


def test_insight_engine_exists_without_an_analyst():
    gw = Gateway()
    assert gw.insights.call(None, "start_analysis", {"buyerId": "BUY-POHJOLA"})["sessionId"]


def test_inbox_and_audit_filtering_live_in_domain_modules():
    from gateway.playbook import approvals
    from gateway import audit
    assert callable(approvals.inbox_for) and callable(audit.AuditLedger.events_for)


def test_discover_gateway_uses_the_configured_base_url(monkeypatch):
    monkeypatch.setenv("AIMO_PUBLIC_URL", "https://gateway.example.test")
    with TestClient(make_app(live=False)) as c:
        res = mcp(c, "discover_gateway")
        assert "https://gateway.example.test/openapi.json" in res["content"][0]["text"]


def test_start_session_accepts_an_idempotency_key():
    c = TestClient(make_app(live=False))
    h = {**AGENT, "Idempotency-Key": "start-1"}
    a = c.post("/v1/sessions", json={}, headers=h).json()["sessionId"]
    r = c.post("/v1/sessions", json={}, headers=h)
    assert r.json()["sessionId"] == a and r.headers.get("Idempotent-Replay") == "true"
    assert len(c.app.state.gw().engine.sessions) == 1


def test_mcp_errors_are_protocol_level():
    with TestClient(make_app(live=False)) as c:
        sid = json.loads(mcp(c, "start_session")["content"][0]["text"])["sessionId"]
        res = mcp(c, "place_order", {"sessionId": sid, "offerIds": ["x"]})
        assert res["isError"] is True
        body = json.loads(res["content"][0]["text"])
        assert body["error"] == "step_not_allowed" and body["next_allowed_tools"]
        ok = mcp(c, "parse_request", {"sessionId": sid, "text": BRIEF})
        assert not ok.get("isError")
