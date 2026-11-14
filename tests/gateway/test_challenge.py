"""The challenge checklist as tests (docs/CHALLENGE_CHECKLIST.md). Each test names the item it proves."""
import os
import time

import pytest
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402
from gateway.core import Gateway  # noqa: E402
from gateway.crypto import verify_jws  # noqa: E402
from gateway import lookup  # noqa: E402
from gateway.playbook.engine import StepNotAllowed  # noqa: E402
from gateway.playbook.tools import offer_ids  # noqa: E402

BRIEF = ("I need 1,000 litres of lactose-free milk by Monday. "
         "Find an option that meets our requirements based on price and availability.")
AGENT = {"Authorization": "Bearer demo-key-pohjola"}
OTHER_AGENT = {"Authorization": "Bearer demo-key-kaarela"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
OTHER_HUMAN = {"Authorization": "Bearer demo-human-usr-skoskinen"}
OPS = {"Authorization": "Bearer demo-ops"}


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def run_agent(c, text, headers=AGENT, stop_at_approval=False):
    """A minimal external agent: obeys next_allowed_tools, cites the offers. Returns (sessionId, last output, log)."""
    seen = []
    sid = c.post("/v1/sessions", json={}, headers=headers).json()["sessionId"]
    nxt, plan, out = ["parse_request"], None, None
    prefer = ["parse_request", "recall", "request_offers", "plan_basket", "check_basket", "render_cards", "place_order", "request_approval"]
    done = set()
    while (tool := next((t for t in prefer if t in nxt and t not in done), None)):
        args = {"text": text} if tool == "parse_request" else {"offerIds": [o["offerId"] for o in plan["offers"]]} if tool == "place_order" else {}
        r = c.post(f"/v1/sessions/{sid}/tools/{tool}", json=args, headers=headers)
        assert r.status_code == 200, (tool, r.json())
        seen.append(tool)
        done.add(tool)
        out, nxt = r.json()["output"], r.json()["next_allowed_tools"]
        if tool == "plan_basket":
            plan = out
        if tool in ("place_order", "request_approval"):
            break
    return sid, out, seen


# ---------------------------------------------------------------- 1 structured lookup
def test_1_lookup_is_documented_json_and_needs_a_credential(c):
    assert c.post("/v1/products/search", json={"query": "milk"}).status_code == 401
    r = c.post("/v1/products/search", json={"query": "lactose-free milk", "qty": 1000, "needBy": "2026-11-16"}, headers=AGENT).json()
    p = r["products"][0]
    assert {"productId", "name", "price", "availability", "deliveryReliability", "co2eKgPerKg", "labels", "allergens"} <= set(p)
    assert p["price"]["perUnit"] > 0 and p["price"]["unit"] == "L" and p["availability"]["status"] in ("available", "partial", "not_by_date", "not_deliverable")
    assert "lactose_free" in p["diet"]
    pa = c.post("/v1/products/price-availability", json={"productIds": [p["productId"]], "qty": 10}, headers=AGENT).json()
    assert pa["products"][0]["productId"] == p["productId"]
    assert "/v1/products/search" in c.get("/openapi.json").json()["paths"]


class FakeAimo:
    """Stands in for adapter.AimoApiClient with the mock API's response shapes (no network in tests)."""
    calls = 0

    def prices(self, ids, requested):
        FakeAimo.calls += 1
        return {i: {"catalogPrice": {"value": 1.25, "validTo": "2026-12-31"}, "comparisonPrice": {"value": 1.25},
                    "comparisonUnit": "L", "tax": {"taxRate": 14}} for i in ids}

    def availability(self, ids, requested):
        FakeAimo.calls += 1
        return {i: {"logisticModel": "Stock", "scheduleLines": [{"availableAmount": 400, "availableDate": requested}]} for i in ids}


def test_1_lookup_goes_through_the_adapter_in_one_batch_per_call():
    gw = Gateway()
    gw.aimo = FakeAimo()
    FakeAimo.calls = 0
    r = lookup.search(gw, "lactose-free milk", qty=1000, need_by="2026-11-16", limit=5)
    assert FakeAimo.calls == 2 and r["live"]
    p = r["products"][0]
    assert p["price"]["source"] == "valio-aimo-mock-api" and p["price"]["perUnit"] == 1.25
    assert p["availability"]["status"] == "partial" and p["availability"]["canCoverQty"] == 400


# ---------------------------------------------------------------- 2 inquiry -> commitment at fixed prices
def test_2_order_must_cite_the_signed_offers_and_prices_are_not_negotiable(c):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    out = {}
    for t, a in (("parse_request", {"text": BRIEF}), ("recall", {}), ("plan_basket", {}), ("check_basket", {}), ("render_cards", {})):
        out[t] = c.post(f"/v1/sessions/{sid}/tools/{t}", json=a, headers=AGENT).json()["output"]
    plan = out["plan_basket"]
    ids = [o["offerId"] for o in plan["offers"]]
    of = c.get(f"/v1/offers/{ids[0]}", headers=AGENT).json()
    ok, payload, _ = verify_jws(of["proof"]["jws"], c.get("/.well-known/jwks.json").json()["keys"])
    assert ok and payload["validUntil"] and payload["credentialSubject"]["unitPrice"] == of["unitPrice"]
    assert c.post(f"/v1/offers/{ids[0]}/verify", headers=AGENT).json()["verified"]
    r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={}, headers=AGENT)
    assert r.status_code == 422 and r.json()["guard"] == "cite_offers" and r.json()["fix"]["offerIds"] == ids
    r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids, "unitPrice": 0.99}, headers=AGENT)
    assert r.status_code == 422 and r.json()["guard"] == "fixed_prices"
    r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ["OF-NOPE"]}, headers=AGENT)
    assert r.status_code == 409 and r.json()["guard"] == "offer_mismatch" and r.json()["next_allowed_tools"] == ["plan_basket"]
    o = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids}, headers=AGENT).json()["output"]
    assert all(l["offerId"] in ids for l in o["lines"])


