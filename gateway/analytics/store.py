"""A year of order history per site, generated deterministically and loaded into SQLite.

One denormalised fact table `line` (one row per ordered product line) is what the
analytics tools query. Everything is seeded (random.Random(2026)) so charts, tests
and the recorded demo are repeatable. Synthetic data on the curated demo assortment.
"""
from __future__ import annotations

import contextvars
import json
import math
import random
import sqlite3
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from .. import catalog

DATA = Path(__file__).resolve().parent.parent / "data"
END = date(2026, 11, 12)          # day before the demo clock
START = date(2025, 12, 1)         # 12 calendar months: Dec 2025 – Nov 2026 (to date)
CATEGORY_LABEL = {"dairy": "Dairy", "plant_based": "Plant-based", "produce": "Fruit & veg", "meat": "Meat",
                  "fish": "Fish", "bakery": "Bakery", "dry_goods": "Dry goods"}
EVENT_LABEL = {"gala": "Gala", "christmas_party": "Christmas party", "wedding": "Wedding", "conference": "Conference",
               "birthday": "Birthday", "lunch": "Lunch", "breakfast": "Breakfast"}
# event menus (recipe ids) per type; guests range
EVENT_MENUS = {
    "gala": (["salmon_starter", "beef_tenderloin", "choc_mousse", "bread_basket", "coffee_service"], (120, 200)),
    "christmas_party": (["kinkku", "rosolli", "lanttulaatikko", "riisipuuro", "coffee_service"], (80, 160)),
    "wedding": (["shrimp_skagen", "pikeperch_main", "strawberry_cream", "bread_basket", "coffee_service"], (60, 140)),
    "conference": (["caesar_salad", "chicken_curry", "fruit_platter", "coffee_service"], (50, 220)),
    "birthday": (["lohikeitto", "berry_pie", "coffee_service"], (30, 80)),
    "lunch": (["meatballs", "mashed_potatoes", "green_salad"], (40, 120)),
}

# Queryable fields. The query compiler only accepts these names (no raw SQL from callers).
SCHEMA = {
    "dimensions": {
        "date": {"label": "Date", "type": "time", "sql": "date"},
        "weekday": {"label": "Weekday", "type": "category", "sql": "weekday"},
        "site": {"label": "Kitchen", "type": "category", "sql": "site_name"},
        "category": {"label": "Category", "type": "category", "sql": "category"},
        "product": {"label": "Product", "type": "category", "sql": "product"},
        "brand": {"label": "Brand", "type": "category", "sql": "brand"},
        "event_type": {"label": "Event type", "type": "category", "sql": "event_type"},
        "event": {"label": "Event", "type": "category", "sql": "event_name"},
        "order_type": {"label": "Order type", "type": "category", "sql": "order_type"},
        "outcome": {"label": "How it went", "type": "category", "sql": "label"},
        "temperature": {"label": "Storage", "type": "category", "sql": "temp"},
    },
    "measures": {
        "spend": {"label": "Spend", "unit": "EUR", "sql": "SUM(value_eur)"},
        "waste": {"label": "Food left over", "unit": "EUR", "sql": "SUM(waste_eur)"},
        "waste_pct": {"label": "Left over (share)", "unit": "%", "sql": "100.0*SUM(waste_eur)/NULLIF(SUM(value_eur),0)"},
        "co2e": {"label": "Carbon footprint", "unit": "kg CO2e", "sql": "SUM(co2e_kg)"},
        "kg": {"label": "Weight", "unit": "kg", "sql": "SUM(kg)"},
        "quantity": {"label": "Quantity", "unit": "units", "sql": "SUM(qty)"},
        "orders": {"label": "Orders", "unit": "count", "sql": "COUNT(DISTINCT order_id)"},
        "lines": {"label": "Order lines", "unit": "count", "sql": "COUNT(*)"},
        "events": {"label": "Events", "unit": "count", "sql": "COUNT(DISTINCT event_id)"},
        "guests": {"label": "Guests", "unit": "count", "sql": "SUM(DISTINCT CASE WHEN event_id IS NOT NULL THEN guests END)"},
        "on_time_pct": {"label": "On time", "unit": "%", "sql": "100.0*AVG(on_time)"},
        "right_sized_pct": {"label": "Just right", "unit": "%", "sql": "100.0*AVG(label='right_sized')"},
        "avg_price": {"label": "Average price", "unit": "EUR/unit", "sql": "SUM(value_eur)/NULLIF(SUM(qty),0)"},
    },
    "timeGrains": ["day", "week", "month", "quarter"],
    "period": {"from": START.isoformat(), "to": END.isoformat()},
}


def all_fields() -> dict:
    """Labels of every dimension and measure across datasets (charts and explanations look names up here)."""
    from .datasets import ACTIVITY_SCHEMA, DEMAND_SCHEMA
    out = {"dimensions": {}, "measures": {}}
    for sch in (ACTIVITY_SCHEMA, DEMAND_SCHEMA, SCHEMA):  # orders last: its labels win on shared names
        for k in out:
            out[k].update(sch[k])
    return out


