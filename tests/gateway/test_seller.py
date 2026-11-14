"""Proactive seller agent (plan v5 Appendix): Valio Aimo's own agent suggests seasonal, new or better products
to the buyer's agent. Signed, promotional, within the mandate, never added to a basket, and audited."""
import json
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402
from gateway import aimo_products, seller  # noqa: E402
from gateway.core import Gateway  # noqa: E402
from gateway.crypto import verify_jws  # noqa: E402

pytestmark = pytest.mark.skipif(not aimo_products.available(), reason="needs the organiser dataset index (make index)")

AGENT = {"Authorization": "Bearer demo-key-pohjola"}
KAARI = {"Authorization": "Bearer demo-key-kaari"}
KOULU = {"Authorization": "Bearer demo-key-kaarela"}
BRIEF = "I need 1,000 litres of lactose-free milk by Monday."


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def gw_of(c):
    return c.app.state.gw()


def test_at_most_three_signed_promotional_suggestions(c):
    r = c.get("/v1/suggestions", headers=AGENT).json()
    sug = r["suggestions"]
    assert 1 <= len(sug) <= 3 and not r["optedOut"]
    jwks = c.get("/.well-known/jwks.json").json()["keys"]
    for s in sug:
        assert s["issuer"] == "Valio Aimo seller agent" and s["promotional"] is True
        assert s["reason"] and s["tradeOff"] and s["source"] and s["validUntil"] and s["type"] in ("seasonal", "new_similar", "better_option")
        ok, payload, _ = verify_jws(s["proof"]["jws"], jwks)
        assert ok and payload["suggestionId"] == s["suggestionId"] and payload["promotional"] is True
        from gateway.crypto import jws_header
        assert jws_header(s["proof"]["jws"])["typ"] == "suggestion+jwt"
        assert s["price"]["perUnit"] > 0 and s["price"]["source"] in ("valio-aimo-mock-api", "demo-values")
    assert {s["type"] for s in sug} >= {"seasonal"}
    # asking again does not pile up: still at most 3 open
    assert len(c.get("/v1/suggestions", headers=AGENT).json()["suggestions"]) == len(sug)


def test_suggestions_respect_allergen_exclusions_and_categories(c):
    gw = gw_of(c)
    for headers, bid in ((KAARI, "BUY-KAARI"), (KOULU, "BUY-KOULU")):
        m = gw.mandates[bid]["mandate"]
        excl = set(m["hardExclusions"]["allergens"])
        for s in c.get("/v1/suggestions", headers=headers).json()["suggestions"]:
            rec = aimo_products.public(aimo_products.by_id(s["productId"]))
            assert not (set(rec["contains"]) | set(rec["mayContain"])) & excl, (bid, s["name"])
            assert set(m["hardExclusions"]["diet"]) <= set(rec["diet"]), (bid, s["name"])
            assert s["category"] in m["allowedCategories"]


def test_opt_out_is_respected(c):
    gw = gw_of(c)
    gw.profiles["BUY-POHJOLA"]["sellerSuggestions"] = False
    r = c.get("/v1/suggestions", headers=AGENT).json()
    assert r["optedOut"] and r["suggestions"] == []
    gw.profiles["BUY-POHJOLA"]["sellerSuggestions"] = True
    assert c.get("/v1/suggestions", headers=AGENT).json()["suggestions"]


def test_mandate_opt_out_is_respected():
    gw = Gateway()
    body = dict(gw.mandates["BUY-POHJOLA"]["mandate"])
    body["preferences"] = {**body["preferences"], "sellerSuggestions": False}
    gw.register_mandate("BUY-POHJOLA", gw.sign_mandate("BUY-POHJOLA", body))
    assert seller.run(gw, "BUY-POHJOLA") == [] and seller.open_for(gw, "BUY-POHJOLA") == []


def test_another_buyers_credential_gets_403(c):
    s = c.get("/v1/suggestions", headers=AGENT).json()["suggestions"][0]
    assert c.get("/v1/suggestions?buyerId=BUY-POHJOLA", headers=KAARI).status_code == 403
    r = c.post(f"/v1/suggestions/{s['suggestionId']}/feedback", json={"decision": "dismissed"}, headers=KAARI)
    assert r.status_code == 403
    assert c.get("/v1/suggestions").status_code == 401
    assert c.get("/v1/suggestions", headers={"Authorization": "Bearer demo-human-usr-lvirtanen"}).status_code == 403


def test_feedback_is_audited_and_idempotent(c):
    s = c.get("/v1/suggestions", headers=AGENT).json()["suggestions"][0]
    h = {**AGENT, "Idempotency-Key": "fb-1"}
    r1 = c.post(f"/v1/suggestions/{s['suggestionId']}/feedback", json={"decision": "dismissed", "reason": "not this week"}, headers=h)
    r2 = c.post(f"/v1/suggestions/{s['suggestionId']}/feedback", json={"decision": "dismissed", "reason": "not this week"}, headers=h)
    assert r1.status_code == 200 and r2.headers.get("Idempotent-Replay") == "true"
    assert c.post(f"/v1/suggestions/{s['suggestionId']}/feedback", json={"decision": "maybe"}, headers=AGENT).status_code == 422
    ev = c.get("/v1/audit", headers=AGENT).json()["events"]
    mine = [e for e in ev if e["refs"].get("suggestionId") == s["suggestionId"]]
    assert {e["action"] for e in mine} >= {"suggestion.created", "suggestion.shown", "suggestion.dismissed"}
    assert all(e["actor"] == "agent:valio-aimo-seller" for e in mine if e["action"] in ("suggestion.created", "suggestion.shown"))
    assert any(e["action"] == "suggestion.dismissed" and e["reason"] and "not this week" in e["reason"] for e in mine)


