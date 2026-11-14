"""Learning signals derived from curated ProcessRecords (+ the buyer's 8-week order history).

Every signal carries its evidence (n, period, processIds). No opaque models:
the planner consumes these numbers through explicit, capped score terms.
"""
from __future__ import annotations

from statistics import median

from . import catalog


def _q(vals, q):
    v = sorted(vals)
    if not v:
        return None
    i = (len(v) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 3)


def weekly_history(buyer: dict) -> dict:
    """gtin -> {median8w, weeks} from the buyer's seeded 8-week history (non-zero weeks)."""
    out = {}
    for key, weeks in buyer.get("history", {}).items():
        p = catalog.by_key(key)
        nz = [w for w in weeks if w > 0]
        if p and nz:
            out[p["gtin"]] = {"median8w": median(nz), "weeks": weeks, "nonZeroWeeks": len(nz)}
    return out


def habitual(buyer: dict, kind: str) -> dict | None:
    """The buyer's usual product for a kind = highest 8-week volume."""
    best, vol = None, 0
    for key, weeks in buyer.get("history", {}).items():
        p = catalog.by_key(key)
        if p and p["kind"] == kind and sum(weeks) > vol:
            best, vol = p, sum(weeks)
    return best


def compute(buyer: dict, records: list[dict], period_from: str | None = None, period_to: str | None = None) -> dict:
    recs = [r for r in records if r["buyerId"] == buyer["id"]
            and (not period_from or r["createdAt"] >= period_from) and (not period_to or r["createdAt"] <= period_to)]
    pairs: dict[tuple, dict] = {}
    changes: dict[str, dict] = {}
    products: dict[str, dict] = {}
    brands: dict[str, dict] = {}
    choices: dict[tuple, dict] = {}
    rules: dict[str, dict] = {}
    percover: dict[tuple, dict] = {}

    for r in recs:
        pid = r["processId"]
        fb = r.get("feedback") or {}
        dec = r.get("decision") or {}
        rejected_gtins = {m["gtin"] for m in dec.get("modifications", []) if m.get("field") == "rejected"}
        for s in r["outcome"].get("substitutions", []):
            k = (s["fromGtin"], s["toGtin"])
            e = pairs.setdefault(k, {"fromGtin": s["fromGtin"], "toGtin": s["toGtin"], "fromName": s["fromName"],
                                     "toName": s["toName"], "n": 0, "accepted": 0, "rejected": 0, "processIds": []})
            acc = fb.get("substituteAccepted")
            if s["toGtin"] in rejected_gtins or r["outcome"]["status"] == "rejected":
                acc = False
            if acc is None:
                continue
            e["n"] += 1
            e["accepted" if acc else "rejected"] += 1
            e["processIds"].append(pid)
            for c in s.get("changes", []):
                ce = changes.setdefault(c, {"change": c, "n": 0, "accepted": 0})
                ce["n"] += 1
                ce["accepted"] += 1 if acc else 0
        if r["outcome"]["status"] in ("ordered", "delivered", "partially_approved"):
            for ln in r.get("lines", []):
                e = products.setdefault(ln["gtin"], {"gtin": ln["gtin"], "name": ln["name"], "brand": ln["brand"],
                                                    "category": ln["category"], "supplierId": ln.get("supplierId"),
                                                    "orders": 0, "qtys": [], "prices": [], "onTimeN": 0, "onTime": 0,
                                                    "fillN": 0, "fillSum": 0.0, "ratings": [], "processIds": []})
                e["orders"] += 1
                e["qtys"].append(ln["qty"])
                e["prices"].append(ln["unitPrice"])
                e["processIds"].append(pid)
                if fb.get("onTime") is not None:
                    e["onTimeN"] += 1
                    e["onTime"] += 1 if fb["onTime"] else 0
                if fb.get("deliveredQty") is not None and r["outcome"].get("qtyOrdered"):
                    e["fillN"] += 1
                    e["fillSum"] += min(1.0, fb["deliveredQty"] / r["outcome"]["qtyOrdered"])
                if fb.get("rating"):
                    e["ratings"].append(fb["rating"])
                b = brands.setdefault(ln["brand"], {"brand": ln["brand"], "orders": 0})
                b["orders"] += 1
        mc = dec.get("manualChoice")
        if mc:
            k = (mc["agentPick"], mc["chosen"])
            e = choices.setdefault(k, {"agentPick": mc["agentPick"], "chosen": mc["chosen"],
                                       "chosenName": catalog.by_gtin(mc["chosen"])["name"],
                                       "agentPickName": catalog.by_gtin(mc["agentPick"])["name"],
                                       "n": 0, "processIds": []})
            e["n"] += 1
            e["processIds"].append(pid)
        for rid in dec.get("ruleIds", []):
            e = rules.setdefault(rid, {"ruleId": rid, "fired": 0, "approved": 0, "rejected": 0, "modified": 0,
                                       "acknowledged": 0, "latencies": [], "processIds": [], "categories": {}})
            e["fired"] += 1
            e["processIds"].append(pid)
            act = dec.get("approverAction")
            if act == "approve":
                e["approved"] += 1
            elif act == "reject":
                e["rejected"] += 1
            elif act in ("modify", "partial"):
                e["modified"] += 1
            elif dec.get("outcome") == "NOTIFY" and not dec.get("manualCorrection") and fb.get("substituteAccepted") is not False:
                e["acknowledged"] += 1
            if dec.get("approvalLatencyMin") is not None:
                e["latencies"].append(dec["approvalLatencyMin"])
            for ln in r.get("lines", []):
                e["categories"][ln["category"]] = e["categories"].get(ln["category"], 0) + 1
        for c in r.get("consumption", []) or []:
            if c.get("perCoverActual") is None:
                continue
            k = (r.get("usageContext", {}).get("template"), c["needGroup"])
            e = percover.setdefault(k, {"template": k[0], "needGroup": k[1], "name": c["name"], "unit": c["unit"],
                                        "planned": [], "actual": [], "dates": [], "processIds": []})
            e["planned"].append(c.get("perCoverPlanned"))
            e["actual"].append(c["perCoverActual"])
            e["dates"].append(r["createdAt"][:10])
            e["processIds"].append(pid)

    def rate(a, n):
        return round(a / n, 3) if n else None

    out_pairs = []
    for e in pairs.values():
        if e["n"] == 0:
            continue
        e["rate"] = rate(e["accepted"], e["n"])
        e["learnedValue"] = round(0.5 + 0.5 * (2 * e["rate"] - 1), 3) if e["n"] >= 2 else 0.5
        out_pairs.append(e)
    out_products = []
    wh = weekly_history(buyer)
    for g, e in products.items():
        e["qtyMedian"] = _q(e["qtys"], .5)
        e["qtyIQR"] = [_q(e["qtys"], .25), _q(e["qtys"], .75)]
        e["priceMedian"] = _q(e["prices"], .5)
        e["priceLast"] = e["prices"][-1]
        e["onTimeRate"] = rate(e["onTime"], e["onTimeN"])
        e["fillRate"] = round(e["fillSum"] / e["fillN"], 3) if e["fillN"] else None
        e["avgRating"] = round(sum(e["ratings"]) / len(e["ratings"]), 2) if e["ratings"] else None
        e["weeklyMedian8w"] = wh.get(g, {}).get("median8w")
        e["processIds"] = e["processIds"][-12:]
        del e["qtys"], e["prices"], e["ratings"], e["fillSum"]
        out_products.append(e)
    for g, h in wh.items():
        if g not in products:
            p = catalog.by_gtin(g)
            out_products.append({"gtin": g, "name": p["name"], "brand": p["brand"], "category": p["category"],
                                 "supplierId": p["origin"]["supplierId"], "orders": h["nonZeroWeeks"],
                                 "weeklyMedian8w": h["median8w"], "onTimeRate": None, "onTimeN": 0,
                                 "fillRate": None, "avgRating": None, "priceMedian": None, "priceLast": None,
                                 "qtyMedian": h["median8w"], "qtyIQR": [None, None], "processIds": []})
    out_rules = []
    for e in rules.values():
        e["medianLatencyMin"] = _q(e["latencies"], .5)
        e["p90LatencyMin"] = _q(e["latencies"], .9)
        del e["latencies"]
        e["processIds"] = e["processIds"][-20:]
        out_rules.append(e)
    out_pc = []
    for e in percover.values():
        e["n"] = len(e["actual"])
        e["perCoverActualMedian"] = _q(e["actual"], .5)
        e["perCoverPlannedMedian"] = _q([x for x in e["planned"] if x is not None], .5)
        out_pc.append(e)
    dates = sorted(r["createdAt"] for r in recs)
    return {
        "buyerId": buyer["id"],
        "period": {"from": dates[0][:10] if dates else None, "to": dates[-1][:10] if dates else None, "processes": len(recs)},
        "substitutionPairs": sorted(out_pairs, key=lambda e: -e["n"]),
        "changeTypes": [dict(e, rate=rate(e["accepted"], e["n"])) for e in changes.values()],
        "products": sorted(out_products, key=lambda e: -e["orders"]),
        "brands": sorted(brands.values(), key=lambda e: -e["orders"]),
        "manualChoices": sorted(choices.values(), key=lambda e: -e["n"]),
        "rules": sorted(out_rules, key=lambda e: e["ruleId"]),
        "perCover": out_pc,
    }


def product_signal(signals: dict | None, gtin: str) -> dict | None:
    if not signals:
        return None
    return next((p for p in signals["products"] if p["gtin"] == gtin), None)


def pair_signal(signals: dict | None, from_gtin: str, to_gtin: str) -> dict | None:
    if not signals:
        return None
    return next((p for p in signals["substitutionPairs"] if p["fromGtin"] == from_gtin and p["toGtin"] == to_gtin), None)


def ever_ordered(buyer: dict, signals: dict | None, gtin: str) -> bool:
    if gtin in weekly_history(buyer):
        return True
    ps = product_signal(signals, gtin)
    return bool(ps and ps.get("orders"))
