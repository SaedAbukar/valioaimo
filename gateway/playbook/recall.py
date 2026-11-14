"""Step 2 · Recall — look in the buyer's own memory first, in a fixed order:

  (a) favourites and pinned products for each need
  (b) past successful orders of the same kind (labels perfect_order,
      right_sized, good_substitute)
  (c) learned quantities per guest from similar events
  (d) standing orders
  (e) leftovers in stock

Each matched line records its source and a confidence (high / medium / low).
Needs nothing in memory covers become gaps for Step 3 (Discover).
"""
from __future__ import annotations

import json
import statistics
from functools import lru_cache
from pathlib import Path

from .. import catalog

DATA = Path(__file__).resolve().parent.parent / "data"
GOOD = ("perfect_order", "right_sized", "good_substitute")
RECALL_ORDER = ["favourites", "similar_orders", "learned_quantities", "standing_orders", "leftovers"]


@lru_cache(maxsize=1)
def seed() -> dict:
    return json.loads((DATA / "history.json").read_text())["buyers"]


def memory(gw, bid: str) -> dict:
    """Live, per-gateway copy of the buyer's memory (new outcomes are appended here)."""
    if not hasattr(gw, "memory"):
        gw.memory = json.loads(json.dumps(seed()))
    return gw.memory.setdefault(bid, {"favourites": [], "fallbacks": {}, "orders": [], "leftovers": []})


def _need_matches(need_text: str, p: dict) -> bool:
    n = catalog.resolve_need(need_text)
    if not n["kind"] or p["kind"] != n["kind"]:
        return False
    return set(n["variants"]) <= set(p["variant"]) and set(n["diet"]) <= set(p["diet"])


def get_favourites(gw, bid: str, needs: list[str]) -> list[dict]:
    mem = memory(gw, bid)
    out = []
    for need in needs:
        for f in mem["favourites"]:
            p = catalog.by_key(f["key"])
            if p and _need_matches(need, p):
                out.append({"need": need, "gtin": p["gtin"], "name": p["name"], "pinned": bool(f.get("pinned")),
                            "fallbacks": [catalog.by_key(k)["gtin"] for k in mem["fallbacks"].get(f["key"], [])]})
                break
    return out


def find_similar_orders(gw, bid: str, brief: dict) -> list[dict]:
    """Past orders of the same kind whose lines mostly went well."""
    mem = memory(gw, bid)
    ev = brief.get("event")
    out = []
    for o in mem["orders"]:
        if ev:
            if o.get("context") != "event" or o.get("eventType") != ev["type"]:
                continue
            same = len(set(o.get("dishes", [])) & {d["recipeId"] for d in ev["dishes"]})
            if not same:
                continue
        else:
            needs = {l["text"] for l in brief["lines"]}
            if not any(any(_need_matches(n, catalog.by_key(l["key"])) for n in needs) for l in o["lines"]):
                continue
            same = 1
        labels = [l.get("label") for l in o["lines"]]
        good = sum(1 for x in labels if x in GOOD) / max(1, len(labels))
        if good < 0.6 or "under_ordered" in labels:
            continue
        out.append({"processId": o["id"], "name": o["name"], "date": o["date"], "guests": o.get("guests"),
                    "sharedDishes": same, "wentWell": round(good, 2), "labels": sorted(set(labels)),
                    "lines": o["lines"]})
    out.sort(key=lambda x: (-x["sharedDishes"], x["date"]), reverse=False)
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def get_learned_quantities(gw, bid: str, event_type: str | None) -> dict:
    """Per need: median used/planned of the last 3 right-sized runs (needs >= 2), clamped 0.6–1.15.

    Learn quietly only from runs that went right; repeated over-ordering is
    turned into a Tip the chef confirms (see tips()), never applied silently.
    """
    if not event_type:
        return {}
    by_need: dict[str, list[tuple[str, float]]] = {}
    for o in memory(gw, bid)["orders"]:
        if o.get("eventType") != event_type:
            continue
        for l in o["lines"]:
            if l.get("label") == "right_sized" and l.get("usage"):
                by_need.setdefault(l["need"], []).append((o["date"], l["usage"]))
    out = {}
    for need, xs in by_need.items():
        xs = sorted(xs)[-3:]
        if len(xs) < 2:
            continue
        f = statistics.median(u for _, u in xs)
        if abs(1 - f) < 0.05:
            continue
        out[need] = {"factor": round(max(0.6, min(1.15, f)), 3), "n": len(xs), "dates": [d for d, _ in xs]}
    return out


def get_standing_orders(gw, bid: str, needs: list[str]) -> list[dict]:
    buyer = gw.buyers[bid]
    out = []
    for so in buyer.get("standingOrders", []):
        p = catalog.by_key(so["productKey"])
        if p and any(_need_matches(n, p) for n in needs):
            out.append({"id": so["id"], "gtin": p["gtin"], "name": p["name"], "qty": so["qty"], "unit": so["unit"],
                        "weekday": so["weekday"], "cadence": so["cadence"]})
    return out


def get_leftovers(gw, bid: str) -> list[dict]:
    out = []
    for lo in memory(gw, bid)["leftovers"]:
        if lo.get("status", "available") != "available":
            continue
        p = catalog.by_key(lo["key"])
        out.append({"leftoverId": lo["leftoverId"], "gtin": p["gtin"], "name": p["name"], "qty": lo["qty"], "unit": p["unit"],
                    "bestBefore": lo["bestBefore"], "status": "available", "sourceLabel": lo["sourceLabel"]})
    return out


def tips(gw, bid: str, event_type: str | None) -> list[dict]:
    """'Last 3 galas used less cream — order 10% less?' when a need was over-ordered 3 times in a row."""
    if not event_type:
        return []
    runs: dict[str, list] = {}
    for o in sorted(memory(gw, bid)["orders"], key=lambda o: o["date"]):
        if o.get("eventType") != event_type:
            continue
        for l in o["lines"]:
            runs.setdefault(l["need"], []).append(l)
    out = []
    for need, ls in runs.items():
        last = ls[-3:]
        if len(last) == 3 and all(l.get("label") == "over_ordered" for l in last):
            used = statistics.median(l.get("usage", 1) for l in last)
            cut = max(5, min(30, round((1 - used) * 100 / 5) * 5))
            out.append({"tipId": f"TIP-{need.replace(' ', '-')}", "need": need, "eventType": event_type,
                        "factor": round(1 - cut / 100, 2), "cutPct": cut, "n": 3})
    return out


def leftover_for(leftovers: list[dict], need_text: str) -> list[dict]:
    return [lo for lo in leftovers if _need_matches(need_text, catalog.by_gtin(lo["gtin"]))]
