"""v5 hardening: no oversell, idempotency, typed inputs, push events, restart, rate limits."""
import os
import threading

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
os.environ.setdefault("AIMO_RATE_PER_MIN", "100000")
from gateway.__main__ import make_app  # noqa: E402
from gateway.core import Gateway  # noqa: E402
from gateway.playbook.engine import StepNotAllowed  # noqa: E402
from gateway.playbook.tools import offer_ids  # noqa: E402
from gateway.util import s2d  # noqa: E402

BRIEF = ("I need 1,000 litres of lactose-free milk by Monday. "
         "Find an option that meets our requirements based on price and availability.")
AGENT = {"Authorization": "Bearer demo-key-pohjola"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
TO_PRESENT = ("parse_request", "recall", "plan_basket", "check_basket", "render_cards")


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def in_process_to_present(gw, text=BRIEF):
    sid = gw.engine.call(None, "start_session", {"buyerId": "BUY-POHJOLA"})["sessionId"]
    for t in TO_PRESENT:
        gw.engine.call(sid, t, {"text": text} if t == "parse_request" else {})
    return sid, gw.engine.sessions[sid]


def http_to_present(c, text=BRIEF, headers=AGENT):
    sid = c.post("/v1/sessions", json={}, headers=headers).json()["sessionId"]
    out = {}
    for t in TO_PRESENT:
        r = c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": text} if t == "parse_request" else {}, headers=headers)
        assert r.status_code == 200, (t, r.json())
        out[t] = r.json()["output"]
    return sid, out


# ---------------------------------------------------------------- Task 1: no overselling
def test_place_order_rechecks_stock():
    gw = Gateway()
    sid, s = in_process_to_present(gw)
    gtin = s["data"]["plan"]["lines"][0]["gtin"]
    gw.backend.set_stock(gtin, 100)
    gw.backend.inbound[gtin] = []
    gw.backend.base_stock[gtin] = 0
    with pytest.raises(StepNotAllowed) as e:
        gw.engine.call(sid, "place_order", {"offerIds": offer_ids(s)})
    assert e.value.extra["guard"] == "stock_changed"
    assert e.value.extra["next_allowed_tools"] == ["plan_basket"] and e.value.extra["shortfall"]
    assert not gw.backend.orders


def test_concurrent_orders_never_oversell(c):
    n = 8
    g = c.app.state.gw()
    plans = [http_to_present(c) for _ in range(n)]
    start = {}
    for _, out in plans:
        for l in out["plan_basket"]["lines"]:
            start.setdefault(l["gtin"], g.backend.available_by(l["gtin"], s2d(l["deliveryDate"])))
    results = [None] * n
    barrier = threading.Barrier(n)

    def go(i):
        sid, out = plans[i]
        barrier.wait()
        results[i] = c.post(f"/v1/sessions/{sid}/tools/place_order",
                            json={"offerIds": [o["offerId"] for o in out["plan_basket"]["offers"]]}, headers=AGENT)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ordered: dict[str, float] = {}
    for o in g.backend.orders:
        for ln in o["lines"]:
            ordered[ln["gtin"]] = ordered.get(ln["gtin"], 0) + ln["qty"]
    for gtin, q in ordered.items():
        assert q <= start[gtin] + 1e-9, (gtin, q, start[gtin])
    losers = [r for r in results if r.status_code != 200]
    assert losers, "8 x 1,000 L must exceed the stock of the planned product"
    assert all(r.status_code == 409 and r.json()["guard"] == "stock_changed" for r in losers)
    assert len(g.backend.orders) == n - len(losers)


# ---------------------------------------------------------------- Task 2: idempotency keys
def test_retried_place_order_returns_same_order(c):
    sid, out = http_to_present(c)
    ids = [o["offerId"] for o in out["plan_basket"]["offers"]]
    h = {**AGENT, "Idempotency-Key": "order-7f3a"}
    r1 = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids}, headers=h)
    r2 = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids}, headers=h)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["output"]["orderId"] == r2.json()["output"]["orderId"]
    assert r2.headers.get("Idempotent-Replay") == "true" and "Idempotent-Replay" not in r1.headers
    assert len(c.app.state.gw().backend.orders) == 1


