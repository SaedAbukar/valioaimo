"""Tool handlers for each playbook step. Each takes (gw, session, args) and returns
the step's output document. The engine decides WHEN a tool may run; these decide
WHAT it returns. Reuses planner.py, policy.py (via Gateway.evaluate) and trust.py.
"""
from __future__ import annotations

import json
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from .. import aimo_products, catalog, planner, preferences, signals as sig
from ..trust import issue_offer, verify_offer
from ..util import d2s, day_label, iso, new_id, r2, s2d
from . import cards as C
from . import discover, menu, recall as R, understand as U
from .engine import GuardFailed, StepNotAllowed, new_session_id, playbook

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def recipes_doc() -> dict:
    return json.loads((DATA / "recipes.json").read_text())


# =================================================================== 0 Receive
def start_session(gw, args: dict) -> dict:
    bid = args.get("buyerId")
    buyer = gw.buyers.get(bid)
    if not buyer:
        raise GuardFailed(f"Unknown buyer {bid}.", guard="known_agent")
    agent_id = args.get("agentId") or buyer["agents"][0]["id"]
    agent = next((a for a in buyer["agents"] if a["id"] == agent_id), None)
    if not agent:
        raise GuardFailed("This agent is not registered for the buyer.", guard="known_agent")
    if gw.kill_switch.get(agent_id):
        raise GuardFailed("This agent is paused by Valio Aimo operations.", guard="known_agent")
    mandate, check = gw.mandate_check(bid)
    if not check["ok"]:
        raise GuardFailed(f"No valid spending limit: {check['detail']}.", guard="valid_spending_limit")
    _sync_profile(gw, bid)
    return {"sessionId": new_session_id(), "buyerId": bid, "agentId": agent_id, "site": buyer["site"]["name"],
            "playbookVersion": playbook()["version"], "spendingLimitValidUntil": mandate["validUntil"]}


def _sync_profile(gw, bid: str):
    """Favourites and fallbacks from buyer memory -> preference profile used by the planner."""
    mem = R.memory(gw, bid)
    prof = gw.profiles[bid]
    prof["favourites"] = [catalog.by_key(f["key"])["gtin"] for f in mem["favourites"]]
    for f in mem["favourites"]:
        p = catalog.by_key(f["key"])
        if f.get("pinned"):
            g = prof["needGroups"].setdefault(catalog.need_group_id(p), {"pinned": None, "fallback": []})
            g["pinned"] = p["gtin"]
            g["fallback"] = [catalog.by_key(k)["gtin"] for k in mem["fallbacks"].get(f["key"], [])]


