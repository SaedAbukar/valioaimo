"""Ready-made data for the app: Your year (Wrapped), order history, kitchens (CRM)."""
from __future__ import annotations

from . import charts, query, store
from .explain import MONTHS, fmt

PERSONALITY = {
    "Dairy": ("The Cream Team", "Dairy carried your kitchen this year."),
    "Meat": ("The Grill Master", "Meat was the heart of your menus."),
    "Fish": ("The Sea Lover", "Fish led your plates this year."),
    "Fruit & veg": ("The Green Machine", "Fresh produce ruled your kitchen."),
    "Bakery": ("The Early Riser", "Bread and pastry set your mornings."),
    "Dry goods": ("The Pantry Planner", "A well-stocked pantry kept you going."),
    "Plant-based": ("The Plant Pioneer", "Plant-based was your signature."),
}


def _q(gw, bid, spec, site_id=None):
    if site_id:
        name = next(s["name"] for s in gw.buyers[bid]["sites"] if s["id"] == site_id)
        spec = dict(spec, filters=list(spec.get("filters", [])) + [{"field": "site", "op": "eq", "value": name}])
    return query.run(store.conn_for(gw), spec, bid)


def _month_label(m: str) -> str:
    y, mm = m.split("-")
    return f"{MONTHS[int(mm) - 1]} {y}"