def test_idempotency_key_in_body_works_like_the_header(c):
    sid, out = http_to_present(c)
    body = {"offerIds": [o["offerId"] for o in out["plan_basket"]["offers"]], "idempotencyKey": "k-body"}
    r1 = c.post(f"/v1/sessions/{sid}/tools/place_order", json=body, headers=AGENT)
    r2 = c.post(f"/v1/sessions/{sid}/tools/place_order", json=body, headers=AGENT)
    assert r1.json()["output"]["orderId"] == r2.json()["output"]["orderId"] and len(c.app.state.gw().backend.orders) == 1


def test_same_key_different_body_is_422(c):
    sid, out = http_to_present(c)
    ids = [o["offerId"] for o in out["plan_basket"]["offers"]]
    h = {**AGENT, "Idempotency-Key": "order-1"}
    assert c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids}, headers=h).status_code == 200
    r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids + ["OF-OTHER"]}, headers=h)
    assert r.status_code == 422 and r.json()["guard"] == "idempotency_conflict" and r.json()["fix"]


def test_approval_decision_is_idempotent(c):
    sid, _ = http_to_present(c, BRIEF.replace("1,000", "3,000"))
    aid = c.post(f"/v1/sessions/{sid}/tools/request_approval", json={}, headers=AGENT).json()["output"]["approval"]["approvalId"]
    h = {**LAURA, "Idempotency-Key": "decide-1"}
    r1 = c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=h)
    r2 = c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=h)
    assert r1.status_code == r2.status_code == 200 and r1.json()["approval"] == r2.json()["approval"]
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert c.post(f"/v1/approvals/{aid}", json={"ok": False}, headers=h).status_code == 422
    assert c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=LAURA).status_code == 422  # no key: already decided


# ---------------------------------------------------------------- Task 3: typed tool inputs
from gateway.analytics.engine import insight_playbook  # noqa: E402
from gateway.playbook.engine import playbook, public_playbook  # noqa: E402


def _all_inputs():
    pb, ip = playbook(), insight_playbook()
    return [(t, pb.get("inputs", {}).get(t)) for t in pb["toolStep"]] + [(t, ip.get("inputs", {}).get(t)) for t in ip["toolStep"]]


@pytest.mark.parametrize("tool,schema", _all_inputs(), ids=[t for t, _ in _all_inputs()])
def test_every_tool_has_an_input_schema(tool, schema):
    from jsonschema import Draft202012Validator
    assert schema, f"{tool} has no input schema"
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert schema["examples"] and all(Draft202012Validator(schema).is_valid(e) for e in schema["examples"])
    assert all(p.get("description") for p in schema.get("properties", {}).values()), tool


def test_playbooks_are_1_1_0():
    assert public_playbook()["version"] == "1.1.0" and insight_playbook()["version"] == "1.1.0"


def test_bad_input_has_a_fix_with_an_example(c):
    sid, _ = http_to_present(c)
    r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerId": "x"}, headers=AGENT)
    assert r.status_code == 422 and r.json()["guard"] == "bad_input"
    assert r.json()["fix"]["example"]["offerIds"] and r.json()["fix"]["expected"]
    assert "offerId" in r.json()["message"]


def test_tool_manifest_lists_input_schemas(c):
    tools = {t["name"]: t for t in c.get("/v1/tools").json()["tools"]}
    assert tools["place_order"]["inputSchema"]["properties"]["offerIds"]
    assert tools["run_query"]["inputSchema"]["properties"]["measures"]


def _correctable(r):
    b = r.json()
    return b.get("fix") or b.get("next_allowed_tools")


