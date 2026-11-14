"""Task 15 (audit C2, C3): chef-app routes need a buyer credential, chat approvals need the approver's own
credential, demo tokens only in demo mode, constant-time token comparison."""
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway import auth  # noqa: E402
from gateway.__main__ import make_app  # noqa: E402

USER = {"Authorization": "Bearer demo-user-buy-pohjola"}
OTHER_USER = {"Authorization": "Bearer demo-user-buy-koulu"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
AGENT = {"Authorization": "Bearer demo-key-pohjola"}
OPS = {"Authorization": "Bearer demo-ops"}
GALA = ("Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. "
        "12 vegan, 8 gluten-free, 1 nut allergy.")

READS = ["/v1/board?buyerId=BUY-POHJOLA", "/v1/chats?buyerId=BUY-POHJOLA", "/v1/insights?buyerId=BUY-POHJOLA",
         "/v1/settings?buyerId=BUY-POHJOLA", "/v1/orders/history?buyerId=BUY-POHJOLA", "/v1/kitchens?buyerId=BUY-POHJOLA",
         "/v1/insights/wrapped?buyerId=BUY-POHJOLA"]


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


@pytest.mark.parametrize("path", READS)
def test_chef_app_reads_need_the_buyers_credential(c, path):
    assert c.get(path).status_code == 401
    assert c.get(path, headers=OTHER_USER).status_code == 403  # another customer's user
    assert c.get(path, headers=AGENT).status_code == 403  # agents use the agent API, not the chef app
    assert c.get(path, headers=USER).status_code == 200
    assert c.get(path.split("?")[0], headers=USER).status_code == 200  # the buyer comes from the credential


def test_chat_needs_a_credential_and_stays_in_its_account(c):
    assert c.post("/v1/chat", json={"text": GALA}).status_code == 401
    r = c.post("/v1/chat", json={"text": GALA, "buyerId": "BUY-POHJOLA"}, headers=OTHER_USER)
    assert r.status_code == 403
    conv = c.post("/v1/chat", json={"text": GALA}, headers=USER).json()["conversation"]
    assert conv["buyerId"] == "BUY-POHJOLA"
    cid = conv["id"]
    assert c.get(f"/v1/chats/{cid}").status_code == 401
    assert c.get(f"/v1/chats/{cid}", headers=OTHER_USER).status_code == 403
    assert c.post(f"/v1/chat/{cid}/actions", json={"action": "order"}, headers=OTHER_USER).status_code == 403
    sid = conv["sessionIds"][-1]
    assert c.get(f"/v1/orders/{sid}/activity").status_code == 401
    assert c.get(f"/v1/orders/{sid}/activity", headers=OTHER_USER).status_code == 403
    assert c.get(f"/v1/orders/{sid}/activity", headers=USER).status_code == 200


def test_chat_approve_needs_the_approvers_own_credential(c):
    conv = c.post("/v1/chat", json={"text": GALA}, headers=USER).json()["conversation"]
    cid = conv["id"]
    c.post(f"/v1/chat/{cid}/actions", json={"action": "order"}, headers=USER)
    c.post("/v1/chat", json={"conversationId": cid, "text": "now 200 guests"}, headers=USER)
    assert c.post(f"/v1/chat/{cid}/actions", json={"action": "send_for_ok"}, headers=USER).status_code == 200
    # the old bypass: approve in chat with a name in the body and no approver credential
    r = c.post(f"/v1/chat/{cid}/actions", json={"action": "approve", "by": "Laura Virtanen"}, headers=USER)
    assert r.status_code == 403
    assert c.post(f"/v1/chat/{cid}/actions", json={"action": "approve", "by": "Laura Virtanen"}).status_code == 401
    r = c.post(f"/v1/chat/{cid}/actions", json={"action": "approve"}, headers=LAURA)
    assert r.status_code == 200 and r.json()["cards"][0]["type"] == "delivery"
    acts = [(e["actor"], e["action"]) for e in c.get("/v1/audit", headers=OPS).json()["events"]]
    assert ("human:Laura Virtanen", "approved") in acts


def test_demo_reset_needs_ops_or_a_demo_user(c, monkeypatch):
    assert c.post("/v1/demo/reset").status_code == 401
    assert c.post("/v1/demo/reset", headers=AGENT).status_code == 403
    assert c.post("/v1/demo/reset", headers=USER).status_code == 200
    assert c.post("/v1/demo/reset", headers=OPS).status_code == 200


def test_demo_tokens_are_refused_outside_demo_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMO_DEMO", "0")
    c = TestClient(make_app(live=False))
    assert c.post("/v1/sessions", json={}, headers=AGENT).status_code == 401
    assert c.get("/v1/board", headers=USER).status_code == 401
    f = tmp_path / "tokens.json"
    f.write_text('{"s3cret-agent-token-0001": {"kind": "agent", "buyerId": "BUY-POHJOLA", "agentId": "agent:pohjola-buyer-01"}}')
    monkeypatch.setenv("AIMO_TOKENS_FILE", str(f))
    c = TestClient(make_app(live=False))
    assert c.post("/v1/sessions", json={}, headers={"Authorization": "Bearer s3cret-agent-token-0001"}).status_code == 201
    assert c.post("/v1/sessions", json={}, headers=AGENT).status_code == 401


def test_tokens_are_compared_in_constant_time(monkeypatch):
    calls = []
    real = auth.hmac.compare_digest

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    from gateway.core import Gateway
    assert auth.resolve(Gateway(), "Bearer demo-key-pohjola").kind == "agent"
    assert calls
