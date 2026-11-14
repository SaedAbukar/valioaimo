"""Mapping of real mock-API responses (shapes observed 14 Nov 2026) into planner products. No network."""
from datetime import date

from gateway.core import Gateway
from gateway.playbook import discover


class FakeClient:
    """Responses copied from the live API for three real product codes."""

    def prices(self, ids, requested):
        rows = {
            "469549": {"catalogPrice": {"value": 1.0}, "comparisonPrice": {"value": 1.0}, "comparisonUnit": "L", "tax": {"taxRate": 13.5}, "error": False},
            "464119": {"catalogPrice": {"value": 13.32}, "comparisonPrice": {"value": 1.33}, "comparisonUnit": "L", "tax": {"taxRate": 13.5}, "error": False},
            "463335": {"catalogPrice": {"value": 1.4}, "comparisonPrice": {"value": 1.4}, "comparisonUnit": "L", "tax": {"taxRate": 13.5}, "error": False},
        }
        return {i: dict(rows[i], productId=i) for i in ids if i in rows}

    def availability(self, ids, requested):
        rows = {
            "469549": {"logisticModel": "Stock", "salesBlock": False, "scheduleLines": [{"availableAmount": 40.0, "availableDate": "2026-11-16", "salesBlock": False}]},
            "464119": {"logisticModel": "Terminal", "salesBlock": False, "scheduleLines": [{"availableAmount": 999999.0, "availableDate": "2026-11-16", "salesBlock": False}]},
            "463335": {"salesBlock": False, "scheduleLines": []},
        }
        return {i: dict(rows[i], productId=i) for i in ids if i in rows}


def test_comparison_price_sets_unit_and_pack_content():
    gw = Gateway()
    gw.aimo = FakeClient()
    from gateway import aimo_products
    rec = aimo_products.by_id("464119")
    p = discover.bridge(gw, rec, "milk", date(2026, 11, 18), {"price": gw.aimo.prices(["464119"], "")["464119"],
                                                              "availability": gw.aimo.availability(["464119"], "")["464119"]})
    assert p["unit"] == "L" and abs(p["packSize"] - 10.015) < 0.01 and p["unitPrice"] == 1.33 and p["livePrice"]
    assert p["logisticModel"] == "Terminal" and not p["stockKnown"]


def test_search_live_uses_one_batch_and_drops_undeliverable(monkeypatch):
    gw = Gateway()
    gw.aimo = FakeClient()
    from gateway import aimo_products
    monkeypatch.setattr(aimo_products, "search", lambda *a, **k: {"products": [{"productId": i} for i in ("469549", "464119", "463335")], "excluded": []})
    r = discover.search_live(gw, "milk", "milk", date(2026, 11, 18), [], [])
    ids = [p["aimoProductId"] for p in r["products"]]
    assert ids == ["469549", "464119"] and r["live"]
    assert len(r["notDeliverable"]) == 1  # empty scheduleLines
    assert gw.backend.available_by("aimo:469549", date(2026, 11, 18)) == 40.0  # Stock: real quantity × 1 L
