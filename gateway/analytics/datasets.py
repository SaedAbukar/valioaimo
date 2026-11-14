"""Live datasets built from the gateway's own records (sessions, audit, orders, seller feedback).

agent_activity  one row per playbook session (and one per seller-suggestion decision): who drove it, the
                gateway's decision, re-quotes, refused calls, time to order, approval wait, live prices.
demand          one row per planned or ordered line, plus one row per need the gateway could not meet and why.

Both are queried through the same query compiler as the order history (query.run with spec.dataset), so the
insight rails, charts and explanations work unchanged. Buyers see only their own rows; Valio Aimo operations
see all buyers, aggregated with k >= 3 buyers per group (query.run k_anon).
"""
from __future__ import annotations

import sqlite3
from datetime import date

from .. import catalog
from ..util import parse_dt

ACTIVITY_SCHEMA = {
    "dimensions": {
        "date": {"label": "Date", "type": "time", "sql": "date"},
        "buyer": {"label": "Customer", "type": "category", "sql": "buyer", "identifying": True},
        "site": {"label": "Kitchen", "type": "category", "sql": "site", "identifying": True},
        "agent": {"label": "Agent", "type": "category", "sql": "agent", "identifying": True},
        "channel": {"label": "Channel", "type": "category", "sql": "channel"},
        "decision": {"label": "Gateway decision", "type": "category", "sql": "decision"},
        "top_rule": {"label": "Main rule", "type": "category", "sql": "top_rule"},
        "approver": {"label": "Approver", "type": "category", "sql": "approver", "identifying": True},
        "kind": {"label": "Row kind", "type": "category", "sql": "kind"},
    },
    "measures": {
        "sessions": {"label": "Sessions", "unit": "count", "sql": "SUM(kind='session')"},
        "autonomous_rate": {"label": "Ordered without a human", "unit": "%",
                            "sql": "100.0*AVG(CASE WHEN kind='session' AND decision IS NOT NULL THEN decision IN ('auto','tell_me') END)"},
        "approval_rate": {"label": "Needed an OK", "unit": "%",
                          "sql": "100.0*AVG(CASE WHEN kind='session' AND decision IS NOT NULL THEN decision='needs_ok' END)"},
        "blocked_rate": {"label": "Could not order", "unit": "%",
                         "sql": "100.0*AVG(CASE WHEN kind='session' AND decision IS NOT NULL THEN decision='blocked' END)"},
        "requote_rate": {"label": "Re-quoted", "unit": "%", "sql": "100.0*AVG(CASE WHEN kind='session' THEN requotes>0 END)"},
        "p50_time_to_order": {"label": "Time to order, median", "unit": "s", "sql": "p50(time_to_order_s)"},
        "p90_approval_wait": {"label": "Approval wait, 90th percentile", "unit": "s", "sql": "p90(approval_wait_s)"},
        "guidance_errors": {"label": "Refused calls (409 + 422)", "unit": "count", "sql": "SUM(c409 + c422)"},
        "orders": {"label": "Orders", "unit": "count", "sql": "SUM(order_total IS NOT NULL)"},
        "order_value": {"label": "Order value", "unit": "EUR", "sql": "SUM(order_total)"},
        "live_price_share": {"label": "Priced live", "unit": "%", "sql": "100.0*AVG(live_price_share)"},
        "suggestion_acceptance_rate": {"label": "Seller suggestions accepted", "unit": "%",
                                       "sql": "100.0*AVG(CASE WHEN kind='suggestion' THEN suggestion='accepted' END)"},
    },
}
DEMAND_SCHEMA = {
    "dimensions": {
        "date": {"label": "Need-by date", "type": "time", "sql": "date"},
        "category": {"label": "Category", "type": "category", "sql": "category"},
        "product": {"label": "Product", "type": "category", "sql": "product"},
        "source": {"label": "Source", "type": "category", "sql": "source"},
        "unmet_reason": {"label": "Why not met", "type": "category", "sql": "unmet_reason"},
        "buyer": {"label": "Customer", "type": "category", "sql": "buyer", "identifying": True},
        "site": {"label": "Kitchen", "type": "category", "sql": "site", "identifying": True},
    },
    "measures": {
        "planned_qty": {"label": "Planned", "unit": "units", "sql": "SUM(CASE WHEN source IN ('planned','ordered') THEN qty END)"},
        "ordered_qty": {"label": "Ordered", "unit": "units", "sql": "SUM(CASE WHEN source='ordered' THEN qty END)"},
        "unmet_qty": {"label": "Not met", "unit": "units", "sql": "SUM(CASE WHEN source='unmet' THEN qty END)"},
        "fill_rate": {"label": "Fill rate", "unit": "%",
                      "sql": "100.0*SUM(CASE WHEN source='ordered' THEN qty ELSE 0 END)/NULLIF(SUM(qty),0)"},
        "lost_value_eur": {"label": "Lost sales", "unit": "EUR", "sql": "SUM(CASE WHEN source='unmet' THEN value_eur END)"},
        "value_eur": {"label": "Value", "unit": "EUR", "sql": "SUM(value_eur)"},
        "lines": {"label": "Lines", "unit": "count", "sql": "COUNT(*)"},
    },
}
WIDE = (date(2026, 1, 1), date(2027, 12, 31))
DATASETS = {
    "agent_activity": {"table": "activity", "schema": ACTIVITY_SCHEMA, "period": WIDE, "buyerCol": "buyer"},
    "demand": {"table": "demand", "schema": DEMAND_SCHEMA, "period": WIDE, "buyerCol": "buyer"},
}
UNMET_REASONS = ["not_deliverable", "not_by_date", "partial", "blocked_allergen", "over_limit_rejected"]