def _buyers() -> list[dict]:
    return json.loads((DATA / "buyers.json").read_text())["buyers"]


def _recipes() -> dict:
    return {r["id"]: r for r in json.loads((DATA / "recipes.json").read_text())["recipes"]}


@lru_cache(maxsize=512)
def _product_for(need: str) -> dict | None:
    n = catalog.resolve_need(need)
    return catalog.by_gtin(n["candidates"][0]) if n["candidates"] else None


@lru_cache(maxsize=1)
def generate() -> list[dict]:
    """All history lines, deterministic."""
    rnd = random.Random(2026)
    recipes = _recipes()
    rows: list[dict] = []
    n_order = 0
    for b in _buyers():
        prefix = b["id"].split("-")[1][:3]
        for site in b["sites"]:
            if not b["history"]:
                continue
            day = START
            while day <= END:
                t = (day - START).days / (END - START).days  # 0 -> 1 over the year
                season = 1 + 0.18 * math.cos((day.timetuple().tm_yday - 350) / 365 * 2 * math.pi)  # busier around Christmas
                waste_base = 0.11 - 0.05 * t if b["id"] == "BUY-POHJOLA" else 0.07 - 0.02 * t
                # replenishment: hotels every weekday, others Mon / Wed / Fri
                days = (0, 1, 2, 3, 4) if b["id"] == "BUY-POHJOLA" else (0, 2, 4)  # hotels order every weekday
                if day.weekday() in days:
                    n_order += 1
                    oid = f"{prefix}-{n_order}"
                    for key, weeks in b["history"].items():
                        p = catalog.by_key(key)
                        base = (sum(weeks) / len(weeks)) / len(days) * site["scale"] * season
                        if base <= 0 or rnd.random() < 0.12:
                            continue
                        qty = max(p["caseQty"], round(base * rnd.uniform(0.75, 1.25) / p["caseQty"]) * p["caseQty"])
                        rows.append(_line(rnd, oid, "replenishment", day, b, site, p, qty, waste_base, t, None))
                # events, mostly Fri/Sat
                if b["id"] == "BUY-POHJOLA" and day.weekday() in (4, 5) and rnd.random() < 0.42 * site["scale"] * season:
                    et = rnd.choice(["christmas_party"] * 4 + ["gala"] * 2 + ["conference"] * 2 + ["birthday", "lunch"]) \
                        if day.month in (11, 12) else rnd.choice(["gala", "wedding", "wedding", "conference", "conference", "birthday", "lunch"]
                                                                if day.month in (5, 6, 7, 8) else ["gala", "conference", "conference", "birthday", "lunch"])
                    menu, (lo, hi) = EVENT_MENUS[et]
                    guests = rnd.randint(lo, hi)
                    n_order += 1
                    oid = f"{prefix}-{n_order}"
                    ev = {"id": f"EV-{n_order}", "type": et, "name": f"{EVENT_LABEL[et]} {day.day}.{day.month}. {site['name'].split()[-1]}", "guests": guests}
                    need: dict[str, float] = {}
                    for rid in menu:
                        for ing, qpp, _unit, yld, _label in recipes[rid]["ing"]:
                            need[ing] = need.get(ing, 0) + guests * qpp / (yld or 1) * 1.08
                    for ing, q in need.items():
                        p = _product_for(ing)
                        if not p:
                            continue
                        qty = max(p["caseQty"], math.ceil(q / p["caseQty"]) * p["caseQty"])
                        rows.append(_line(rnd, oid, "event", day - timedelta(days=1), b, site, p, qty, waste_base + 0.03, t, ev))
                day += timedelta(days=1)
    return rows


def _line(rnd, oid, otype, day, b, site, p, qty, waste_base, t, ev) -> dict:
    price = p["unitPrice"] * (1 + 0.05 * math.sin(day.timetuple().tm_yday / 58) + 0.03 * t) * rnd.uniform(0.97, 1.03)
    value = qty * price
    used = min(1.0, max(0.55, 1 - rnd.gauss(waste_base, 0.05)))
    if p["key"] == "cream_whip_kaarna" and ev:
        used = min(used, 0.84)  # the cream story: events keep over-ordering cream
    kg = qty * (p.get("kgPerUnit") or 1)
    return {"order_id": oid, "order_type": otype, "buyer_id": b["id"], "site_id": site["id"], "site_name": site["name"],
            "date": day.isoformat(), "month": day.strftime("%Y-%m"), "weekday": day.strftime("%a"),
            "event_id": ev["id"] if ev else None, "event_type": EVENT_LABEL[ev["type"]] if ev else None,
            "event_name": ev["name"] if ev else None, "guests": ev["guests"] if ev else None,
            "product": p["name"], "product_key": p["key"], "category": CATEGORY_LABEL.get(p["category"], p["category"]),
            "brand": p["brand"], "temp": "Chilled" if p.get("shelfLifeDays", 365) <= 21 else "Ambient & frozen",
            "qty": round(qty, 3), "unit": p["unit"], "unit_price": round(price, 4), "value_eur": round(value, 2),
            "kg": round(kg, 2), "co2e_kg": round(kg * (p.get("co2eKgPerKg") or 0), 2),
            "on_time": 1 if rnd.random() < p.get("onTimeRate", 0.95) else 0,
            "used_pct": round(used, 3), "waste_eur": round(value * (1 - used), 2),
            "label": "right_sized" if used >= 0.9 else "over_ordered"}


