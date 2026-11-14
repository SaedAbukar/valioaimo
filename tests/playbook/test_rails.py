"""The rails themselves: order enforcement, guards, schema checks, lint, audit."""
import pytest

from gateway.core import Gateway
from gateway.playbook import cards as C
from gateway.playbook.engine import GuardFailed, StepNotAllowed, public_playbook


@pytest.fixture
def gw():
    return Gateway()


def start(gw, bid="BUY-POHJOLA"):
    return gw.engine.call(None, "start_session", {"buyerId": bid})["sessionId"]


def test_playbook_is_versioned_and_complete():
    pb = public_playbook()
    assert pb["version"] == "1.0.0"
    assert [s["n"] for s in pb["steps"]] == list(range(9))
    assert pb["steps"][2]["order"] == ["favourites", "similar_orders", "learned_quantities", "standing_orders", "leftovers"]
    for s in pb["steps"]:
        assert s["tools"] and s.get("output")


def test_out_of_order_is_409_with_next_tools(gw):
    sid = start(gw)
    with pytest.raises(StepNotAllowed) as e:
        gw.engine.call(sid, "place_order")
    assert e.value.status == 409 and e.value.extra["next_allowed_tools"][0] == "parse_request"
    gw.engine.call(sid, "parse_request", {"text": "I need 1,000 L lactose-free milk by Monday"})
    with pytest.raises(StepNotAllowed):
        gw.engine.call(sid, "search_products", {"query": "milk"})  # recall first


def test_discover_locked_when_recall_has_no_gaps(gw):
    sid = start(gw)
    gw.engine.call(sid, "parse_request", {"text": "I need 1,000 L lactose-free milk by Monday"})
    r = gw.engine.call(sid, "recall")
    assert r["output"]["gaps"] == [] and "request_offers" not in r["next_allowed_tools"]
    with pytest.raises(StepNotAllowed):
        gw.engine.call(sid, "request_offers")


def test_missing_date_asks_exactly_one_question(gw):
    sid = start(gw)
    b = gw.engine.call(sid, "parse_request", {"text": "Christmas party for 120: kinkku, rosolli, riisipuuro"})["output"]
    assert b["missing"] == ["when"] and b["event"]["guests"] == 120
    q = gw.engine.call(sid, "ask_user")["output"]["question"]
    assert q["field"] == "when" and 1 <= len(q["answers"]) <= 3
    with pytest.raises(StepNotAllowed):
        gw.engine.call(sid, "ask_user")
    with pytest.raises(StepNotAllowed):
        gw.engine.call(sid, "recall")
    b = gw.engine.call(sid, "parse_request", {"answer": {"field": "when", "value": "2026-12-11"}})["output"]
    assert b["complete"]


def test_finnish_request(gw):
    sid = start(gw)
    b = gw.engine.call(sid, "parse_request", {"text": "Pikkujoulut lauantaina 21.11. 120 hengelle: kinkku, rosolli, riisipuuro. 6 vegaania."})["output"]
    assert b["lang"] == "fi" and b["event"]["guests"] == 120 and b["event"]["date"] == "2026-11-21"
    assert b["constraints"]["dietCounts"] == {"vegan": 6}


def _to_present(gw, text="I need 1,000 L lactose-free milk by Monday"):
    sid = start(gw)
    for t, a in (("parse_request", {"text": text}), ("recall", {}), ("plan_basket", {}), ("check_basket", {}), ("render_cards", {})):
        gw.engine.call(sid, t, a)
    return sid


def test_check_is_gateway_run_and_agent_cannot_skip_it(gw):
    sid = start(gw)
    gw.engine.call(sid, "parse_request", {"text": "I need 1,000 L lactose-free milk by Monday"})
    gw.engine.call(sid, "recall")
    gw.engine.call(sid, "plan_basket")
    with pytest.raises(StepNotAllowed):
        gw.engine.call(sid, "place_order")
    gw.engine.call(sid, "check_basket")
    ev = [e for e in gw.audit.events(trace_id=sid) if e["action"] == "playbook.check_basket"][0]
    assert ev["actor"] == "system:gateway" and ev["decision"] == "tell_me"


def test_price_lock_stops_expired_offers(gw):
    sid = _to_present(gw)
    gw.clock.advance(16)
    with pytest.raises(StepNotAllowed) as e:
        gw.engine.call(sid, "place_order")
    assert e.value.extra["guard"] == "price_locked"
    gw.engine.call(sid, "plan_basket")  # re-plan gets fresh signed offers
    gw.engine.call(sid, "check_basket")
    gw.engine.call(sid, "render_cards")
    assert gw.engine.call(sid, "place_order")["output"]["status"] == "ordered"


def test_needs_ok_cannot_be_ordered_directly(gw):
    sid = start(gw, "BUY-KOULU")
    for t, a in (("parse_request", {"text": "60 L oat drink by Monday"}), ("recall", {}), ("plan_basket", {"useAlternative": "L1"}),
                 ("check_basket", {}), ("render_cards", {})):
        gw.engine.call(sid, t, a)
    assert gw.engine.sessions[sid]["data"]["decision"]["decision"] == "needs_ok"
    with pytest.raises(StepNotAllowed):
        gw.engine.call(sid, "place_order")
    assert gw.engine.call(sid, "request_approval")["output"]["status"] == "waiting_for_ok"


def test_every_step_is_audited_with_playbook_version(gw):
    sid = _to_present(gw)
    evs = [e for e in gw.audit.events(trace_id=sid) if e["action"].startswith("playbook.")]
    assert [e["refs"]["step"] for e in evs] == ["receive", "understand", "recall", "plan", "check", "present"]
    assert all(e["refs"]["playbookVersion"] == "1.0.0" and "ms" in e["refs"] for e in evs)
    assert gw.audit.verify()["ok"]


def test_cards_pass_lint_and_lint_catches_jargon(gw):
    sid = _to_present(gw)
    for c in gw.engine.sessions[sid]["data"]["cards"]:
        assert C.lint(c) == []
    bad = C.card("basket", text="Policy R2 fired: the mandate limit and GTIN 0643 score 0.8 1 2 3")
    errs = C.lint(bad)
    assert any("mandate" in e for e in errs) and any("R2" in e for e in errs) and any("numbers" in e for e in errs)
    with pytest.raises(GuardFailed):
        C.lint_all([bad])


def test_external_agent_cards_are_linted(gw):
    sid = _to_present(gw)
    gw.engine.call(sid, "plan_basket")
    gw.engine.call(sid, "check_basket")
    with pytest.raises(GuardFailed):
        gw.engine.call(sid, "render_cards", {"cards": [{"type": "basket", "title": "Tier BEST by score", "text": ""}]})


def test_unknown_agent_cannot_start(gw):
    with pytest.raises(GuardFailed):
        gw.engine.call(None, "start_session", {"buyerId": "BUY-POHJOLA", "agentId": "agent:stranger"})
