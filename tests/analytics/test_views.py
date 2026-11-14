"""Data for Your year (wrapped), order history and the kitchens (CRM) view."""
from gateway.analytics import views
from gateway.core import Gateway

GW = Gateway()


def test_wrapped_tells_a_story_of_at_least_eight_cards():
    w = views.wrapped(GW, "BUY-POHJOLA")
    kinds = [c["kind"] for c in w["cards"]]
    assert len(kinds) >= 8 and kinds[0] == "intro" and kinds[-1] == "outro"
    assert {"top_product", "waste", "co2", "personality", "busiest_month", "top_event"} <= set(kinds)
    for c in w["cards"]:
        assert c["headline"] and len(c.get("numbers", [])) <= 3


def test_wrapped_for_one_kitchen_only_counts_that_kitchen():
    all_ = views.wrapped(GW, "BUY-POHJOLA")["cards"][0]["numbers"][0]["value"]
    one = views.wrapped(GW, "BUY-POHJOLA", "SITE-POH-TKU")["cards"][0]["numbers"][0]["value"]
    assert one != all_


def test_wrapped_for_a_brand_new_kitchen_is_friendly():
    w = views.wrapped(GW, "BUY-UUSI")
    assert w["cards"][0]["kind"] == "empty"


def test_order_history_is_paged_searchable_and_sorted():
    p1 = views.order_history(GW, "BUY-POHJOLA", page=1, size=50)
    assert len(p1["orders"]) == 50 and p1["total"] > 800
    assert p1["orders"][0]["date"] >= p1["orders"][-1]["date"]
    gala = views.order_history(GW, "BUY-POHJOLA", q="gala")
    assert gala["total"] > 0 and all("Gala" in (o["event"] or "") for o in gala["orders"])
    tre = views.order_history(GW, "BUY-POHJOLA", site_id="SITE-POH-TRE")
    assert {o["siteId"] for o in tre["orders"]} == {"SITE-POH-TRE"}


def test_kitchens_have_kpis_and_a_sparkline():
    k = views.kitchens(GW, "BUY-POHJOLA")
    assert k["org"]["name"] == "Hotelli Pohjola Group" and len(k["sites"]) == 3
    s = k["sites"][0]
    assert {"spendMonth", "wastePct", "onTimePct", "trend", "lead", "address"} <= set(s)
    assert len(s["trend"]) == 12