COLUMNS = ["order_id", "order_type", "buyer_id", "site_id", "site_name", "date", "month", "weekday", "event_id",
           "event_type", "event_name", "guests", "product", "product_key", "category", "brand", "temp", "qty", "unit",
           "unit_price", "value_eur", "kg", "co2e_kg", "on_time", "used_pct", "waste_eur", "label"]


def load(gw=None) -> sqlite3.Connection:
    """In-memory SQLite with the `line` fact table (read-only use)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(f"CREATE TABLE line ({', '.join(COLUMNS)})")
    conn.executemany(f"INSERT INTO line VALUES ({', '.join('?' * len(COLUMNS))})", [tuple(r[c] for c in COLUMNS) for r in generate()])
    for c in ("buyer_id", "site_id", "month", "date", "event_id"):
        conn.execute(f"CREATE INDEX ix_{c} ON line({c})")
    conn.commit()
    return conn


# Which order data the insights read: "demo" = the generated year above; "live" = only the orders placed through
# this gateway (chat, Agent mode, MCP and REST agents), so a demo can start empty and fill up as people order.
SOURCE: contextvars.ContextVar[str] = contextvars.ContextVar("insight_source", default="demo")
LIVE_PERIOD = (date(2026, 11, 1), date(2026, 12, 31))  # the demo clock runs in Nov 2026; deliveries land within weeks


def live_rows(gw) -> list[dict]:
    """One row per ordered line, from the gateway's own orders (amended orders count once, as their latest version)."""
    from .. import catalog
    rows = []
    for o in list(gw.orders.values()):
        s = gw.engine.sessions.get(o["sessionId"])
        if not s or o.get("status") not in ("ordered", "delivered", "done"):
            continue
        b = gw.buyers[s["buyerId"]]
        site = b.get("site") or b["sites"][0]
        ev = (s["data"].get("brief") or {}).get("event")
        usage = {u["need"]: u.get("usage", 1) for u in (s["data"].get("usage") or {}).get("lines", [])}
        for ln in o["lines"]:
            p = catalog.by_gtin(ln["gtin"]) or {}
            day = date.fromisoformat(ln["deliveryDate"])
            line = next((l for l in (s["data"].get("plan") or {}).get("lines", []) if l["gtin"] == ln["gtin"]), {})
            used = min(1.0, usage.get(line.get("need"), 1.0))
            kg = ln["qty"] * (p.get("kgPerUnit") or 1)
            rows.append({
                "order_id": o["orderId"], "order_type": "event" if ev else "replenishment", "buyer_id": b["id"],
                "site_id": site.get("id"), "site_name": site.get("name"), "date": day.isoformat(), "month": day.strftime("%Y-%m"),
                "weekday": day.strftime("%a"), "event_id": s["sessionId"] if ev else None,
                "event_type": EVENT_LABEL.get(ev.get("type"), ev.get("typeLabel")) if ev else None,
                "event_name": ev.get("name") if ev else None, "guests": ev.get("guests") if ev else None,
                "product": ln["name"], "product_key": p.get("key", ln["gtin"]),
                "category": CATEGORY_LABEL.get(p.get("category"), p.get("category") or "Other"), "brand": p.get("brand"),
                "temp": "Chilled" if p.get("shelfLifeDays", 365) <= 21 else "Ambient & frozen",
                "qty": ln["qty"], "unit": ln["unit"], "unit_price": ln["unitPrice"], "value_eur": ln["lineTotal"],
                "kg": round(kg, 2), "co2e_kg": round(kg * (p.get("co2eKgPerKg") or 0), 2), "on_time": 1,
                "used_pct": round(used, 3), "waste_eur": round(ln["lineTotal"] * (1 - used), 2),
                "label": "right_sized" if used >= 0.9 else "over_ordered"})
    return rows


def live_conn(gw) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(f"CREATE TABLE line ({', '.join(COLUMNS)})")
    conn.executemany(f"INSERT INTO line VALUES ({', '.join('?' * len(COLUMNS))})", [tuple(r[c] for c in COLUMNS) for r in live_rows(gw)])
    conn.commit()
    return conn


def conn_for(gw) -> sqlite3.Connection:
    if SOURCE.get() == "live":
        return live_conn(gw)  # rebuilt per question: it is small and always current
    if not hasattr(gw, "history_db"):
        gw.history_db = load(gw)
    return gw.history_db


def using(source: str | None, fn, *a, **k):
    """Run fn with the insight data source set (used by the routes, inside the worker thread)."""
    tok = SOURCE.set("live" if source == "live" else "demo")
    try:
        return fn(*a, **k)
    finally:
        SOURCE.reset(tok)