def wrapped(gw, bid: str, site_id: str | None = None) -> dict:
    b = gw.buyers[bid]
    where = next((s["name"] for s in b["sites"] if s["id"] == site_id), None) if site_id else b["name"]
    tot = _q(gw, bid, {"measures": ["spend", "orders", "kg"]}, site_id)
    if not tot["rows"] or not tot["rows"][0]["spend"]:
        return {"title": f"{where}: your year", "cards": [{"kind": "empty", "eyebrow": "Your year", "headline": "Your story starts now.",
                                                             "sub": "Order for a few weeks and your year in food appears here.", "numbers": []}]}
    t = tot["rows"][0]
    cards = [{"kind": "intro", "eyebrow": "Your year in food", "headline": f"{where}, what a year.",
              "sub": "Dec 2025 – Nov 2026, every order you placed with Valio Aimo.",
              "numbers": [{"label": "spent", "value": fmt(t["spend"], "EUR")}, {"label": "orders", "value": f"{t['orders']:,}"},
                          {"label": "of food", "value": f"{t['kg'] / 1000:,.1f} t"}]}]
    top = _q(gw, bid, {"measures": ["spend", "orders"], "dimensions": ["product"], "sort": [{"by": "spend", "dir": "desc"}], "limit": 5}, site_id)
    p = top["rows"][0]
    cards.append({"kind": "top_product", "eyebrow": "Your number one", "headline": p["product"],
                  "sub": f"On {p['orders']} orders. Nothing else came close.",
                  "numbers": [{"label": "spent on it", "value": fmt(p["spend"], "EUR")}],
                  "chart": charts.build(top, {"type": "bar"})})
    cats = _q(gw, bid, {"measures": ["spend"], "dimensions": ["category"], "calc": [{"type": "share", "of": "spend"}]}, site_id)
    c0 = cats["rows"][0]
    name, line = PERSONALITY.get(c0["category"], ("The All-Rounder", "A bit of everything, done well."))
    cards.append({"kind": "personality", "eyebrow": "Your kitchen personality", "headline": name, "sub": line,
                  "numbers": [{"label": f"of spend was {c0['category'].lower()}", "value": f"{c0['spend_share']:.0f}%"}],
                  "chart": charts.build(cats, {"type": "donut"})})
    months = _q(gw, bid, {"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}]}, site_id)
    best = max(months["rows"], key=lambda r: r["spend"])
    cards.append({"kind": "busiest_month", "eyebrow": "Your busiest month", "headline": _month_label(best["date"]),
                  "sub": "The kitchen never slept.", "numbers": [{"label": "spent that month", "value": fmt(best["spend"], "EUR")}],
                  "chart": charts.build(months, {"type": "column"})})
    ev = _q(gw, bid, {"measures": ["guests", "spend"], "dimensions": ["event"], "sort": [{"by": "guests", "dir": "desc"}], "limit": 1}, site_id)
    evn = _q(gw, bid, {"measures": ["events"]}, site_id)["rows"]
    if ev["rows"]:
        e = ev["rows"][0]
        cards.append({"kind": "top_event", "eyebrow": "Your biggest night", "headline": e["event"],
                      "sub": f"One of {evn[0]['events']} events you fed this year.",
                      "numbers": [{"label": "guests", "value": f"{e['guests']:,}"}, {"label": "on food", "value": fmt(e["spend"], "EUR")}]})
    waste = _q(gw, bid, {"measures": ["waste_pct"], "dimensions": [{"field": "date", "grain": "month"}]}, site_id)
    w = [r["waste_pct"] for r in waste["rows"]]
    first, last = sum(w[:3]) / 3, sum(w[-3:]) / 3
    drop = (first - last) / first * 100 if first else 0
    cards.append({"kind": "waste", "eyebrow": "Less in the bin", "headline": f"{abs(drop):.0f}% {'less' if drop >= 0 else 'more'} food left over",
                  "sub": "Your last three months compared to your first three.", "tone": "good" if drop >= 0 else "watch",
                  "numbers": [{"label": "left over now", "value": f"{last:.1f}%"}], "chart": charts.build(waste, {"type": "area"})})
    co2 = _q(gw, bid, {"measures": ["co2e"]}, site_id)["rows"][0]["co2e"]
    trips = co2 / 31  # car, Helsinki–Tampere one way ≈ 180 km × 0.17 kg/km
    cards.append({"kind": "co2", "eyebrow": "Your footprint", "headline": f"{co2 / 1000:,.0f} tonnes CO₂e",
                  "sub": f"About {trips:,.0f} car trips from Helsinki to Tampere.",
                  "numbers": [{"label": "per kg of food", "value": f"{co2 / max(1, t['kg']):.1f} kg"}]})
    ot = _q(gw, bid, {"measures": ["on_time_pct"]}, site_id)["rows"][0]["on_time_pct"]
    cards.append({"kind": "on_time", "eyebrow": "Delivered on time", "headline": f"{ot:.0f}% of the time",
                  "sub": "Valio Aimo trucks, rain or shine.", "numbers": []})
    cards.append({"kind": "outro", "eyebrow": "Next year", "headline": "Keep cooking. We'll keep counting.",
                  "sub": "Ask anything about your year in Explore.", "numbers": []})
    return {"title": f"{where}: your year", "cards": cards}


def order_history(gw, bid: str, page: int = 1, size: int = 50, q: str | None = None, site_id: str | None = None,
                  order_type: str | None = None, sort: str = "date", direction: str = "desc") -> dict:
    conn = store.conn_for(gw)
    where, args = ["buyer_id = ?"], [bid]
    if site_id:
        where.append("site_id = ?")
        args.append(site_id)
    if order_type in ("event", "replenishment"):
        where.append("order_type = ?")
        args.append(order_type)
    if q:
        where.append("order_id IN (SELECT order_id FROM line WHERE buyer_id = ? AND (LOWER(event_name) LIKE ? OR LOWER(product) LIKE ? OR LOWER(site_name) LIKE ? OR LOWER(order_id) LIKE ?))")
        like = f"%{q.lower()}%"
        args += [bid, like, like, like, like]
    sort_col = {"date": "date", "total": "total", "lines": "lines", "site": "site_name"}.get(sort, "date")
    sql = (f"SELECT order_id, MIN(date) AS date, site_id, site_name, order_type, MAX(event_name), MAX(event_type), MAX(guests), "
           f"COUNT(*) AS lines, SUM(value_eur) AS total, MIN(on_time), SUM(label='over_ordered') FROM line WHERE {' AND '.join(where)} "
           f"GROUP BY order_id ORDER BY {sort_col} {'ASC' if direction == 'asc' else 'DESC'}, order_id DESC")
    rows = conn.execute(sql, args).fetchall()
    total = len(rows)
    start = (max(1, page) - 1) * size
    out = [{"id": r[0], "key": r[0], "date": r[1], "siteId": r[2], "site": r[3], "type": r[4], "event": r[5], "eventType": r[6],
            "guests": r[7], "lines": r[8], "total": round(r[9], 2), "onTime": bool(r[10]),
            "outcome": "Some left over" if r[11] else "Just right", "status": "done"} for r in rows[start:start + size]]
    return {"orders": out, "total": total, "page": page, "size": size}


def kitchens(gw, bid: str) -> dict:
    b = gw.buyers[bid]
    m, _ = gw.mandate_check(bid)
    from ..playbook import recall
    mem = recall.memory(gw, bid)
    from .. import catalog
    sites = []
    for s in b["sites"]:
        trend = _q(gw, bid, {"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}]}, s["id"])["rows"]
        recent = _q(gw, bid, {"measures": ["spend", "orders", "waste_pct", "on_time_pct"], "period": "last_3_months"}, s["id"])["rows"]
        month = _q(gw, bid, {"measures": ["spend", "orders"], "period": "last_30_days"}, s["id"])["rows"]
        r3 = recent[0] if recent else {}
        sites.append({"id": s["id"], "name": s["name"], "type": s["type"], "address": s["address"], "lead": s["lead"],
                      "spendMonth": (month[0]["spend"] if month else 0) or 0, "ordersMonth": (month[0]["orders"] if month else 0) or 0,
                      "wastePct": r3.get("waste_pct"), "onTimePct": r3.get("on_time_pct"),
                      "trend": [round(r["spend"]) for r in trend] if trend else [], "deliveryDays": ["Mon", "Tue", "Wed", "Thu", "Fri"]
                      if bid == "BUY-POHJOLA" else ["Mon", "Wed", "Fri"]})
    return {"org": {"id": bid, "name": b["name"], "segment": b["segment"], "admin": b["admin"],
                    "approvers": b["approvers"], "creditLimit": b["creditLimitEUR"], "openInvoices": b["openInvoicesEUR"]},
            "sites": sites,
            "favourites": [{"name": catalog.by_key(f["key"])["name"], "pinned": bool(f.get("pinned"))} for f in mem["favourites"]],
            "limits": [{"label": "Per order", "value": m["limits"]["perOrderEUR"]}, {"label": "Per event", "value": m["limits"].get("perEventEUR")},
                       {"label": "Per month", "value": m["limits"]["perMonthEUR"]}],
            "allergens": m["hardExclusions"]["allergens"], "liveApi": bool(gw.aimo)}


def order_detail(gw, bid: str, order_id: str) -> dict:
    rows = store.conn_for(gw).execute(
        "SELECT product, category, qty, unit, value_eur, label, on_time, date, site_name, event_name FROM line "
        "WHERE buyer_id = ? AND order_id = ? ORDER BY value_eur DESC", [bid, order_id]).fetchall()
    return {"id": order_id, "lines": [{"product": r[0], "category": r[1], "qty": r[2], "unit": r[3], "value": r[4],
                                       "outcome": "Just right" if r[5] == "right_sized" else "Some left over", "onTime": bool(r[6])} for r in rows],
            "date": rows[0][7] if rows else None, "site": rows[0][8] if rows else None, "event": rows[0][9] if rows else None}
