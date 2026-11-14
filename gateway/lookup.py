"""Structured product, price and availability lookup for external agents.

Read-only: nothing here commits spend, so it sits outside the order playbook.
Price and availability come from the Valio Aimo mock API through the adapter
(ONE /api/price and ONE /api/availability call per lookup, only for the products
already narrowed down), or from deterministic demo values when no key is set;
`source` always says which.

What an agent sees is limited on purpose (docs/EXPOSURE.md): availability is a
status plus "can you cover MY quantity", never the warehouse stock level.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import aimo_products
from .playbook import discover
from .util import d2s, delivery_day, s2d

MAX_LIMIT = 20


def _need_by(gw, need_by: str | None) -> date:
    return s2d(need_by) if need_by else delivery_day(gw.clock.today() + timedelta(days=2))


def _live(gw, ids: list[str], nb: date) -> tuple[dict, dict]:
    client = getattr(gw, "aimo", None)
    if not client or not ids:
        return {}, {}
    return client.prices(ids, d2s(nb)), client.availability(ids, d2s(nb))


def _row(gw, rec: dict, nb: date, qty: float | None, prices: dict, avail: dict) -> dict:
    pid = rec["id"]
    live = {"price": prices.get(pid), "availability": avail.get(pid)} if (prices or avail) else None
    p = discover.bridge(gw, rec, None, nb, live)
    pub = aimo_products.public(rec)
    be = gw.backend
    sched = be.schedule(p["gtin"])
    earliest = sched[0]["date"] if sched else None
    by_need = be.available_by(p["gtin"], nb)
    if not sched:
        status = "not_deliverable"
    elif earliest > d2s(nb):
        status = "not_by_date"
    elif qty and by_need + 1e-9 < qty:
        status = "partial"
    else:
        status = "available"
    packs = None
    if qty and p["packSize"]:
        packs = -(-qty // p["packSize"])
    return {
        "productId": pid, "gtin": pub["gtin"], "name": pub["name"], "nameFi": pub["nameFi"], "brand": pub["brand"],
        "content": {"perSalesUnit": p["packSize"], "unit": p["unit"]},
        "price": {"perSalesUnit": p["salesUnitPrice"], "perUnit": p["unitPrice"], "unit": p["unit"], "currency": "EUR",
                  "vatRate": p.get("taxRate"), "validTo": p.get("priceValidTo"),
                  "source": "valio-aimo-mock-api" if p["livePrice"] else "demo-values"},
        "availability": {"status": status, "earliestDelivery": earliest, "needBy": d2s(nb),
                         "canCoverQty": (min(by_need, qty) if qty else None),
                         "logisticModel": p.get("logisticModel"), "orderCutoff": p.get("closingTime"),
                         "source": "valio-aimo-mock-api" if live and live.get("availability") else "demo-values"},
        "estimate": ({"salesUnits": packs, "total": round(packs * p["salesUnitPrice"], 2)} if packs else None),
        "deliveryReliability": pub["deliveryReliability"], "co2eKgPerKg": pub["co2eKgPerKg"], "labels": pub["labels"],
        "allergens": {"contains": pub["contains"], "mayContain": pub["mayContain"]}, "diet": pub["diet"],
    }


def _rank(rows: list[dict]) -> list[dict]:
    """good-better-best: deliverable on time first, then price per kg / L, then reliability."""
    order = {"available": 0, "partial": 1, "not_by_date": 2, "not_deliverable": 3}
    rows.sort(key=lambda r: (order[r["availability"]["status"]], r["price"]["perUnit"], -(r["deliveryReliability"] or 0)))
    ok = [r for r in rows if r["availability"]["status"] == "available"]
    if ok:
        ok[0]["tag"] = "best_price"
        rel = max(ok, key=lambda r: r["deliveryReliability"] or 0)
        rel.setdefault("tag", "most_reliable")
        low = min(ok, key=lambda r: r["co2eKgPerKg"] if r["co2eKgPerKg"] is not None else 99)
        low.setdefault("tag", "lowest_co2")
    return rows


def search(gw, query: str, qty: float | None = None, need_by: str | None = None,
           exclude_allergens: list[str] | None = None, diet: list[str] | None = None, limit: int = 8) -> dict:
    limit = max(1, min(int(limit or 8), MAX_LIMIT))
    nb = _need_by(gw, need_by)
    q = discover.query_fi(query)
    r = aimo_products.search(q, exclude_allergens=exclude_allergens, diet=diet, limit=limit)
    ids = [x["productId"] for x in r["products"]]
    prices, avail = _live(gw, ids, nb)
    rows = _rank([_row(gw, aimo_products.by_id(i), nb, qty, prices, avail) for i in ids])
    return {"query": query, "needBy": d2s(nb), "qty": qty, "count": len(rows), "products": rows,
            "excluded": r["excluded"], "live": bool(prices),
            "next": "To buy: start a playbook session (POST /v1/sessions) and follow next_allowed_tools."}


def price_availability(gw, product_ids: list[str], need_by: str | None = None, qty: float | None = None) -> dict:
    ids = [str(i).replace("aimo:", "") for i in product_ids][:MAX_LIMIT]
    nb = _need_by(gw, need_by)
    recs = {i: aimo_products.by_id(i) for i in ids}
    unknown = [i for i, rec in recs.items() if not rec]
    known = [i for i in ids if recs[i]]
    prices, avail = _live(gw, known, nb)
    return {"needBy": d2s(nb), "products": [_row(gw, recs[i], nb, qty, prices, avail) for i in known],
            "unknown": unknown, "live": bool(prices)}


def product(gw, product_id: str) -> dict | None:
    rec = aimo_products.by_id(str(product_id).replace("aimo:", ""))
    return aimo_products.public(rec) if rec else None
