"""Insights and Settings for the app, in plain kitchen language.

Statements are computed from the buyer's memory (outcome labels per line) and
the board; the weekly 'left over' series is seeded demo history plus any usage
recorded in this run.
"""
from __future__ import annotations

from .. import catalog
from . import recall as R

# share of ordered food that was left over, per week (seeded, 8 weeks to 13 Nov 2026)
WASTE_SERIES = {"BUY-POHJOLA": [9.8, 9.1, 8.7, 8.9, 7.6, 7.2, 6.4, 5.9],
                "BUY-KOULU": [6.1, 6.0, 5.8, 5.9, 5.5, 5.2, 5.4, 5.0],
                "BUY-KAARI": [4.2, 4.0, 4.4, 4.1, 3.9, 3.8, 3.6, 3.7],
                "BUY-UUSI": []}
WEEKS = ["21.9.", "28.9.", "5.10.", "12.10.", "19.10.", "26.10.", "2.11.", "9.11."]


def for_buyer(gw, bid: str) -> dict:
    mem = R.memory(gw, bid)
    lines = [l for o in mem["orders"] for l in o["lines"]]
    right = sum(1 for l in lines if l.get("label") in ("right_sized", "good_substitute"))
    series = WASTE_SERIES.get(bid, [])
    statements = []
    if len(series) >= 8:
        a, b = sum(series[:4]) / 4, sum(series[4:]) / 4
        statements.append({"id": "waste", "tone": "good" if b < a else "watch",
                           "text": "You threw away less this month." if b < a else "A bit more was left over this month.",
                           "detail": f"About {round(abs(a - b) / a * 100)}% less left over than the month before." if b < a else ""})
    if lines:
        statements.append({"id": "right", "tone": "good", "text": f"{round(right / len(lines) * 100)}% of what you ordered was just right.",
                           "detail": "Counted from what your team tapped in “How did it go?”."})
    auto = sum(1 for s in gw.engine.sessions.values() if s["buyerId"] == bid and (s["data"].get("decision") or {}).get("decision") in ("auto", "tell_me"))
    total = sum(1 for s in gw.engine.sessions.values() if s["buyerId"] == bid and s["data"].get("decision"))
    statements.append({"id": "ok", "tone": "neutral",
                       "text": "Most orders went through without waiting for an OK." if not total or auto / total >= 0.5 else "Many orders needed an OK this week.",
                       "detail": "Orders inside your limits go straight to Valio Aimo."})
    favs = [catalog.by_key(f["key"])["name"] for f in mem["favourites"]][:3]
    if favs:
        statements.append({"id": "fav", "tone": "neutral", "text": f"Your favourites are used first: {favs[0]}" + (" and more." if len(favs) > 1 else "."),
                           "detail": "Change them in Settings."})
    tips = []
    for et in sorted({o.get("eventType") for o in mem["orders"] if o.get("eventType")}):
        for t in R.tips(gw, bid, et):
            tips.append({"text": f"Your last 3 {et}s had {t['need']} left over. Order {t['cutPct']}% less next time?", "tipId": t["tipId"]})
    if bid == "BUY-POHJOLA" and not tips:
        tips.append({"text": "Your salmon portions are spot on. Keep the same amount for the next gala.", "tipId": None})
    return {"statements": statements[:4], "chart": {"title": "Food left over", "unit": "%", "labels": WEEKS[-len(series):] if series else [],
                                                    "values": series}, "tips": tips[:3]}


def settings(gw, bid: str) -> dict:
    b = gw.buyers[bid]
    m, _ = gw.mandate_check(bid)
    mem = R.memory(gw, bid)
    lim = m["limits"]
    allergen_words = {"nuts": "Nuts", "peanuts": "Peanuts", "milk": "Milk", "sesame": "Sesame", "fish": "Fish", "eggs": "Eggs"}
    return {
        "buyer": {"id": bid, "name": b["name"], "site": b["site"]["name"], "segment": b["segment"]},
        "buyers": [{"id": x["id"], "name": x["name"], "segment": x["segment"]} for x in gw.buyers.values()],
        "favourites": [{"name": catalog.by_key(f["key"])["name"], "pinned": bool(f.get("pinned"))} for f in mem["favourites"]],
        "limits": [{"label": "Per order", "value": lim["perOrderEUR"]}, {"label": "Per event", "value": lim.get("perEventEUR")},
                   {"label": "Per month", "value": lim["perMonthEUR"]}],
        "allergens": [allergen_words.get(a, a.title()) for a in m["hardExclusions"]["allergens"]],
        "approvers": [{"name": a["name"], "role": a["role"]} for a in b["approvers"]],
        "liveApi": bool(gw.aimo),
    }