def test_2_changed_price_means_requote_never_a_silent_new_price():
    gw = Gateway()
    sid = gw.engine.call(None, "start_session", {"buyerId": "BUY-POHJOLA"})["sessionId"]
    for t, a in (("parse_request", {"text": BRIEF}), ("recall", {}), ("plan_basket", {}), ("check_basket", {}), ("render_cards", {})):
        gw.engine.call(sid, t, a)
    s = gw.engine.sessions[sid]
    gtin = s["data"]["plan"]["lines"][0]["gtin"]
    old = gw.backend.price(gtin)
    gw.backend.set_price(gtin, old + 0.10)
    with pytest.raises(StepNotAllowed) as e:
        gw.engine.call(sid, "place_order", {"offerIds": offer_ids(s)})
    assert e.value.extra["guard"] == "price_locked" and "price now" in str(e.value)
    plan = gw.engine.call(sid, "plan_basket")["output"]  # re-quote: a fresh signed offer at the new price
    assert plan["offers"][0]["unitPrice"] == pytest.approx(old + 0.10)


# ---------------------------------------------------------------- 3 permissions and human approval
def test_3_rules_are_published_and_cover_the_brief(c):
    r = c.get("/v1/rules").json()
    human = {x["title"] for x in r["autonomy"]["needsNamedHumanOk"]}
    never = {x["title"] for x in r["autonomy"]["neverAllowed"]}
    assert {"Per-order spend limit", "Substitution outside tolerance", "Delivery after need-by date"} <= human
    assert "Hard allergen / diet exclusion" in never
    assert "gateway" in r["decidedBy"] and r["limitsPerBuyer"]["BUY-POHJOLA"]["approvers"]


def test_3_over_limit_reaches_a_named_human_and_the_agent_cannot_approve(c):
    sid, out, _ = run_agent(c, BRIEF.replace("1,000", "3,000"))
    assert out["status"] == "waiting_for_ok"
    aid = out["approval"]["approvalId"]
    assert out["approval"]["approver"]["name"] == "Laura Virtanen"
    assert c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=AGENT).status_code == 403
    assert c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=OTHER_HUMAN).status_code == 403
    inbox = c.get("/v1/approvals", headers=LAURA).json()
    assert [p["approvalId"] for p in inbox["pending"]] == [aid]
    d = c.post(f"/v1/approvals/{aid}", json={"ok": True, "note": "fine"}, headers=LAURA).json()
    assert d["approval"]["status"] == "approved" and d["approval"]["decidedBy"] == "Laura Virtanen"
    plan = c.get(f"/v1/sessions/{sid}", headers=AGENT).json()["outputs"]["plan"]
    o = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": [x["offerId"] for x in plan["offers"]]}, headers=AGENT).json()["output"]
    assert o["approvedBy"] == "Laura Virtanen"
    acts = [(e["actor"], e["action"]) for e in c.get(f"/v1/audit?sessionId={sid}", headers=AGENT).json()["events"]]
    assert ("system:gateway", "approval.notified") in acts and ("human:Laura Virtanen", "approved") in acts
    assert ("system:gateway", "playbook.check_basket") in acts  # the gateway decided, not the agent


# ---------------------------------------------------------------- 4 end to end
def test_4_brief_request_end_to_end_over_http_under_a_minute(c):
    t0 = time.perf_counter()
    sid, order, tools = run_agent(c, BRIEF)
    assert time.perf_counter() - t0 < 60
    assert tools[:2] == ["parse_request", "recall"] and tools[-1] == "place_order"
    assert order["status"] == "ordered" and sum(l["qty"] for l in order["lines"]) >= 1000
    got = c.get(f"/v1/orders/{order['orderId']}", headers=AGENT).json()
    assert got["confirmationVerified"]
    ok, payload, _ = verify_jws(order["confirmation"]["jws"], c.get("/.well-known/jwks.json").json()["keys"])
    assert ok and payload["type"] == "OrderConfirmation" and payload["offerIds"] and payload["mandateId"] == "MAN-POHJOLA"


