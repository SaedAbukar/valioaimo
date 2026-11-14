"""Step 3 · Discover — only for gaps that Recall could not fill.

Two sources, one shape:
  * the curated demo assortment (gateway/data/catalog.json) for the seeded
    customers, so golden scenarios stay repeatable;
  * the real Valio Aimo product data (17.5k products, gateway/aimo_products.py)
    for kitchens on the live assortment and for needs the curated set lacks.
Real products are bridged into the planner's product shape here. Price and
availability come from the mock API when AIMO_API_KEY is set (only for the few
products already narrowed down), otherwise from deterministic demo values.
"""
from __future__ import annotations

import re
from datetime import date

from .. import aimo_products, catalog
from ..adapter import demo_value
from ..util import d2s, s2d

# curated kind -> category (planner/policy speak) and a typical demo price per kg/L
KIND_CATEGORY = {p["kind"]: p["category"] for p in catalog.products()}
KIND_PRICE: dict[str, list[float]] = {}
for _p in catalog.products():
    KIND_PRICE.setdefault(_p["kind"], []).append(_p["unitPrice"] / (_p["packSize"] or 1) if _p["unit"] == "pcs" else _p["unitPrice"])


def _content(rec: dict) -> tuple[str, float]:
    """Unit and amount per sales unit for a real product (L, kg or pcs)."""
    name = f"{rec.get('fi', '')} {rec.get('en', '')}".lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(l|dl|ml)\b", name)
    if m:
        v = float(m.group(1).replace(",", "."))
        v = v / 10 if m.group(2) == "dl" else v / 1000 if m.group(2) == "ml" else v
        mult = re.match(r"\s*(\d+)\s*x\s", rec.get("fi", ""), re.I)
        return "L", round(v * (int(mult.group(1)) if mult else 1), 3)
    if rec.get("kg"):
        return "kg", rec["kg"]
    if rec.get("unit") == "KG":
        return "kg", 1.0
    return "pcs", 1.0