def test_dismissed_products_are_not_suggested_again_for_30_days():
    gw = Gateway()
    first = seller.run(gw, "BUY-POHJOLA")
    gone = first[0]
    seller.feedback(gw, "BUY-POHJOLA", gone["suggestionId"], "dismissed", "no", actor="agent:pohjola-buyer-01")
    for _ in range(3):
        again = seller.open_for(gw, "BUY-POHJOLA") + seller.run(gw, "BUY-POHJOLA", force=True)
        assert gone["productId"] not in {s["productId"] for s in again}
    assert len(seller.open_for(gw, "BUY-POHJOLA")) <= 3
    gw.clock.advance(31 * 24 * 60)
    assert seller.dismissed_recently(gw, "BUY-POHJOLA", gone["productId"]) is False


def test_accepting_replans_through_check_basket_not_a_direct_order(c):
    sugs = c.get("/v1/suggestions", headers=AGENT).json()["suggestions"]
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards"):
        c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": BRIEF} if t == "parse_request" else {}, headers=AGENT)
    before = c.get(f"/v1/sessions/{sid}", headers=AGENT).json()["outputs"]["plan"]
    pick = next(s for s in sugs if s["action"] == "add")
    orders_before = len(gw_of(c).backend.orders)
    r = c.post(f"/v1/sessions/{sid}/tools/plan_basket", json={"acceptSuggestion": pick["suggestionId"]}, headers=AGENT).json()
    assert r["step"] == "plan" and "place_order" not in r["next_allowed_tools"] and "check_basket" in r["next_allowed_tools"]
    assert len(gw_of(c).backend.orders) == orders_before  # never ordered directly
    added = [l for l in r["output"]["lines"] if l["source"] == "valio-aimo-seller"]
    assert added and added[0]["aimoProductId"] == pick["productId"] and len(r["output"]["lines"]) == len(before["lines"]) + 1
    chk = c.post(f"/v1/sessions/{sid}/tools/check_basket", json={}, headers=AGENT).json()["output"]
    assert chk["decision"] in ("tell_me", "needs_ok") and "R8" in chk["internal"]["ruleIds"]  # first-time product
    assert gw_of(c).seller_state["suggestions"][pick["suggestionId"]]["status"] == "accepted"
    acts = [e["action"] for e in c.get(f"/v1/audit?sessionId={sid}", headers=AGENT).json()["events"]]
    assert "suggestion.accepted" in acts and acts.index("suggestion.accepted") < len(acts) - 1


def test_a_suggestion_of_another_buyer_cannot_be_accepted(c):
    other = c.get("/v1/suggestions", headers=KOULU).json()["suggestions"][0]
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    for t in ("parse_request", "recall", "plan_basket"):
        c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": BRIEF} if t == "parse_request" else {}, headers=AGENT)
    r = c.post(f"/v1/sessions/{sid}/tools/plan_basket", json={"acceptSuggestion": other["suggestionId"]}, headers=AGENT)
    assert r.status_code == 404 and r.json()["fix"]


def test_suggestion_created_event_wakes_the_buyer_agent(c):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    evs = c.get(f"/v1/sessions/{sid}/events", headers=AGENT).json()["events"]
    created = [e for e in evs if e["type"] == "suggestion.created"]
    assert created and created[0]["data"]["suggestionId"] and created[0]["data"]["issuer"] == "Valio Aimo seller agent"


def test_discovery_lists_the_seller(c):
    card = c.get("/.well-known/agent-card.json").json()
    assert "proactive-offers" in {s["id"] for s in card["skills"]}
    assert "com.valioaimo.suggestions" in json.dumps(c.get("/.well-known/ucp").json())
    paths = c.get("/openapi.json").json()["paths"]
    assert "/v1/suggestions" in paths and "/v1/suggestions/{suggestionId}/feedback" in paths
    names = {t["name"] for t in c.get("/v1/tools").json()["tools"]}
    assert {"get_suggestions", "suggestion_feedback"} <= names


def test_mcp_parity():
    os.environ["AIMO_LIVE"] = "0"
    os.environ["AIMO_AGENT_TOKEN"] = "demo-key-pohjola"
    import asyncio
    import gateway.mcp_server as m
    names = {t.name for t in asyncio.run(m.mcp.list_tools())}
    assert {"get_suggestions", "suggestion_feedback"} <= names
    got = json.loads(m.get_suggestions())
    s = got["suggestions"][0]
    assert s["issuer"] == "Valio Aimo seller agent" and s["proof"]["jws"]
    fb = json.loads(m.suggestion_feedback(s["suggestionId"], "dismissed", "not now"))
    assert fb["status"] == "dismissed"


def test_agent_demo_suggestions_verifies_signatures(c, monkeypatch, capsys):
    import scripts.agent_demo as demo

    class Local(demo.Gateway):
        def call(self, method, path, body=None, token=None):
            r = c.request(method, path, json=body, headers={"Authorization": f"Bearer {token or self.token}"})
            return r.status_code, r.json()

    monkeypatch.setattr(demo, "Gateway", Local)
    assert demo.suggestions("http://test", "demo-key-pohjola") == 0
    out = capsys.readouterr().out
    assert "signature valid" in out and "suggestion+jwt" in out