# ---------------------------------------------------------------- 5 no exposure
def test_5_agents_never_reach_backend_or_secrets(c, monkeypatch):
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "gateway"
    talkers = sorted(p.name for p in src.rglob("*.py") if "urllib" in p.read_text())
    assert talkers == ["adapter.py"]  # the only module that can reach Valio Aimo systems
    sid, order, _ = run_agent(c, BRIEF)
    bodies = [c.get(u, headers=AGENT).text for u in (f"/v1/sessions/{sid}", f"/v1/orders/{order['orderId']}", "/v1/mandate",
                                                     f"/v1/sessions/{sid}/log", "/.well-known/ucp", "/openapi.json")]
    bodies.append(c.post("/v1/products/search", json={"query": "milk", "qty": 5}, headers=AGENT).text)
    for b in bodies:
        assert "X-API-Key" not in b and "junction26.valioaimo.fi" not in b
        key = os.environ.get("AIMO_API_KEY")
        assert not key or key not in b
    p = c.post("/v1/products/search", json={"query": "milk", "qty": 5}, headers=AGENT).json()["products"][0]
    assert p["availability"]["canCoverQty"] <= 5  # never the warehouse stock level


def test_7_agent_is_bound_to_its_customer_account(c):
    assert c.post("/v1/sessions", json={}).status_code == 401
    assert c.post("/v1/sessions", json={"buyerId": "BUY-KOULU"}, headers=AGENT).status_code == 403
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    assert c.get(f"/v1/sessions/{sid}", headers=OTHER_AGENT).status_code == 403
    assert c.post(f"/v1/sessions/{sid}/tools/parse_request", json={"text": BRIEF}, headers=OTHER_AGENT).status_code == 403
    m = c.get("/v1/mandate", headers=AGENT).json()
    ok, payload, _ = verify_jws(m["jws"], m["buyerJwks"]["keys"])
    assert ok and payload["issuedBy"]["name"] and payload["limits"]["perOrderEUR"] == 2000


def test_7_valio_aimo_operations_can_pause_an_agent(c):
    assert c.post("/v1/ops/agents/agent:pohjola-buyer-01/pause", json={}, headers=AGENT).status_code == 403
    c.post("/v1/ops/agents/agent:pohjola-buyer-01/pause", json={"paused": True, "reason": "test"}, headers=OPS)
    r = c.post("/v1/sessions", json={}, headers=AGENT)
    assert r.status_code == 422 and r.json()["guard"] == "known_agent"
    assert c.get("/v1/audit", headers=OPS).json()["verify"]["ok"]


# ---------------------------------------------------------------- 6 open standards
def test_6_openapi_31_and_every_documented_path_is_served(c):
    spec = c.get("/openapi.json").json()
    assert spec["openapi"] == "3.1.0"
    for name, sch in spec["components"]["schemas"].items():
        Draft202012Validator.check_schema(sch)
    import re
    served = {re.sub(r"\{[^}]+\}", "{}", r.path) for r in c.app.routes}
    for path in spec["paths"]:
        assert re.sub(r"\{[^}]+\}", "{}", path) in served, path


def test_6_well_known_profile_agent_card_and_jwks(c):
    ucp = c.get("/.well-known/ucp").json()
    assert ucp["ucp"]["services"]["dev.ucp.shopping"]["rest"]["schema"].endswith("/openapi.json")
    assert ucp["trust"]["jwks_uri"].endswith("/.well-known/jwks.json")
    card = c.get("/.well-known/agent-card.json").json()
    ok, payload, _ = verify_jws(card["signatures"][0]["jws"], c.get("/.well-known/jwks.json").json()["keys"])
    assert ok and payload["name"] == card["name"] and {s["id"] for s in card["skills"]} >= {"product-lookup", "order", "approval"}


# ---------------------------------------------------------------- 8 playbook served and enforced
def test_8_playbook_served_and_out_of_order_rejected_over_http(c):
    pb = c.get("/v1/playbook").json()
    assert [s["name"] for s in pb["steps"]][1:8] == ["Understand", "Recall first", "Discover only for gaps", "Plan", "Check", "Present", "Act"]
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={}, headers=AGENT)
    assert r.status_code == 409 and r.json()["next_allowed_tools"][0] == "parse_request"


# ---------------------------------------------------------------- 11 human-readable log
def test_11_plain_log_for_the_buyer(c):
    sid, _, _ = run_agent(c, BRIEF)
    log = c.get(f"/v1/sessions/{sid}/log", headers=AGENT).json()
    assert log["log"] and all(e["why"] for e in log["audit"] if e["what"].startswith("playbook."))
