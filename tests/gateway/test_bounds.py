"""Task 20 (audit M2, M3, M4): validated input everywhere, bounded long-poll, eviction, incremental audit verify."""
import json
import os
import threading
import time

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402
from gateway.core import Gateway  # noqa: E402

AGENT = {"Authorization": "Bearer demo-key-pohjola"}


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


@pytest.mark.parametrize("path,body,field", [
    ("/v1/products/search", {"query": 5}, "query"),
    ("/v1/products/search", {"query": "milk", "limit": "lots"}, "limit"),
    ("/v1/products/search", {"query": "milk", "qtty": 5}, "qtty"),
    ("/v1/products/search", {}, "query"),
    ("/v1/products/price-availability", {"productIds": "465039"}, "productIds"),
    ("/v1/products/price-availability", {"productIds": ["1"] * 21}, "productIds"),
])
def test_lookup_bodies_are_validated_with_a_fix(c, path, body, field):
    r = c.post(path, json=body, headers=AGENT)
    assert r.status_code == 422 and r.json()["guard"] == "bad_input", r.json()
    assert r.json()["fix"]["example"] and field in json.dumps(r.json())


def test_mcp_malformed_args_and_filters_are_structured_422():
    os.environ["AIMO_LIVE"] = "0"
    import gateway.mcp_server as m
    sid = json.loads(m.start_session())["sessionId"]
    r = json.loads(m.call_tool(sid, "parse_request", "{not json"))
    assert r["status"] == 422 and r["guard"] == "bad_input" and r["fix"]["example"]
    r = json.loads(m.ask_insight("BUY-POHJOLA", "spend by month", '{"siteId": 5}'))
    assert r["status"] == 422 and r["guard"] == "bad_input"


def test_each_session_has_its_own_condition():
    gw = Gateway()
    assert gw.events.cond_for("A") is not gw.events.cond_for("B") and gw.events.cond_for("A") is gw.events.cond_for("A")


def test_long_poll_pool_is_bounded(monkeypatch):
    monkeypatch.setenv("AIMO_MAX_WAITERS", "1")
    c = TestClient(make_app(live=False))
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    nxt = c.get(f"/v1/sessions/{sid}/events", headers=AGENT).json()["next"]
    th = threading.Thread(target=lambda: c.get(f"/v1/sessions/{sid}/events?after={nxt}&wait=2", headers=AGENT))
    th.start()
    time.sleep(0.3)
    r = c.get(f"/v1/sessions/{sid}/events?after={nxt}&wait=2", headers=AGENT)
    assert r.status_code == 503 and int(r.headers["Retry-After"]) >= 1 and r.json()["fix"]
    assert c.get(f"/v1/sessions/{sid}/events?after=0", headers=AGENT).status_code == 200  # wait=0 never queues
    th.join()


def test_old_entries_are_evicted():
    gw = Gateway()
    gw.engine.idempotent("s|place_order", "k1", {}, lambda: {"x": 1})
    gw.events.emit("SES-1", "step.completed", {})
    gw.clock.advance(25 * 60)
    gw.engine.idempotent("s|place_order", "k2", {}, lambda: {"x": 2})
    assert "s|place_order|k1" not in gw.engine.idem and "s|place_order|k2" in gw.engine.idem
    e = gw.events.emit("SES-1", "step.completed", {})
    assert e["seq"] == 2 and [x["seq"] for x in gw.events.read("SES-1", 0)] == [2]


def test_api_cache_evicts_expired_rows():
    from gateway.adapter import AimoApiClient
    a = AimoApiClient("http://x.invalid", "k")
    t = [0.0]
    a.now = lambda: t[0]
    a._send = lambda path, body, timeout: {"products": [{"productId": p} for p in body["products"]]}
    a.prices(["1", "2"], "d")
    t[0] += a.TTL + 1
    a.prices(["3"], "d")
    assert {k[1] for k in a._cache} == {"3"}


def test_audit_verify_is_incremental():
    gw = Gateway()
    full = gw.audit.verify(full=True)
    v1 = gw.audit.verify()
    gw.audit.append(trace_id=None, actor="system:test", action="x")
    v2 = gw.audit.verify()
    assert v2["ok"] and v2["newlyChecked"] == 1 and v2["checked"] == full["checked"] + 1 and v1["ok"]