# =================================================================== 1 Understand
def parse_request(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    today = gw.clock.today()
    buyer = gw.buyers[s["buyerId"]]
    recipes = recipes_doc()["recipes"]
    if args.get("answer") and d.get("brief"):
        a = args["answer"]
        brief = U.apply_answer(d["brief"], a["field"], a["value"], today, recipes)
    elif d.get("brief") and d["brief"].get("event") and (g := U.parse_change(args.get("text", ""))) and not U.is_event_new(args.get("text", "")):
        if d.get("order") and d["order"]["status"] == "ordered":
            gw.backend.release(d["order"])  # the amended order re-reserves on place_order
        brief = U.rescale(d["brief"], g)
        brief["changed"] = {"guests": g}
    else:
        if not args.get("text"):
            raise GuardFailed("parse_request needs 'text' (or 'answer').", guard="bad_input",
                              fix={"example": {"text": "I need 1,000 litres of lactose-free milk by Monday."}})
        brief = U.parse(args["text"], today, buyer["site"], recipes)
    d["brief"] = brief
    return brief


def ask_user(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    q = U.question_for(d["brief"], gw.clock.today())
    if not q:
        raise GuardFailed("Nothing critical is missing; no question needed.", guard="one_question",
                          next_allowed_tools=["recall"], fix={"call": "recall"})
    d["asked"] = q
    return {"question": q}


# =================================================================== 2 Recall
def _needs(gw, s: dict) -> list[str]:
    b = s["data"]["brief"]
    if b.get("event"):
        return [l["need"] for l in _menu(gw, s)["lines"]]
    return [l["text"] for l in b["lines"]]


def _menu(gw, s: dict) -> dict:
    d = s["data"]
    b = d["brief"]
    learned = R.get_learned_quantities(gw, s["buyerId"], b["event"]["type"])
    tips = [t for t in R.tips(gw, s["buyerId"], b["event"]["type"]) if t["tipId"] in d["acceptedTips"]]
    d["menu"] = menu.build(b, recipes_doc(), learned, tips)
    return d["menu"]


def get_favourites(gw, s, args):
    out = R.get_favourites(gw, s["buyerId"], _needs(gw, s))
    s["data"].setdefault("recallParts", {})["favourites"] = out
    return {"favourites": out}


def find_similar_orders(gw, s, args):
    out = R.find_similar_orders(gw, s["buyerId"], s["data"]["brief"])
    s["data"].setdefault("recallParts", {})["similar_orders"] = out
    return {"orders": out}


def get_learned_quantities(gw, s, args):
    ev = s["data"]["brief"].get("event")
    out = R.get_learned_quantities(gw, s["buyerId"], ev["type"] if ev else None)
    s["data"].setdefault("recallParts", {})["learned_quantities"] = out
    return {"learned": out}


def get_standing_orders(gw, s, args):
    out = R.get_standing_orders(gw, s["buyerId"], _needs(gw, s))
    s["data"].setdefault("recallParts", {})["standing_orders"] = out
    return {"standingOrders": out}


def get_leftovers(gw, s, args):
    out = R.get_leftovers(gw, s["buyerId"])
    s["data"].setdefault("recallParts", {})["leftovers"] = out
    return {"leftovers": out}


def recall(gw, s: dict, args: dict) -> dict:
    """Run the five recall sources in the playbook order and assemble the RecallResult."""
    d = s["data"]
    parts = d.setdefault("recallParts", {})
    for name, fn in (("favourites", get_favourites), ("similar_orders", find_similar_orders),
                     ("learned_quantities", get_learned_quantities), ("standing_orders", get_standing_orders),
                     ("leftovers", get_leftovers)):
        if name not in parts:
            fn(gw, s, {})
    needs = _needs(gw, s)
    matched, gaps = [], []
    favs = {f["need"]: f for f in parts["favourites"]}
    similar = parts["similar_orders"]
    for need in needs:
        f = favs.get(need)
        if f:
            matched.append({"need": need, "productId": f["gtin"], "name": f["name"], "source": "favourites",
                            "confidence": "high" if f["pinned"] else "medium", "fallbacks": f["fallbacks"]})
            continue
        hit = None
        for o in similar:
            for l in o["lines"]:
                p = catalog.by_key(l["key"])
                if l.get("label") in R.GOOD and R._need_matches(need, p):
                    hit = (o, p)
                    break
            if hit:
                break
        if hit:
            matched.append({"need": need, "productId": hit[1]["gtin"], "name": hit[1]["name"], "source": "similar_orders",
                            "confidence": "medium", "fromOrder": hit[0]["name"]})
        else:
            gaps.append(need)
    for need, lf in parts["learned_quantities"].items():
        if need in needs:
            matched.append({"need": need, "source": "learned_quantities", "confidence": "high" if lf["n"] >= 3 else "medium",
                            "factor": lf["factor"]})
    for so in parts["standing_orders"]:
        matched.append({"need": so["name"], "source": "standing_orders", "confidence": "low", "standingOrder": so["id"]})
    for lo in parts["leftovers"]:
        if any(R.leftover_for([lo], n) for n in needs):
            matched.append({"need": lo["name"], "source": "leftovers", "confidence": "high", "qty": lo["qty"], "unit": lo["unit"]})
    ev = d["brief"].get("event")
    out = {"matched": matched, "gaps": gaps, "sources": R.RECALL_ORDER,
           "similar": similar[0] if similar else None,
           "tips": [t for t in R.tips(gw, s["buyerId"], ev["type"] if ev else None)
                    if t["tipId"] not in d["acceptedTips"] + d["ignoredTips"]],
           "coverage": round(1 - len(gaps) / max(1, len(needs)), 2)}
    d["recall"] = out
    return out


# =================================================================== 3 Discover
def _live(gw, s) -> bool:
    return gw.buyers[s["buyerId"]].get("assortment") == "aimo"


def search_products(gw, s, args):
    q = args.get("query") or args.get("need") or ""
    if _live(gw, s) or not catalog.resolve_need(q)["kind"]:
        r = aimo_products.search(q, exclude_allergens=args.get("excludeAllergens"), diet=args.get("diet"), limit=args.get("limit", 10))
        return {"source": "valio-aimo", **r}
    return {"source": "assortment", **catalog.search(q, exclude_allergens=args.get("excludeAllergens"))}


def get_product(gw, s, args):
    pid = str(args.get("productId", ""))
    rec = aimo_products.by_id(pid.replace("aimo:", ""))
    if rec:
        return aimo_products.public(rec)
    p = catalog.by_gtin(pid)
    if not p:
        raise GuardFailed(f"Unknown product {pid}.", fix={"call": "search_products", "example": {"query": "oat drink"}})
    return catalog.public_product(p)


def request_offers(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    b = d["brief"]
    need_by = _need_by(gw, s)
    excl = _exclusions(gw, s)
    out = []
    for need in d["recall"]["gaps"]:
        rn = catalog.resolve_need(need)
        if _live(gw, s) or not rn["kind"]:
            r = discover.search_live(gw, _query(need), rn["kind"], need_by, excl, [], limit=10)
            qty = next((l["qty"] for l in b.get("lines", []) if l["text"] == need), 0)
            big = [p for p in r["products"] if not qty or p["packSize"] >= qty / 150]  # no 2.5 dl cartons for 100 L
            cands = (big if len(big) >= 2 else r["products"])[:6]
            source = "valio-aimo"
        else:
            cands = [catalog.by_gtin(g) for g in rn["candidates"]][:6]
            source = "assortment"
        offers = []
        for p in cands[:6]:
            of = issue_offer(gw, p["gtin"], need_by, s["buyerId"])
            d.setdefault("offers", {})[p["gtin"]] = of
            offers.append({"productId": p["gtin"], "name": p["name"], "unitPrice": of["unitPrice"], "unit": p["unit"],
                           "available": of["availability"]["qtyAvailable"], "offerId": of["offerId"],
                           "validUntil": of["validUntil"]})
        out.append({"need": need, "source": source, "candidates": offers,
                    "liveCandidates": [p["gtin"] for p in cands] if source == "valio-aimo" else None})
    res = {"gaps": out, "needBy": d2s(need_by), "live": bool(getattr(gw, "aimo", None))}
    d["candidates"] = res
    return res


def _query(need: str) -> str:
    return discover.query_fi(need)


def _exclusions(gw, s) -> list[str]:
    m, _ = gw.mandate_check(s["buyerId"])
    return list(m["hardExclusions"]["allergens"]) if m else []


def _need_by(gw, s):
    b = s["data"]["brief"]
    if b.get("event"):
        return s2d(b["event"]["date"]) - timedelta(days=1)
    return s2d(b["when"]["value"])


# =================================================================== 4 Plan
def plan_basket(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    bid = s["buyerId"]
    buyer = gw.buyers[bid]
    if args.get("choices"):
        d["choices"].update(args["choices"])
    if args.get("useAlternative"):
        d["alternatives"][args["useAlternative"]] = True
    if args.get("acceptTip"):
        d["acceptedTips"].append(args["acceptTip"])
    if args.get("ignoreTip"):
        d["ignoredTips"].append(args["ignoreTip"])
    if "recall" not in d:
        raise StepNotAllowed("Recall must run before planning.", next_allowed_tools=["recall"])
    if args.get("acceptSuggestion"):
        _accept_suggestion(gw, s, args["acceptSuggestion"])
    if getattr(gw, "aimo", None):  # live mode: recalled favourites are priced on the mock API too
        discover.refresh_curated(gw, _need_by(gw, s))
    b = d["brief"]
    is_event = bool(b.get("event"))
    if is_event and (args.get("acceptTip") or args.get("ignoreTip")):
        _menu(gw, s)
        d["recall"]["tips"] = [t for t in d["recall"]["tips"] if t["tipId"] not in d["acceptedTips"] + d["ignoredTips"]]
    mandate, _ = gw.mandate_check(bid)
    leftovers = R.get_leftovers(gw, bid)
    ctx = {"buyer": buyer, "mandate": mandate, "profile": gw.profiles[bid], "signals": sig.compute(buyer, gw.records),
           "backend": gw.backend, "today": gw.clock.today(), "leftovers": leftovers}
    reqs = d["menu"]["lines"] if is_event else [dict(l, needBy=b["when"]["value"]) for l in b["lines"]]
    reqs = reqs + [dict(x, needBy=d2s(_need_by(gw, s))) for x in d.get("suggestionLines", [])]  # added from a seller suggestion
    sug_cands = d.get("suggestionCands", {})
    live_cands = {g["need"]: g["liveCandidates"] for g in (d.get("candidates") or {}).get("gaps", []) if g.get("liveCandidates")}
    srcmap = {m["need"]: m for m in d["recall"]["matched"] if m["source"] in ("favourites", "similar_orders")}
    learned = {m["need"]: m for m in d["recall"]["matched"] if m["source"] == "learned_quantities"}
    lines, cant, pending, adjustments, left_used, plan_lines = [], [], [], [], [], []
    usage = {"type": "event", "date": b["event"]["date"]} if is_event else None
    for req in reqs:
        need = req.get("need") or req["text"]
        r = {"lineId": req["lineId"], "text": req["text"], "qty": req["qty"], "unit": req["unit"],
             "useLeftovers": req.get("useLeftovers", False), "excludeAllergens": req.get("excludeAllergens", [])}
        if need in live_cands:
            r["candidates"] = live_cands[need]
        if req.get("candidates") or req["lineId"] in sug_cands:  # a seller suggestion the agent accepted
            r["candidates"] = req.get("candidates") or sug_cands[req["lineId"]]["gtins"]
        nb = s2d(req["needBy"])
        choice = d["choices"].get(req["lineId"])
        pl = planner.plan_line(ctx, r, nb, choice, usage)
        plan_lines.append(pl)
        for n in pl["notices"]:
            if n["type"] == "leftover" and n.get("applied"):
                left_used.append({"need": need, "qty": n["applied"], "name": catalog.by_gtin(n["gtin"])["name"], "leftoverId": n["leftoverId"]})
        if pl["qtyAfterLeftovers"] <= 1e-9:
            continue
        # Can't do: nothing of the requested kind is safe AND on time; an allergen removed the only other option
        strict = [i for i in pl["ranked"] if not i["specRelaxed"] and not i["lateOnly"]]
        allergen_out = [e for e in pl["excluded"] if e["code"] == "allergen"]
        safe_alt = next((i for i in pl["ranked"] if i["specRelaxed"] and not i["lateOnly"]), None)
        if not strict and allergen_out and not d["alternatives"].get(req["lineId"]):
            late = next((i for i in pl["ranked"] if not i["specRelaxed"] and i["lateOnly"]), None)
            cant.append({"lineId": req["lineId"], "need": need, "qty": pl["qtyAfterLeftovers"], "unit": pl["unit"],
                         "blockedProduct": allergen_out[0]["name"], "allergen": allergen_out[0]["reason"],
                         "lateProduct": late["name"] if late else None, "lateDate": late["earliest"] if late else None,
                         "alternative": {"productId": safe_alt["gtin"], "name": safe_alt["name"], "unitPrice": safe_alt["unitPrice"],
                                         "unit": safe_alt["unit"]} if safe_alt else None})
            continue
        # Product choice: a real choice only when the kitchen has no memory for this need and nothing was picked yet
        if need not in srcmap and not choice and len(pl["ranked"]) >= 2 and not is_event:
            opts = [i for i in pl["ranked"] if not i["lateOnly"]][:3]
            if len(opts) >= 2:
                pending.append({"lineId": req["lineId"], "need": need, "qty": pl["qtyAfterLeftovers"], "unit": pl["unit"],
                                "options": [_option(i, opts, gw) for i in opts]})
        if not pl["plans"]:
            cant.append({"lineId": req["lineId"], "need": need, "qty": pl["qtyAfterLeftovers"], "unit": pl["unit"],
                         "blockedProduct": None, "allergen": (pl["excluded"][0]["reason"] if pl["excluded"] else "nothing available"),
                         "alternative": None})
            continue
        chosen = pl["plans"][0]
        for l in chosen["lines"]:
            src = "discover"
            m = srcmap.get(need)
            if m and l["gtin"] == m["productId"]:
                src = m["source"]
            elif m and l["gtin"] in m.get("fallbacks", []):
                src = "similar_orders"  # the stand-in that worked last time (good_substitute)
            if choice:
                src = "discover"
            of = issue_offer(gw, l["gtin"], s2d(l["deliveryDate"]), bid)
            d.setdefault("offers", {})[l["gtin"]] = of
            l["offerId"] = of["offerId"]
            l["unitPrice"] = of["unitPrice"]
            l["lineTotal"] = r2(l["qty"] * of["unitPrice"])
            adj = req.get("qtyAdjustment")
            if adj:
                l["qtyAdjustment"] = adj
                adjustments.append({"need": need, **adj})
            p = catalog.by_gtin(l["gtin"])
            why = _why(need, l, src, m, req, learned.get(need), pl)
            sug = req.get("suggestion") or (sug_cands.get(req["lineId"]) or {}).get("suggestion")
            if sug and l["gtin"] in (req.get("candidates") or sug_cands.get(req["lineId"], {}).get("gtins", [])):
                src, why = "valio-aimo-seller", f"Suggested by Valio Aimo: {sug['reason']}"
            lines.append({**l, "productId": l["gtin"], "need": need, "label": req.get("label", need), "why": why, "source": src,
                          "nameFi": p.get("nameFi"), "salesUnit": p.get("salesUnit"), "live": p.get("livePrice", False),
                          "aimoProductId": p.get("aimoProductId")})
    total = r2(sum(l["lineTotal"] for l in lines))
    deliveries: dict[str, list] = {}
    for l in lines:
        deliveries.setdefault(l["deliveryDate"], []).append(l["lineId"])
    out = {"lines": lines, "total": total, "deliveryDays": sorted(deliveries),
           "perGuest": r2(total / b["event"]["guests"]) if is_event and b["event"]["guests"] else None,
           "cantDo": cant, "pendingChoices": pending, "leftoversUsed": left_used, "adjustments": adjustments,
           "requestLines": [{"lineId": pl["lineId"], "qty": pl["qtyAfterLeftovers"], "needBy": r["needBy"]}
                            for pl, r in zip(plan_lines, reqs) if pl["qtyAfterLeftovers"] > 0 and pl["plans"]],
           "warnings": (d.get("menu") or {}).get("warnings", []),
           "co2eKg": round(sum(l["qty"] * (catalog.by_gtin(l["gtin"]).get("kgPerUnit") or 1) * (catalog.by_gtin(l["gtin"]).get("co2eKgPerKg") or 0) for l in lines), 1)}
    # the signed offers this basket stands on: place_order must cite exactly these ids
    out["offers"] = [{k: d["offers"][g][k] for k in ("offerId", "gtin", "name", "unitPrice", "unit", "validUntil", "priceSource", "aimoProductId")}
                     for g in dict.fromkeys(l["gtin"] for l in lines)]
    d["plan"] = out
    return out


def _accept_suggestion(gw, s: dict, sug_id: str):
    """Use a seller suggestion through the normal rails: the product is bridged, the basket is re-planned and
    must pass check_basket again (signed offers, mandate, approval rules). Never an order by itself."""
    from .. import aimo_products, lookup, seller
    from .engine import NotFound
    d, bid = s["data"], s["buyerId"]
    sug = seller.get(gw, sug_id)
    if not sug or sug["buyerId"] != bid:
        raise NotFound(f"No suggestion {sug_id} for this customer.", fix={"call": "get_suggestions", "rest": "GET /v1/suggestions"})
    if sug_id in d.get("acceptedSuggestions", []):
        return
    if sug["status"] not in ("open", "accepted") or sug["validUntil"] < iso(gw.clock.now()) or seller.opted_out(gw, bid):
        raise GuardFailed(f"The suggestion {sug_id} is {sug['status']} and can no longer be used.", guard="suggestion_closed",
                          fix={"call": "get_suggestions"})
    nb = _need_by(gw, s)
    rec = aimo_products.by_id(sug["productId"])
    prices, avail = lookup._live(gw, [rec["id"]], nb)
    kind = sug["replaces"]["need"] if sug["action"] == "replace" else None
    live = {"price": prices.get(rec["id"]), "availability": avail.get(rec["id"])} if (prices or avail) else None
    p = discover.bridge(gw, rec, kind or "other", nb, live)
    p["category"] = sug["category"]
    if sug["action"] == "replace":
        lines = d["menu"]["lines"] if d["brief"].get("event") else d["brief"]["lines"]
        hit = next((l for l in lines if catalog.resolve_need(l["text"])["kind"] == kind), None)
        if not hit:
            raise GuardFailed(f"This suggestion replaces {sug['replaces']['productName']}, which is not in this order.",
                              guard="suggestion_not_applicable", fix={"hint": "accept it in a session that orders that product"})
        d.setdefault("suggestionCands", {})[hit["lineId"]] = {"gtins": [p["gtin"]], "suggestion": {"id": sug_id, "reason": sug["reason"]}}
        d["choices"][hit["lineId"]] = p["gtin"]
    else:
        n = len(d.get("suggestionLines", [])) + 1
        qty = sug["suggestedQty"]["qty"] if sug["suggestedQty"]["unit"] == p["unit"] else p["packSize"]
        d.setdefault("suggestionLines", []).append({"lineId": f"S{n}", "text": p["name"], "need": p["name"], "qty": qty,
                                                    "unit": p["unit"], "candidates": [p["gtin"]],
                                                    "suggestion": {"id": sug_id, "reason": sug["reason"]}})
    d.setdefault("acceptedSuggestions", []).append(sug_id)
    if sug["status"] == "open":
        seller.feedback(gw, bid, sug_id, "accepted", "added through plan_basket; re-planned and re-checked",
                        actor=f"agent:{s['agentId'].split(':')[-1]}", trace_id=s["sessionId"])


def _option(i: dict, opts: list[dict], gw) -> dict:
    cheapest = min(opts, key=lambda x: x["unitPrice"])
    fastest = min(opts, key=lambda x: x["earliest"] or "9999")
    tag = "Best match" if i is opts[0] else "Cheaper option" if i is cheapest else "Faster delivery" if i is fastest else "Also good"
    p = catalog.by_gtin(i["gtin"])
    why = {"Best match": "Fits what you asked for best.", "Cheaper option": "Lower price for the same use.",
           "Faster delivery": "Can arrive sooner.", "Also good": "A solid second choice."}[tag]
    if p.get("onTimeRate") and p.get("source") == "valio-aimo" and p["onTimeRate"] >= 0.98:
        why = why[:-1] + ", always delivered in full."
    return {"productId": i["gtin"], "name": i["name"], "brand": i["brand"], "unitPrice": i["unitPrice"], "unit": i["unit"],
            "tag": tag, "why": why, "earliest": i["earliest"]}


def _why(need, l, src, m, req, learned, pl) -> str:
    bits = []
    if src == "favourites":
        bits.append("Your favourite.")
    elif src == "similar_orders" and m and m.get("fromOrder"):
        bits.append(f"You used it for {m['fromOrder']}.")
    elif src == "similar_orders":
        bits.append("It worked well as a stand-in last time.")
    elif l["role"] == "substitute":
        bits.append(f"Your usual one is short, so this fills the gap.")
    else:
        bits.append("Best match from Valio Aimo.")
    if req.get("sources"):
        portions = sum(x["portions"] for x in req["sources"])
        bits.append(f"For {portions} portions of {', '.join(sorted({x['dish'].split(' (')[0] for x in req['sources']}))}.")
    if req.get("qtyAdjustment"):
        bits.append(f"Adjusted because {req['qtyAdjustment']['why']}.")
    lo = next((n for n in pl["notices"] if n["type"] == "leftover" and n.get("applied")), None)
    if lo:
        bits.append(f"Uses {lo['applied']:g} {pl['unit']} you already have first.")
    if l.get("overage"):
        bits.append("Rounded up to whole packs.")
    return " ".join(bits)


# =================================================================== 5 Check (gateway-run)
PLAIN = {
    "R1": "It contains something your kitchen never orders.",
    "R2": "This is over the spending limit for one order.",
    "R3": "This would go over this month's budget.",
    "R4": "A different brand fills part of the order, within your rules.",
    "R5": "A replacement differs more than your rules allow.",
    "R6": "The order is split between two products to get the full amount.",
    "R7": "Part of it arrives after the day you need it.",
    "R8": "You have not ordered this product before.",
    "R9": "This kind of product is outside what you normally buy.",
    "R10": "Your standing order changed a lot from normal.",
    "R11": "It doesn't match one of your must-have choices.",
    "R12": "Your favourite was available but not picked.",
    "R13": "The amount is different from your usual.",
    "R14": "The cost per guest is above your target.",
    "V1": "Valio Aimo needs to check the account balance first.",
    "V2": "The amount looks much bigger than usual. Typo?",
    "V3": "Ordering is paused by Valio Aimo.",
}
OUTCOME = {"AUTO": "auto", "NOTIFY": "tell_me", "APPROVE": "needs_ok", "BLOCK": "blocked"}


def check_basket(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    plan = d["plan"]
    bid = s["buyerId"]
    b = d["brief"]
    verifs = []
    for l in plan["lines"]:
        v = verify_offer(gw, d["offers"][l["gtin"]], qty=None)
        verifs.append({"productId": l["gtin"], "verified": v["verified"],
                       "failed": [c["detail"] for c in v["checks"] if not c["ok"] and c["id"] != "freshness"]})
    ev = {"guests": b["event"]["guests"], "name": b["event"]["name"]} if b.get("event") else None
    pol = gw.evaluate(bid, plan["lines"], plan["requestLines"], **({"event": ev} if ev else {})) if plan["lines"] else \
        {"outcome": "BLOCK", "decisions": [], "ruleIds": []}
    decision = OUTCOME[pol["outcome"]]
    ok = all(v["verified"] for v in verifs)
    if not ok:
        decision = "blocked"
    prio = ["V3", "R1", "V1", "V2", "R2", "R14", "R3", "R7", "R5", "R9", "R11", "R10", "R13", "R6", "R4", "R12", "R8"]
    top = sorted([x for x in pol["decisions"] if x["outcome"] == pol["outcome"]],
                 key=lambda x: prio.index(x["ruleId"]) if x["ruleId"] in prio else 99)
    reasons = list(dict.fromkeys(PLAIN.get(x["ruleId"], "One of your rules applies.") for x in (top or pol["decisions"])))
    if not ok:
        reasons.insert(0, "A price or stock promise expired. I need to check again.")
    if not plan["lines"]:
        reasons = ["Nothing in this order can be delivered safely."]
    mandate, _ = gw.mandate_check(bid)
    lim = mandate["limits"]
    limit = lim.get("perEventEUR", lim["perOrderEUR"]) if ev else lim["perOrderEUR"]
    out = {"decision": decision, "reasons": reasons, "offersVerified": ok, "verifications": verifs,
           "limit": limit, "overBy": r2(max(0.0, plan["total"] - limit)),
           "approver": _approver(gw, bid), "internal": {"outcome": pol["outcome"], "ruleIds": pol["ruleIds"],
                                                        "decisions": [{"ruleId": x["ruleId"], "reason": x["reason"]} for x in pol["decisions"]]}}
    d["decision"] = out
    return out


def _approver(gw, bid):
    b = gw.buyers[bid]
    a = b["approvers"][0]
    return {"id": a["id"], "name": a["name"], "role": a["role"]}


# =================================================================== 6 Present
def render_cards(gw, s: dict, args: dict) -> dict:
    cards = C.for_session(gw, s)
    if args.get("cards"):  # an external agent may bring its own wording; it must pass the same lint
        cards = args["cards"]
    C.lint_all(cards)
    s["data"]["cards"] = cards
    return {"cards": cards}


# =================================================================== 7 Act
def _lock_prices(gw, s):
    """Every offer still holds: signature, validity, price AND stock for the planned quantity (re-checked live)."""
    d = s["data"]
    qty: dict[str, float] = {}
    for l in d["plan"]["lines"]:
        qty[l["gtin"]] = qty.get(l["gtin"], 0) + l["qty"]
    for l in d["plan"]["lines"]:
        v = verify_offer(gw, d["offers"][l["gtin"]], qty=qty[l["gtin"]])
        if not v["verified"]:
            bad = "; ".join(c["detail"] for c in v["checks"] if not c["ok"] and c["id"] != "freshness")
            only_stock = v["shortfall"] and all(c["ok"] or c["id"] == "freshness" for c in v["checks"] if c["id"] != "reverify")
            if only_stock and "price now" not in bad:
                _stock_changed(v["shortfall"])
            raise StepNotAllowed(f"Offer for {l['name']} is no longer valid ({bad}). Plan again.",
                                 guard="price_locked", next_allowed_tools=["plan_basket"])


def _stock_changed(shortfall: list[str]):
    raise StepNotAllowed("Stock changed since the quote: " + "; ".join(shortfall) + ". Re-quote with plan_basket.",
                         guard="stock_changed", shortfall=shortfall, next_allowed_tools=["plan_basket"],
                         fix={"call": "plan_basket", "why": "the planner re-plans on what is deliverable now"})


NEGOTIATION_KEYS = {"price", "unitPrice", "prices", "discount", "total", "counterOffer", "lineTotal"}


def offer_ids(s: dict) -> list[str]:
    """The signed offers the checked basket stands on; place_order must cite exactly these."""
    d = s["data"]
    return list(dict.fromkeys(d["offers"][l["gtin"]]["offerId"] for l in d["plan"]["lines"]))


def reject_negotiation(s: dict, args: dict):
    tried = sorted(NEGOTIATION_KEYS & set(args))
    if tried:
        raise GuardFailed("Prices are fixed by the signed offers. There is no negotiation: "
                          f"remove {', '.join(tried)} and cite the offer ids.", guard="fixed_prices",
                          fix={"offerIds": offer_ids(s)})


def _cite(s: dict, args: dict):
    """Inquiry -> commitment at fixed prices: an order cites the signed offers; no price is negotiable."""
    reject_negotiation(s, args)
    cited = args.get("offerIds")
    want = offer_ids(s)
    if not cited:
        raise GuardFailed("An order must cite the signed offers it accepts.", guard="cite_offers", fix={"offerIds": want})
    if set(cited) != set(want):
        raise StepNotAllowed("The cited offers are not the ones in the checked basket. Re-quote with plan_basket.",
                             guard="offer_mismatch", expected=want, next_allowed_tools=["plan_basket"])


def _confirmation(gw, s: dict, order: dict) -> dict:
    """Order confirmation signed by the gateway (JWS ES256), verifiable against /.well-known/jwks.json."""
    mandate, _ = gw.mandate_check(s["buyerId"])
    claim = {"type": "OrderConfirmation", "orderId": order["orderId"], "backendOrderRef": order["backendOrderRef"],
             "buyerId": s["buyerId"], "agentId": s["agentId"], "mandateId": (mandate or {}).get("mandateId"),
             "sessionId": s["sessionId"], "offerIds": [l["offerId"] for l in order["lines"]],
             "lines": [{k: l[k] for k in ("offerId", "gtin", "qty", "unit", "unitPrice", "lineTotal", "deliveryDate")}
                       for l in order["lines"]],
             "total": order["total"], "currency": "EUR", "placedAt": order["placedAt"],
             "decision": order["decision"], "approvedBy": order["approvedBy"]}
    return {"format": "order+jwt", "alg": "ES256", "kid": gw.gateway_key.kid, "jwksUri": "/.well-known/jwks.json",
            "jws": gw.gateway_key.sign(claim, typ="order+jwt")}


def place_order(gw, s: dict, args: dict) -> dict:
    _cite(s, args)
    with gw.lock:  # verify -> reserve -> place is one atomic step: two agents never both get the last stock
        _lock_prices(gw, s)
        return _place(gw, s)


def _place(gw, s: dict) -> dict:
    d = s["data"]
    plan = d["plan"]
    prev = d.get("order")
    order = {"orderId": prev["orderId"] if prev else new_id("ORD"), "status": "ordered", "placedAt": iso(gw.clock.now()),
             "lines": [{k: l[k] for k in ("lineId", "gtin", "name", "qty", "unit", "unitPrice", "lineTotal", "deliveryDate", "offerId")} for l in plan["lines"]],
             "total": plan["total"], "deliveries": _deliveries(plan), "amended": bool(prev),
             "decision": d["decision"]["decision"], "approvedBy": (d.get("approval") or {}).get("decidedBy")}
    for ln in order["lines"]:  # the price comes from the signed offer, never from the caller
        ln["offerId"] = d["offers"][ln["gtin"]]["offerId"]
    ok, short = gw.backend.reserve(order["lines"])
    if not ok:
        _stock_changed(short)
    order["backendOrderRef"] = gw.backend.place_order(order)["backendOrderRef"]
    if d.get("approval") and d["approval"]["status"] == "approved":
        d["approval"]["used"] = True
    order["confirmation"] = _confirmation(gw, s, order)
    d["order"] = order
    gw.orders[order["orderId"]] = {"sessionId": s["sessionId"], **order}
    return order


def _deliveries(plan):
    out = []
    for day in plan["deliveryDays"]:
        ls = [l for l in plan["lines"] if l["deliveryDate"] == day]
        out.append({"date": day, "label": day_label(s2d(day)), "window": "in the morning", "lines": len(ls),
                    "items": [l["name"] for l in ls][:6]})
    return out


def request_approval(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    _lock_prices(gw, s)
    ap = _approver(gw, s["buyerId"])
    d["approval"] = {"approvalId": new_id("APR"), "status": "pending", "approver": ap, "requestedAt": iso(gw.clock.now()),
                     "reasons": d["decision"]["reasons"], "total": d["plan"]["total"]}
    gw.approvals[d["approval"]["approvalId"]] = s["sessionId"]
    # the request reaches a named human: their inbox (GET /v1/approvals with their credential)
    gw.inbox.append({"to": ap["id"], "name": ap["name"], "buyerId": s["buyerId"], "approvalId": d["approval"]["approvalId"],
                     "sessionId": s["sessionId"], "at": d["approval"]["requestedAt"]})
    gw.audit.append(trace_id=s["sessionId"], actor="system:gateway", action="approval.notified", buyer_id=s["buyerId"],
                    refs={"approvalId": d["approval"]["approvalId"], "to": ap["id"]},
                    reason=f"Asked {ap['name']} ({ap['role']}) for an OK: {'; '.join(d['decision']['reasons'])}")
    return {"status": "waiting_for_ok", "approval": d["approval"]}


def decide_approval(gw, s: dict, ok: bool, person: dict, note: str | None = None) -> dict:
    """A named approver's decision. Not a playbook tool: agents cannot call it (auth + MCP have no such tool)."""
    appr = (s["data"].get("approval") or {})
    if appr.get("status") != "pending":
        raise GuardFailed("There is no pending approval for this order.", guard="pending_approval")
    if person["id"] not in {a["id"] for a in gw.buyers[s["buyerId"]]["approvers"]}:
        raise GuardFailed(f"{person.get('name', person['id'])} is not an approver for this customer.", guard="named_approver")
    appr.update({"status": "approved" if ok else "rejected", "decidedBy": person["name"], "decidedById": person["id"],
                 "decidedAt": iso(gw.clock.now()), "note": note})
    gw.inbox[:] = [m for m in gw.inbox if m["approvalId"] != appr["approvalId"]]
    gw.audit.append(trace_id=s["sessionId"], actor=f"human:{person['name']}", action="approved" if ok else "rejected",
                    buyer_id=s["buyerId"], refs={"approvalId": appr["approvalId"], "step": "act", "personId": person["id"]},
                    decision="APPROVE" if ok else "REJECT",
                    reason=f"{person['name']} {'approved' if ok else 'declined'} the order" + (f": {note}" if note else ""))
    gw.events.emit(s["sessionId"], "approval.decided", {"approvalId": appr["approvalId"], "status": appr["status"],
                                                         "decidedBy": person["name"], "next_allowed_tools": gw.engine.allowed(s)})
    gw.save()
    return appr


# =================================================================== 8 Follow up and learn
USAGE = {"all": (0.97, "right_sized"), "some": (0.82, "over_ordered"), "ran_out": (1.1, "under_ordered")}


def record_usage(gw, s: dict, args: dict) -> dict:
    d = s["data"]
    if not d.get("order"):
        raise GuardFailed("Nothing was ordered in this session yet.", next_allowed_tools=["get_session"],
                          fix={"call": "place_order first"})
    entries = args.get("entries") or {}
    b = d["brief"]
    lines, labels = [], []
    seen = set()
    for l in d["plan"]["lines"]:
        if l["need"] in seen:
            continue
        seen.add(l["need"])
        u, lab = USAGE.get(entries.get(l["need"], "all"), USAGE["all"])
        lines.append({"need": l["need"], "key": catalog.by_gtin(l["gtin"]).get("key"), "usage": u, "label": lab})
        labels.append(lab)
    ev = b.get("event")
    event_label = "perfect_order" if all(x == "right_sized" for x in labels) else None
    rec = {"id": s["sessionId"], "date": ev["date"] if ev else b["when"]["value"], "context": b["context"],
           "eventType": ev["type"] if ev else None,
           "name": (ev["name"] if ev["name"] != ev["typeLabel"] else f"{ev['typeLabel'].split()[0].lower()} on {day_label(s2d(ev['date']))}") if ev else "Order",
           "guests": ev["guests"] if ev else None, "dishes": [x["recipeId"] for x in ev["dishes"]] if ev else [],
           "lines": lines, "labels": sorted(set(labels) | ({event_label} if event_label else set()))}
    R.memory(gw, s["buyerId"])["orders"].append(rec)
    d["order"]["status"] = "done"
    if d["order"]["orderId"] in gw.orders:
        gw.orders[d["order"]["orderId"]]["status"] = "done"
    d["usage"] = rec
    return {"processId": s["sessionId"], "labels": rec["labels"], "lines": lines,
            "tips": R.tips(gw, s["buyerId"], ev["type"] if ev else None)}


def get_tips(gw, s, args):
    ev = s["data"]["brief"].get("event")
    return {"tips": R.tips(gw, s["buyerId"], args.get("eventType") or (ev["type"] if ev else None))}
