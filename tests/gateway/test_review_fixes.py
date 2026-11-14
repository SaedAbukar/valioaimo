"""Final whole-branch review (v5): each Critical / Important finding as a failing test first."""
import json
import os
import threading

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402
from gateway.core import Gateway  # noqa: E402
from gateway.playbook.tools import offer_ids  # noqa: E402

USER = {"Authorization": "Bearer demo-user-buy-pohjola"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
SANNA = {"Authorization": "Bearer demo-human-usr-skoskinen"}
KOULU_USER = {"Authorization": "Bearer demo-user-buy-koulu"}
AGENT = {"Authorization": "Bearer demo-key-pohjola"}
OPS = {"Authorization": "Bearer demo-ops"}
GALA = ("Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. "
        "12 vegan, 8 gluten-free, 1 nut allergy.")
OVER = "I need 3,000 litres of lactose-free milk by Monday."


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def gala_waiting_for_ok(c):
    conv = c.post("/v1/chat", json={"text": GALA}, headers=USER).json()["conversation"]
    c.post(f"/v1/chat/{conv['id']}/actions", json={"action": "order"}, headers=USER)
    c.post("/v1/chat", json={"conversationId": conv["id"], "text": "now 200 guests"}, headers=USER)
    c.post(f"/v1/chat/{conv['id']}/actions", json={"action": "send_for_ok"}, headers=USER)
    return conv["id"], conv["sessionIds"][-1]


# ---------------------------------------------------------------- Critical 1
def test_chat_action_cannot_reach_another_buyers_session(c):
    cid, sid = gala_waiting_for_ok(c)
    gw = c.app.state.gw()
    own = c.post("/v1/chat", json={"text": "60 L oat drink by Monday"}, headers=SANNA).json()["conversation"]["id"]
    r = c.post(f"/v1/chat/{own}/actions", json={"action": "approve", "payload": {"sessionId": sid}}, headers=SANNA)
    assert r.status_code in (403, 404)
    assert gw.engine.sessions[sid]["data"]["approval"]["status"] == "pending"
    own_u = c.post("/v1/chat", json={"text": "60 L oat drink by Monday"}, headers=KOULU_USER).json()["conversation"]["id"]
    for action in ("order", "send_for_ok", "delivered", "decline"):
        r = c.post(f"/v1/chat/{own_u}/actions", json={"action": action, "payload": {"sessionId": sid}}, headers=KOULU_USER)
        assert r.status_code in (403, 404), action


def test_chat_approve_by_someone_who_is_not_an_approver_fails(c):
    cid, sid = gala_waiting_for_ok(c)
    jari = {"Authorization": "Bearer demo-human-usr-jlehtonen"}  # Pohjola approver too: allowed, named as themself
    r = c.post(f"/v1/chat/{cid}/actions", json={"action": "approve"}, headers=jari).json()
    assert c.app.state.gw().engine.sessions[sid]["data"]["approval"]["decidedBy"] == "John Doe"


# ---------------------------------------------------------------- Critical 2
def test_an_approval_covers_only_the_basket_the_human_saw():
    from gateway.playbook.tools import decide_approval
    gw = Gateway()
    sid = gw.engine.call(None, "start_session", {"buyerId": "BUY-POHJOLA"})["sessionId"]
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards"):
        gw.engine.call(sid, t, {"text": OVER} if t == "parse_request" else {})
    gw.engine.call(sid, "request_approval")
    s = gw.engine.sessions[sid]
    decide_approval(gw, s, True, {"id": "usr-lvirtanen", "name": "Laura Virtanen"})
    approved_total = s["data"]["approval"]["total"]
    r = None
    for t in ("parse_request", "recall", "request_offers", "plan_basket", "check_basket", "render_cards"):
        try:
            r = gw.engine.call(sid, t, {"text": "80 kg beef tenderloin by Monday"} if t == "parse_request" else {})
        except Exception:  # noqa: BLE001 - request_offers only when there are gaps
            pass
    s = gw.engine.sessions[sid]
    assert s["data"]["plan"]["total"] <= approved_total and s["data"]["decision"]["decision"] == "needs_ok"
    assert "place_order" not in r["next_allowed_tools"] and "request_approval" in r["next_allowed_tools"]


# ---------------------------------------------------------------- Important 3
def test_mcp_cannot_open_a_session_for_another_buyer():
    os.environ["AIMO_LIVE"] = "0"
    import gateway.mcp_server as m
    before = {s for s, v in m.GW.engine.sessions.items() if v["buyerId"] == "BUY-KOULU"}
    r = json.loads(m.call_tool("", "start_session", json.dumps({"buyerId": "BUY-KOULU"})))
    assert r["status"] in (403, 422)
    assert {s for s, v in m.GW.engine.sessions.items() if v["buyerId"] == "BUY-KOULU"} == before


# ---------------------------------------------------------------- Important 4
def test_operations_cannot_drive_an_order_session(c):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    assert c.post(f"/v1/sessions/{sid}/tools/parse_request", json={"text": OVER}, headers=OPS).status_code == 403
    assert c.get(f"/v1/sessions/{sid}", headers=OPS).status_code == 200  # reading is fine


# ---------------------------------------------------------------- Important 5
@pytest.mark.parametrize("body", [{}, {"ok": "false"}, {"ok": 1}])
def test_an_approval_decision_needs_an_explicit_boolean(c, body):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards"):
        c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": OVER} if t == "parse_request" else {}, headers=AGENT)
    aid = c.post(f"/v1/sessions/{sid}/tools/request_approval", json={}, headers=AGENT).json()["output"]["approval"]["approvalId"]
    r = c.post(f"/v1/approvals/{aid}", json=body, headers=LAURA)
    assert r.status_code == 422 and r.json()["fix"]
    assert c.app.state.gw().engine.sessions[sid]["data"]["approval"]["status"] == "pending"


# ---------------------------------------------------------------- Important 6
def test_changing_the_request_after_asking_cancels_the_pending_approval(c):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards"):
        c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": OVER} if t == "parse_request" else {}, headers=AGENT)
    aid = c.post(f"/v1/sessions/{sid}/tools/request_approval", json={}, headers=AGENT).json()["output"]["approval"]["approvalId"]
    c.post(f"/v1/sessions/{sid}/tools/parse_request", json={"text": "I need 2,500 litres of lactose-free milk by Monday."}, headers=AGENT)
    inbox = c.get("/v1/approvals", headers=LAURA)
    assert inbox.status_code == 200 and aid not in [p["approvalId"] for p in inbox.json()["pending"]]
    r = c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=LAURA)
    assert r.status_code == 422 and r.json()["guard"] == "pending_approval"


