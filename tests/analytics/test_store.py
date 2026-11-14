"""Task 1: a deterministic, rich year of order history per site."""
from gateway.analytics import store
from gateway.core import Gateway


def _counts(conn):
    q = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
    return {"orders": q("SELECT COUNT(DISTINCT order_id) FROM line"), "lines": q("SELECT COUNT(*) FROM line"),
            "months": q("SELECT COUNT(DISTINCT month) FROM line"), "event_types": q("SELECT COUNT(DISTINCT event_type) FROM line WHERE event_type IS NOT NULL"),
            "spend": round(q("SELECT SUM(value_eur) FROM line"), 2)}


def test_history_is_deterministic_and_rich():
    a, b = _counts(store.load(Gateway())), _counts(store.load(Gateway()))
    assert a == b
    assert a["orders"] >= 1000 and a["lines"] >= 15000
    assert a["months"] == 12 and a["event_types"] >= 5


def test_every_pohjola_site_has_history():
    conn = store.load(Gateway())
    sites = {r[0] for r in conn.execute("SELECT DISTINCT site_id FROM line WHERE buyer_id='BUY-POHJOLA'")}
    assert sites == {"SITE-POH-HKI", "SITE-POH-TRE", "SITE-POH-TKU"}


def test_waste_falls_over_the_year_for_pohjola():
    conn = store.load(Gateway())
    rows = conn.execute("SELECT month, SUM(waste_eur)/SUM(value_eur) FROM line WHERE buyer_id='BUY-POHJOLA' GROUP BY month ORDER BY month").fetchall()
    assert rows[-1][1] < rows[0][1]


def test_schema_describes_every_queryable_field():
    for name, f in store.SCHEMA["dimensions"].items():
        assert f["label"] and f["type"] in ("time", "category")
    for name, f in store.SCHEMA["measures"].items():
        assert f["label"] and f["sql"] and f["unit"] in ("EUR", "kg", "kg CO2e", "%", "count", "units", "EUR/unit")
