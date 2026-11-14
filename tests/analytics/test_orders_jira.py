"""Jira-style order data: keys, event colours, due dates, activity timeline, order detail."""
from gateway.analytics import views
from gateway.core import Gateway
from gateway.playbook.agent import ChefAssistant

GALA = "Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. 12 vegan, 8 gluten-free, 1 nut allergy."


def test_board_items_have_key_colour_due_and_site():
    gw = Gateway()
    A = ChefAssistant(gw)
    r = A.message(None, GALA)
    A.action(r["conversation"]["id"], "order")
    A.message(None, "I need 1,000 L lactose-free milk by Monday")
    items = [i for c in A.board()["columns"] for i in c["items"]]
    gala = next(i for i in items if i["type"] == "event")
    milk = next(i for i in items if i["type"] == "order")
    assert gala["key"].startswith("POH-") and gala["key"] != milk["key"]
    assert 1 <= gala["eventColor"] <= 8 and milk["eventColor"] is None
    assert gala["due"] == "2026-11-21" and milk["due"] == "2026-11-16"
    assert gala["site"] == "Pohjola Helsinki"


def test_activity_is_a_plain_timeline():
    gw = Gateway()
    A = ChefAssistant(gw)
    r = A.message(None, GALA)
    A.action(r["conversation"]["id"], "order")
    sid = r["conversation"]["sessionIds"][0]
    acts = A.activity(sid)
    texts = [a["text"] for a in acts]
    assert texts[0] == "Request received" and "Ordered" in texts[-1]
    assert any("favourites" in t for t in texts)
    for a in acts:
        assert "playbook" not in a["text"] and "_" not in a["text"]


def test_history_order_detail_lists_lines():
    gw = Gateway()
    first = views.order_history(gw, "BUY-POHJOLA", size=1)["orders"][0]
    d = views.order_detail(gw, "BUY-POHJOLA", first["id"])
    assert d["lines"] and abs(sum(l["value"] for l in d["lines"]) - first["total"]) < 0.05