def _secs(a: str | None, b: str | None) -> float | None:
    return (parse_dt(b) - parse_dt(a)).total_seconds() if a and b else None


def agent_activity(gw) -> list[dict]:
    rejected: dict[str, list[dict]] = {}
    for e in gw.audit.rejections():
        if e.get("traceId"):
            rejected.setdefault(e["traceId"], []).append(e)
    rows = []
    for s in gw.engine.sessions.values():
        d = s["data"]
        chk = d.get("decision") or {}
        order = d.get("order")
        appr = d.get("approval") or {}
        rej = rejected.get(s["sessionId"], [])
        offers = (d.get("plan") or {}).get("offers") or []
        buyer = gw.buyers.get(s["buyerId"], {})
        rows.append({
            "kind": "session", "buyer": s["buyerId"], "site": buyer.get("site", {}).get("name"),
            "agent": s["agentId"].split(":")[-1], "channel": s.get("channel", "api"), "date": s["createdAt"][:10],
            "decision": chk.get("decision"), "top_rule": ((chk.get("internal") or {}).get("ruleIds") or [None])[0],
            "requotes": sum(1 for e in rej if e["refs"].get("guard") in ("price_locked", "stock_changed")),
            "c409": sum(1 for e in rej if e["refs"].get("status") == 409),
            "c422": sum(1 for e in rej if e["refs"].get("status") == 422),
            "time_to_order_s": _secs(s["createdAt"], order["placedAt"]) if order else None,
            "approval_wait_s": _secs(appr.get("requestedAt"), appr.get("decidedAt")),
            "approver": appr.get("decidedBy"), "approved": {"approved": 1, "rejected": 0}.get(appr.get("status")),
            "order_total": order["total"] if order else None,
            "live_price_share": (sum(o.get("priceSource") == "valio-aimo-mock-api" for o in offers) / len(offers)) if offers else None,
            "suggestion": None})
    for sg in gw.seller_state["suggestions"].values():
        if sg["status"] in ("accepted", "dismissed"):
            buyer = gw.buyers.get(sg["buyerId"], {})
            rows.append({"kind": "suggestion", "buyer": sg["buyerId"], "site": buyer.get("site", {}).get("name"),
                         "agent": "valio-aimo-seller", "channel": "seller", "date": sg["decidedAt"][:10], "decision": None,
                         "top_rule": None, "requotes": 0, "c409": 0, "c422": 0, "time_to_order_s": None, "approval_wait_s": None,
                         "approver": None, "approved": None, "order_total": None, "live_price_share": None,
                         "suggestion": sg["status"]})
    return rows