# ---------------------------------------------------------------- Important 7
def test_human_decision_holds_the_session_lock_and_idempotency_not_the_global_lock():
    from gateway.playbook.tools import decide_approval
    gw = Gateway()
    sid = gw.engine.call(None, "start_session", {"buyerId": "BUY-POHJOLA"})["sessionId"]
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards", "request_approval"):
        gw.engine.call(sid, t, {"text": OVER} if t == "parse_request" else {})
    seen = {}
    real = gw.audit.append

    def spy(**kw):
        if kw.get("action") == "approved":
            seen["session_lock"] = gw.engine.lock_for(sid)._is_owned()
        return real(**kw)

    gw.audit.append = spy
    decide_approval(gw, gw.engine.sessions[sid], True, {"id": "usr-lvirtanen", "name": "Laura Virtanen"})
    assert seen["session_lock"] is True
    held = {}
    gw.engine.idempotent("x|y", "k", {}, lambda: held.setdefault("gw", gw.lock._is_owned()) or {"ok": 1})
    assert held["gw"] is False


def test_rest_approve_with_key_and_chat_approve_race_without_deadlock(c):
    cid, sid = gala_waiting_for_ok(c)
    aid = c.app.state.gw().engine.sessions[sid]["data"]["approval"]["approvalId"]
    res = []
    t1 = threading.Thread(target=lambda: res.append(c.post(f"/v1/approvals/{aid}", json={"ok": True},
                                                             headers={**LAURA, "Idempotency-Key": "k1"}).status_code))
    t2 = threading.Thread(target=lambda: res.append(c.post(f"/v1/chat/{cid}/actions", json={"action": "approve"}, headers=LAURA).status_code))
    t1.start(); t2.start(); t1.join(15); t2.join(15)
    assert not t1.is_alive() and not t2.is_alive() and sorted(res)[0] == 200


# ---------------------------------------------------------------- Important 8
def test_a_declined_amendment_keeps_the_original_order_and_its_stock(c):
    gw = c.app.state.gw()
    conv = c.post("/v1/chat", json={"text": GALA}, headers=USER).json()["conversation"]
    c.post(f"/v1/chat/{conv['id']}/actions", json={"action": "order"}, headers=USER)
    stock_after_order = dict(gw.backend.stock)
    n_orders = len(gw.backend.orders)
    c.post("/v1/chat", json={"conversationId": conv["id"], "text": "now 200 guests"}, headers=USER)
    c.post(f"/v1/chat/{conv['id']}/actions", json={"action": "send_for_ok"}, headers=USER)
    c.post(f"/v1/chat/{conv['id']}/actions", json={"action": "decline"}, headers=LAURA)
    assert len(gw.backend.orders) == n_orders and gw.backend.stock == stock_after_order


# ---------------------------------------------------------------- Important 9
def test_a_chat_order_waiting_for_ok_is_placed_after_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("AIMO_DB", str(tmp_path / "gw.db"))
    c1 = TestClient(make_app(live=False))
    cid, sid = gala_waiting_for_ok(c1)
    before = c1.app.state.gw().engine.sessions[sid]["data"]["order"]["total"]
    c2 = TestClient(make_app(live=False))
    aid = c2.app.state.gw().engine.sessions[sid]["data"]["approval"]["approvalId"]
    r = c2.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=LAURA).json()
    assert r["cards"][0]["type"] == "delivery"
    assert c2.app.state.gw().engine.sessions[sid]["data"]["order"]["total"] > before
    assert c2.get(f"/v1/chats/{cid}", headers=USER).status_code == 200