def bridge(gw, rec: dict, kind: str | None, need_by: date, live_data: dict | None = None) -> dict:
    """Register a real product with the catalog and backend; returns the curated-shape product."""
    gtin = f"aimo:{rec['id']}"
    unit, size = _content(rec)
    kind = kind or "other"
    pub = aimo_products.public(rec)
    p = {
        "key": gtin, "gtin": gtin, "aimoSku": rec["id"], "aimoProductId": rec["id"], "realGtin": rec.get("gtin"),
        "name": rec.get("en") or rec.get("fi"), "nameFi": rec.get("fi"), "brand": rec.get("brand") or rec.get("vendor", "").title(),
        "category": KIND_CATEGORY.get(kind, "dry_goods"), "kind": kind, "variant": [], "keywords": [],
        "unit": unit, "packSize": size, "unitsPerCase": 1, "caseQty": size, "currency": "EUR", "priceBasis": f"per {unit}",
        "allergens": pub["contains"], "mayContain": pub["mayContain"], "diet": pub["diet"],
        "certificates": [{"label": x, "issuer": "on pack (GS1 packagingMarkedLabel)", "validUntil": "2099-12-31"} for x in pub["labels"]],
        "origin": {"country": (rec.get("origin") or "").upper(), "supplierId": rec.get("vendor", "")},
        "qualityGrade": 4.0, "carbonClass": None, "shelfLifeDays": 7 if rec.get("temp") in (1, 2, 3, 4) else 180,
        "kgPerUnit": (rec.get("kg") / size) if rec.get("kg") and size else 1.0, "co2eKgPerKg": rec.get("co2"),
        "leadTimeDays": 1, "onTimeRate": rec.get("rel", 0.95), "salesUnit": rec.get("unit"), "source": "valio-aimo",
    }
    price_unit, stock_units, earliest, live = None, None, None, False
    pr, av = (live_data or {}).get("price"), (live_data or {}).get("availability")
    if pr and not pr.get("error") and pr.get("catalogPrice"):
        price_unit, live = pr["catalogPrice"]["value"], True
        cmp_unit = {"KG": "kg", "L": "L"}.get(pr.get("comparisonUnit") or "")
        cmp = (pr.get("comparisonPrice") or {}).get("value")
        if cmp_unit and cmp:  # price per kg / L is official; content per sales unit = sales price / comparison price
            unit, size = cmp_unit, round(price_unit / cmp, 3)
        else:
            unit, size = "pcs", 1.0
        p.update({"unit": unit, "packSize": size, "caseQty": size, "priceBasis": f"per {unit}",
                  "taxRate": (pr.get("tax") or {}).get("taxRate"), "priceValidTo": pr["catalogPrice"].get("validTo")})
    if av is not None:
        lines = av.get("scheduleLines") or []
        line = lines[0] if lines else {}
        amount = line.get("availableAmount", 0) or 0
        if av.get("salesBlock") or line.get("salesBlock") or not line.get("availableDate") or amount <= 0:
            stock_units = 0  # empty schedule, sales block or 0 = cannot be delivered
        else:
            # Terminal products always say 999999 (unknown), some Stock products 9999999999: treat as ample
            stock_units = min(amount, 100000)
            earliest = s2d(line["availableDate"])
        p.update({"logisticModel": av.get("logisticModel"), "closingTime": av.get("closingTime"),
                  "stockKnown": av.get("logisticModel") == "Stock" and 0 < amount < 999999})
    if price_unit is None:
        base = sorted(KIND_PRICE.get(kind, [3.0]))[len(KIND_PRICE.get(kind, [3.0])) // 2]
        price_unit = round(base * size * demo_value(rec["id"], 0.85, 1.2), 2)
    if stock_units is None:
        stock_units = int(demo_value(rec["id"] + "s", 80, 1500))
    size = p["packSize"]
    p["unitPrice"] = round(price_unit / size, 4) if size else price_unit
    p["salesUnitPrice"] = price_unit
    p["livePrice"] = live
    p["kgPerUnit"] = (rec.get("kg") / size) if rec.get("kg") and size else (1.0 if p["unit"] in ("kg", "L") else 0.5)
    catalog.register_real(p)
    gw.backend.register(gtin, p["unitPrice"], stock_units * size, earliest)
    return p


def search_live(gw, text: str, kind: str | None, need_by: date, exclude: list[str], diet: list[str],
                limit: int = 6) -> dict:
    """Real Valio Aimo search for one gap; bridges the top hits.

    Price and availability for all hits come from ONE /api/price and ONE /api/availability call
    (only the narrowed-down products, as the API asks). Products that cannot be delivered are dropped.
    """
    r = aimo_products.search(text, exclude_allergens=exclude, diet=diet, limit=limit)
    ids = [x["productId"] for x in r["products"]]
    client = getattr(gw, "aimo", None)
    prices, avail = {}, {}
    if client and ids:
        prices = client.prices(ids, d2s(need_by))
        avail = client.availability(ids, d2s(need_by))
    out, dropped = [], []
    for pid in ids:
        p = bridge(gw, aimo_products.by_id(pid), kind, need_by,
                   {"price": prices.get(pid), "availability": avail.get(pid)} if (prices or avail) else None)
        if not gw.backend.schedule(p["gtin"]):
            dropped.append(p["name"])
        else:
            out.append(p)
    return {"products": out, "excluded": r["excluded"], "notDeliverable": dropped, "source": "valio-aimo",
            "live": bool(prices)}


def query_fi(need: str) -> str:
    """The real assortment is named in Finnish first; map the few words the index does not know."""
    return need.replace("lactose-free", "laktoositon").replace("lactose free", "laktoositon")


def refresh_curated(gw, need_by: date) -> list[str]:
    """Live mode: curated demo products that mirror a real Valio Aimo product (`aimoId`)
    get their price and availability from the mock API (one batch call each), so a
    recalled favourite is priced and promised on live data, not demo values."""
    client = getattr(gw, "aimo", None)
    if not client:
        return []
    mapped = {p["gtin"]: p["aimoId"] for p in catalog.products() if p.get("aimoId")}
    ids = sorted(set(mapped.values()))
    prices, avail = client.prices(ids, d2s(need_by)), client.availability(ids, d2s(need_by))
    done = []
    for gtin, aid in mapped.items():
        pr, av = prices.get(aid), avail.get(aid)
        if not pr or pr.get("error") or not pr.get("catalogPrice"):
            continue
        sales = pr["catalogPrice"]["value"]
        cmp = (pr.get("comparisonPrice") or {}).get("value")
        per_unit = cmp if cmp else sales / (catalog.by_gtin(gtin)["packSize"] or 1)
        content = sales / cmp if cmp else catalog.by_gtin(gtin)["packSize"]
        lines = (av or {}).get("scheduleLines") or []
        line = lines[0] if lines else {}
        amount = line.get("availableAmount", 0) or 0
        if (av or {}).get("salesBlock") or not line.get("availableDate") or amount <= 0:
            stock, earliest = 0.0, None
        else:
            stock, earliest = min(amount, 100000) * content, s2d(line["availableDate"])
        gw.backend.register(gtin, round(per_unit, 4), round(stock, 1), earliest)
        gw.backend.inbound[gtin] = []
        gw.backend.live[gtin] = {"aimoProductId": aid, "priceValidTo": pr["catalogPrice"].get("validTo")}
        done.append(gtin)
    return done