def _price(gtin: str | None, gw) -> float:
    if gtin and gtin in gw.backend.prices:
        return gw.backend.price(gtin)
    return 0.0


def demand(gw) -> list[dict]:
    rows = []
    for s in gw.engine.sessions.values():
        d = s["data"]
        plan = d.get("plan")
        if not plan:
            continue
        buyer = gw.buyers.get(s["buyerId"], {})
        base = {"buyer": s["buyerId"], "site": buyer.get("site", {}).get("name")}
        order = d.get("order")
        rejected = (d.get("approval") or {}).get("status") == "rejected"
        for l in plan["lines"]:
            p = catalog.by_gtin(l["gtin"]) or {}
            src = "ordered" if order else "unmet" if rejected else "planned"
            rows.append({**base, "date": l["deliveryDate"], "category": p.get("category", "other"), "product": l["name"],
                         "qty": l["qty"], "value_eur": l["lineTotal"], "source": src,
                         "unmet_reason": "over_limit_rejected" if src == "unmet" else None})
        nb = plan["lines"][0]["deliveryDate"] if plan["lines"] else (d.get("brief") or {}).get("when", {}).get("value")
        for cd in plan.get("cantDo") or []:
            alt = cd.get("alternative") or {}
            p = catalog.by_gtin(alt.get("productId")) or {}
            reason = "blocked_allergen" if cd.get("blockedProduct") and cd.get("allergen") else \
                "not_by_date" if cd.get("lateProduct") else "not_deliverable"
            rows.append({**base, "date": nb, "category": p.get("category", "other"), "product": cd.get("blockedProduct") or cd["need"],
                         "qty": cd["qty"], "value_eur": round(cd["qty"] * (alt.get("unitPrice") or _price(alt.get("productId"), gw)), 2),
                         "source": "unmet", "unmet_reason": reason})
        cant = {cd["need"] for cd in plan.get("cantDo") or []}
        brief = d.get("brief") or {}
        for req in ([] if brief.get("event") else brief.get("lines", [])):  # covered less than asked: the rest is unmet
            need = req.get("need") or req["text"]
            got = sum(l["qty"] for l in plan["lines"] if l.get("need") == need)
            if need not in cant and got and got + 1e-6 < req["qty"]:
                rows.append({**base, "date": nb, "category": "other", "product": need, "qty": round(req["qty"] - got, 3),
                             "value_eur": 0.0, "source": "unmet", "unmet_reason": "partial"})
    return rows


def _pctl(q: float):
    class Agg:
        def __init__(self):
            self.xs = []

        def step(self, v):
            if v is not None:
                self.xs.append(v)

        def finalize(self):
            if not self.xs:
                return None
            xs = sorted(self.xs)
            return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]
    return Agg


def connect(gw) -> sqlite3.Connection:
    """A fresh in-memory SQLite with both live tables (they are small; rebuilt per question)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.create_aggregate("p50", 1, _pctl(0.5))
    conn.create_aggregate("p90", 1, _pctl(0.9))
    for table, rows, cols in (
            ("activity", agent_activity(gw), ["kind", "buyer", "site", "agent", "channel", "date", "decision", "top_rule", "requotes",
                                              "c409", "c422", "time_to_order_s", "approval_wait_s", "approver", "approved",
                                              "order_total", "live_price_share", "suggestion"]),
            ("demand", demand(gw), ["buyer", "site", "date", "category", "product", "qty", "value_eur", "source", "unmet_reason"])):
        conn.execute(f"CREATE TABLE {table} ({', '.join(cols)})")
        conn.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", [tuple(r.get(c) for c in cols) for r in rows])
    conn.commit()
    return conn
