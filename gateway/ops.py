"""Valio Aimo operations view: what the agent channel tells a wholesaler that a webshop cannot.

Agents state their need before they order (date, quantity, diet, event), so the gateway sees forward demand,
including the needs it could not meet. Three views, all over the live datasets (analytics/datasets.py) and all
aggregated across customers with k >= 3 buyers per group (smaller groups are suppressed, and nothing can be
grouped by customer, kitchen, agent or approver):

  metrics     channel metrics: autonomous rate, approval rate and wait, re-quote rate, blocked rate, fill rate,
              time to order, refused calls, seller-suggestion acceptance; plus the raw operational counters
  demand      forward demand per need-by day, category or product, for stock and transport planning
  lost_sales  what agents asked for that could not be supplied, and why (assortment and supplier decisions)
"""
from __future__ import annotations

from datetime import date, timedelta

from .analytics import charts, datasets, query
from .playbook.engine import GuardFailed

K = 3
BY = {"day": {"field": "date", "grain": "day"}, "category": "category", "product": "product"}
CHANNEL = ["sessions", "autonomous_rate", "approval_rate", "blocked_rate", "requote_rate", "p50_time_to_order",
           "p90_approval_wait", "guidance_errors", "suggestion_acceptance_rate"]


def _period(gw, frm: str | None, to: str | None, days: int = 14) -> dict:
    today = gw.clock.today()
    return {"from": frm or today.isoformat(), "to": to or (today + timedelta(days=days)).isoformat()}


def _chart(res: dict, kind: str, title: str | None) -> dict | None:
    if not res["rows"]:
        return None
    try:
        return charts.build(res, {"type": kind, **({"title": title} if title else {})})
    except GuardFailed:
        return None


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _day_chart(rows: list[dict]) -> dict | None:
    """Planned need per delivery day: one thin bar per day (<= 24 px, rounded data end), day names on the axis."""
    if not rows:
        return None
    vals = []
    for r in rows:
        d = date.fromisoformat(r["date"])
        vals.append({**r, "day": f"{DAYS[d.weekday()]} {d.day}.{d.month}."})
    qty = {"type": "quantitative", "format": ",.0f"}
    return {"$schema": charts.SCHEMA_URL, "data": {"values": vals}, "width": "container", "height": 200,
            "mark": {"type": "bar", "size": 24, "cornerRadiusEnd": 4},
            "encoding": {"x": {"field": "day", "type": "ordinal", "sort": {"field": "date"}, "title": None, "axis": {"labelAngle": 0}},
                         "y": {"field": "planned_qty", "type": "quantitative", "title": "Units planned"},
                         "tooltip": [{"field": "day", "title": "Delivery day"}, {**qty, "field": "planned_qty", "title": "Planned"},
                                     {**qty, "field": "ordered_qty", "title": "Ordered"}, {**qty, "field": "unmet_qty", "title": "Not met"}]},
            "usermeta": {"chartType": "column"}}


def metrics(gw) -> dict:
    conn = datasets.connect(gw)
    act = query.run(conn, {"dataset": "agent_activity", "measures": CHANNEL}, None, k_anon=K)
    dem = query.run(conn, {"dataset": "demand", "measures": ["fill_rate", "lost_value_eur"]}, None, k_anon=K)
    channel = (act["rows"] or [None])[0]
    if channel is not None and dem["rows"]:
        channel.update(dem["rows"][0])
    return {"kAnonymity": K, "channel": channel,
            "suppressed": not channel,
            "note": None if channel else f"Fewer than {K} customers so far: shown once more customers use agents.",
            "raw": gw.metrics.snapshot(gw)}


def demand(gw, frm: str | None = None, to: str | None = None, by: str = "day") -> dict:
    if by not in BY:
        raise GuardFailed(f"Cannot group forward demand by '{by}'.", fix={"by": list(BY), "why": "never by customer (k-anonymity)"})
    spec = {"dataset": "demand", "measures": ["planned_qty", "ordered_qty", "unmet_qty", "value_eur"], "dimensions": [BY[by]],
            "period": _period(gw, frm, to)}
    if by != "day":
        spec["sort"] = [{"by": "planned_qty", "dir": "desc"}]
        spec["limit"] = 20
    res = query.run(datasets.connect(gw), spec, None, k_anon=K)
    chart = _day_chart(res["rows"]) if by == "day" else _chart(res, "bar", None)
    return {"by": by, "period": res["period"], "kAnonymity": K, "suppressed": res["suppressed"], "columns": res["columns"],
            "rows": res["rows"], "chart": chart,
            "explain": "What agents planned and ordered, by need-by date: next week's need before the orders arrive."}


REASON_TEXT = {"blocked_allergen": "an allergen the kitchen never orders", "not_deliverable": "nothing deliverable",
               "not_by_date": "not by the date needed", "partial": "only part of the amount", "over_limit_rejected": "the OK was declined"}


def lost_sales(gw, frm: str | None = None, to: str | None = None) -> dict:
    p = {"from": frm or date(2026, 1, 1).isoformat(), "to": to or (gw.clock.today() + timedelta(days=60)).isoformat()}
    res = query.run(datasets.connect(gw), {"dataset": "demand", "measures": ["unmet_qty", "lost_value_eur", "lines"],
                                           "dimensions": ["unmet_reason"], "filters": [{"field": "source", "op": "eq", "value": "unmet"}],
                                           "period": p, "sort": [{"by": "lost_value_eur", "dir": "desc"}]}, None, k_anon=K)
    for r in res["rows"]:
        r["why"] = REASON_TEXT.get(r["unmet_reason"], r["unmet_reason"])
    return {"period": res["period"], "kAnonymity": K, "suppressed": res["suppressed"], "columns": res["columns"], "rows": res["rows"],
            "chart": _chart(res, "bar", None),
            "explain": "What agents asked for that Valio Aimo could not supply, and why: input for assortment and supplier decisions."}