def test_every_4xx_in_rails_has_fix_or_next_allowed_tools(c):
    bad = []
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    u = f"/v1/sessions/{sid}/tools/"
    cases = [("place_order", {}), ("parse_request", {}), ("parse_request", {"txt": "milk"}), ("no_such_tool", {}),
             ("parse_request", {"text": 42})]
    for tool, a in cases:
        r = c.post(u + tool, json=a, headers=AGENT)
        if r.status_code >= 400 and not _correctable(r):
            bad.append((tool, a, r.status_code, r.json()))
    sid, out = http_to_present(c)
    u = f"/v1/sessions/{sid}/tools/"
    ids = [o["offerId"] for o in out["plan_basket"]["offers"]]
    for tool, a in [("place_order", {}), ("place_order", {"offerIds": ids, "unitPrice": 1}), ("place_order", {"offerIds": ["OF-X"]}),
                    ("ask_user", {}), ("get_product", {"productId": "nope"}), ("record_usage", {"entries": {}})]:
        r = c.post(u + tool, json=a, headers=AGENT)
        if r.status_code >= 400 and not _correctable(r):
            bad.append((tool, a, r.status_code, r.json()))
    ana = c.post("/v1/insights/sessions", json={"buyerId": "BUY-POHJOLA"}, headers=AGENT).json()["output"]["sessionId"]
    for tool, a in [("run_query", {}), ("describe_data", {"x": 1}), ("get_values", {"field": "nope"}),
                    ("build_chart", {"type": "line"})]:
        r = c.post(f"/v1/insights/sessions/{ana}/tools/{tool}", json=a, headers=AGENT)
        if r.status_code >= 400 and not _correctable(r):
            bad.append((tool, a, r.status_code, r.json()))
    assert not bad, bad


# ---------------------------------------------------------------- Task 4: push updates
def test_agent_is_woken_by_approval(c):
    import time
    sid, _ = http_to_present(c, BRIEF.replace("1,000", "3,000"))
    aid = c.post(f"/v1/sessions/{sid}/tools/request_approval", json={}, headers=AGENT).json()["output"]["approval"]["approvalId"]
    first = c.get(f"/v1/sessions/{sid}/events", headers=AGENT).json()
    types = [e["type"] for e in first["events"]]
    assert {"step.completed", "decision.made", "approval.requested"} <= set(types)
    got = {}

    def waiter():
        t0 = time.perf_counter()
        got["r"] = c.get(f"/v1/sessions/{sid}/events?after={first['next']}&wait=5", headers=AGENT).json()
        got["s"] = time.perf_counter() - t0

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.2)
    c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=LAURA)
    th.join(6)
    assert got["s"] < 1.0
    ev = [e for e in got["r"]["events"] if e["type"] == "approval.decided"][0]
    assert ev["data"]["status"] == "approved" and "place_order" in ev["data"]["next_allowed_tools"]
    assert got["r"]["next"] > first["next"]


def test_events_are_own_session_only_and_wait_is_capped(c):
    sid, _ = http_to_present(c)
    assert c.get(f"/v1/sessions/{sid}/events", headers={"Authorization": "Bearer demo-key-kaarela"}).status_code == 403
    r = c.get(f"/v1/sessions/{sid}/events?wait=99", headers=AGENT)
    assert r.status_code == 422 and r.json()["fix"]
    assert "/v1/sessions/{sessionId}/events" in c.get("/openapi.json").json()["paths"]
    assert "wait_for_update" in {t["name"] for t in c.get("/v1/tools").json()["tools"]}


def test_offer_expiring_event_is_emitted_on_read():
    gw = Gateway()
    sid, s = in_process_to_present(gw)
    gw.clock.advance(14)
    n_offers = len(s["data"]["plan"]["offers"])
    assert len([e for e in gw.events.read(sid, 0) if e["type"] == "offer.expiring"]) == n_offers
    assert len([e for e in gw.events.read(sid, 0) if e["type"] == "offer.expiring"]) == n_offers  # once per offer
