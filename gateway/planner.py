"""Planner & ranking. Proposes; never orders.

1 candidates (catalog + attribute match) -> 2 hard filters (logged with reason)
-> 3 unit conversion to whole cases -> 4 score with the buyer's preference weights
-> 5 BEST/BETTER/GOOD tiers with trade-off sentence -> 6 up to 3 plans
(split across products / single substitute / split across dates).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from . import catalog, preferences as prefs, signals as sig
from .util import d2s, day_label, r2, s2d

TIERS = ["BEST", "BETTER", "GOOD"]


def fmt_qty(q: float, unit: str) -> str:
    return f"{q:,.0f} {unit}" if abs(q - round(q)) < 1e-9 else f"{q:,.1f} {unit}"


def variant_text(vs):
    return ", ".join(v.replace("_", "-") for v in vs) or "standard"


def substitution_meta(p: dict, primary: dict) -> dict:
    changes = []
    if p["brand"] != primary["brand"]:
        changes.append("brand switch")
    if abs(p["packSize"] - primary["packSize"]) > 1e-9:
        changes.append("pack size")
    if sorted(p["variant"]) != sorted(primary["variant"]):
        changes.append("spec change")
    if sorted(p["allergens"] + p["mayContain"]) != sorted(primary["allergens"] + primary["mayContain"]):
        changes.append("allergen profile")
    if p["category"] != primary["category"]:
        changes.append("category change")
    delta = (p["unitPrice"] - primary["unitPrice"]) / primary["unitPrice"] * 100 if primary["unitPrice"] else 0
    return {"changes": changes, "priceDeltaPct": round(delta, 1)}


def spec_diff(p: dict, primary: dict) -> str:
    a = [v for v in p["variant"] if v not in primary["variant"]]
    b = [v for v in primary["variant"] if v not in p["variant"]]
    if p["kind"] != primary["kind"]:
        return f"{catalog.KIND_LABELS.get(p['kind'], p['kind'])} instead of {catalog.KIND_LABELS.get(primary['kind'], primary['kind'])}"
    return f"{variant_text(a)} instead of {variant_text(b)}"


def describe_changes(p: dict, primary: dict, changes: list[str]) -> str:
    out = []
    for c in changes:
        if c == "brand switch":
            out.append(f"brand {p['brand']}")
        elif c == "pack size":
            out.append(f"{p['packSize']:g} {p['unit']} packs")
        elif c == "spec change":
            out.append(spec_diff(p, primary))
        elif c == "allergen profile":
            add = sorted(set(p["allergens"] + p["mayContain"]) - set(primary["allergens"] + primary["mayContain"]))
            out.append("adds allergen " + "/".join(add) if add else "different allergen profile")
        elif c == "category change":
            out.append(f"category {p['category']}")
    return ", ".join(out) or "same spec"


def plan_line(ctx: dict, req: dict, need_by: date, choice: str | None = None, usage: dict | None = None) -> dict:
    buyer, mandate, profile, signals = ctx["buyer"], ctx["mandate"], ctx["profile"], ctx.get("signals")
    be, today = ctx["backend"], ctx["today"]
    need = catalog.resolve_need(req["text"])
    if req.get("candidates"):  # Discover step supplied the candidate set (e.g. real Valio Aimo products)
        first = catalog.by_gtin(req["candidates"][0])
        need = dict(need, candidates=list(req["candidates"]), variants=[],
                    kind=first["kind"], kindLabel=catalog.KIND_LABELS.get(first["kind"], first["kind"]))
    excl_all = (set(mandate["hardExclusions"]["allergens"]) if mandate else set()) | set(req.get("excludeAllergens", []))
    diet_req = set(need["diet"]) | (set(mandate["hardExclusions"]["diet"]) if mandate else set())
    hab = sig.habitual(buyer, need["kind"]) if need["kind"] else None
    qty_req = float(req["qty"])
    unit_req = req.get("unit")
    notices = []

    # leftovers on hand reduce the need (only when the caller opts in, e.g. event planning)
    leftover_used = 0.0
    for lo in ctx.get("leftovers", []):
        lp = catalog.by_gtin(lo["gtin"])
        if lo["status"] == "available" and need["kind"] and lp["kind"] == need["kind"] \
                and set(need["diet"]) <= set(lp["diet"]) and lo["bestBefore"] >= d2s(need_by):
            txt = f"You have {fmt_qty(lo['qty'], lp['unit'])} of {lp['name']} left from {lo.get('sourceLabel', 'an earlier order')} (best-before {day_label(s2d(lo['bestBefore']))})."
            n = {"type": "leftover", "leftoverId": lo["leftoverId"], "gtin": lo["gtin"], "qty": lo["qty"], "text": txt}
            if req.get("useLeftovers"):
                use = min(lo["qty"], qty_req - leftover_used)
                leftover_used += use
                n["applied"] = use
                n["text"] += f" Using {fmt_qty(use, lp['unit'])} first."
            notices.append(n)
    qty = max(0.0, qty_req - leftover_used)

    eligible, relaxed, excluded = [], [], []
    for g in need["candidates"]:
        p = catalog.by_gtin(g)
        reason = code = None
        bad_all = sorted((set(p["allergens"]) | set(p["mayContain"])) & excl_all)
        group = catalog.need_group_id(p)
        eff = prefs.effective(profile, p["category"], buyer.get("site", {}).get("id"))
        failed, _ = prefs.apply_filters(eff, p)
        nb = prefs.never_buy(profile, p)
        blocked_pairs = mandate["substitution"].get("blockedPairs", []) if mandate else []
        if need["kind"] and p["kind"] != need["kind"]:
            code, reason = "kind", f"Not {need['kindLabel']} — it is {catalog.KIND_LABELS.get(p['kind'], p['kind'])}"
        elif bad_all:
            contains = [a for a in bad_all if a in p["allergens"]]
            may = [a for a in bad_all if a not in p["allergens"]]
            reason = ("Contains " + ", ".join(contains) if contains else "May contain " + ", ".join(may)) + " (excluded by mandate)"
            code = "allergen"
        elif not diet_req <= set(p["diet"]):
            miss = sorted(diet_req - set(p["diet"]))
            code, reason = "diet", "Not " + " / ".join(catalog.DIET_LABELS.get(m, m) for m in miss)
        elif need["certs"] and not set(need["certs"]) <= {c["label"] for c in p["certificates"]}:
            code, reason = "certificate", "Missing certificate " + ", ".join(need["certs"])
        elif nb:
            code, reason = "never_buy", nb
        elif failed:
            code, reason = "filter", "Required filter: " + "; ".join(failed)
        elif unit_req and p["unit"] != unit_req and {p["unit"], unit_req} != {"L", "kg"}:  # food liquids: about 1 kg per litre
            code, reason = "unit", f"Sold per {p['unit']}, request is in {unit_req}"
        elif hab and [hab["gtin"], g] in blocked_pairs:
            code, reason = "blocked_swap", f"Swap from {hab['name']} blocked by mandate (kitchen rejected it)"
        elif not be.schedule(g):
            code, reason = "out_of_stock", "Out of stock, no inbound supply"
        if reason:
            excluded.append({"gtin": g, "name": p["name"], "brand": p["brand"], "code": code, "reason": reason,
                             "unitPrice": be.price(g), "unit": p["unit"],
                             "availByNeedBy": be.available_by(g, need_by)})
            continue
        missing_variant = [v for v in need["variants"] if v not in p["variant"]]
        item = {"p": p, "group": group, "eff": eff, "specRelaxed": bool(missing_variant), "missingVariant": missing_variant}
        (relaxed if missing_variant else eligible).append(item)

    strict_cover = sum(be.available_by(i["p"]["gtin"], need_by) for i in eligible)
    if strict_cover < qty and relaxed:
        notices.append({"type": "relaxed", "text": f"Not enough {variant_text(need['variants'])} {need['kindLabel']} by {day_label(need_by)} "
                        f"({fmt_qty(strict_cover, unit_req or '')}); also considering other {need['kindLabel']} as substitutes."})
        eligible += relaxed
    else:
        for i in relaxed:
            p = i["p"]
            excluded.append({"gtin": p["gtin"], "name": p["name"], "brand": p["brand"], "code": "spec",
                             "reason": f"Not {variant_text(i['missingVariant'])} (kept as fallback only if needed)",
                             "unitPrice": be.price(p["gtin"]), "unit": p["unit"],
                             "availByNeedBy": be.available_by(p["gtin"], need_by)})

    prices = [be.price(i["p"]["gtin"]) for i in eligible]
    min_price = min(prices) if prices else 0
    pref_brands = set(mandate.get("preferredBrands", [])) if mandate else set()
    favs = set(profile.get("favourites", []))
    today_iso = today.isoformat()
    ranked = []
    for i in eligible:
        p, eff = i["p"], i["eff"]
        g = p["gtin"]
        w = eff["weights"]
        price = be.price(g)
        avail = be.available_by(g, need_by)
        sched = be.schedule(g)
        ps = sig.product_signal(signals, g)
        reasons = []
        # spec
        spec = 0.4 if i["specRelaxed"] else (0.7 if hab and not set(hab["variant"]) <= set(p["variant"]) else 1.0)
        # delivery
        ontime = p["onTimeRate"]
        if ps and ps.get("onTimeN", 0) >= 3 and ps.get("onTimeRate") is not None:
            ontime = ps["onTimeRate"]
            reasons.append(f"Delivery: on time {ps['onTime']}/{ps['onTimeN']} for you (history)")
        cover = min(1.0, avail / qty) if qty else 1.0
        delivery = ontime * cover
        # quality
        quality = (p["qualityGrade"] - 1) / 4
        if ps and ps.get("avgRating"):
            quality = (quality + (ps["avgRating"] - 1) / 4) / 2
        sust = prefs.sustainability_score(p, today_iso)
        brand = 1.0 if p["brand"] in pref_brands else 0.0
        case_qty = p["caseQty"]
        full_cases = math.ceil(qty / case_qty - 1e-9) if qty else 0
        over = full_cases * case_qty - qty
        pack_fit = max(0.0, 1 - (over / qty) * 10) if qty else 1.0
        learned, ltxt = 0.5, None
        if hab and hab["gtin"] == g:
            wh = sig.weekly_history(buyer).get(g)
            learned, ltxt = 1.0, f"Your usual product ({fmt_qty(wh['median8w'], p['unit'])}/week median)" if wh else "Your usual product"
        else:
            pr = sig.pair_signal(signals, hab["gtin"], g) if hab else None
            if pr and pr["n"] >= 2:
                learned = pr["learnedValue"]
                ltxt = f"Kitchen accepted this swap {pr['accepted']}/{pr['n']} times"
            mc = next((m for m in (signals or {}).get("manualChoices", []) if m["chosen"] == g and m["n"] >= 2), None)
            if mc and learned < 0.9:
                learned, ltxt = 0.9, f"You picked this over the agent's choice {mc['n']} times"
        values = {"spec": spec, "price": (min_price / price) if price else 0, "delivery": delivery, "quality": quality,
                  "sustainability": sust, "brand": brand, "packFit": pack_fit, "learned": learned}
        breakdown = [{"criterion": c, "label": prefs.CRITERIA_LABELS[c], "weight": w[c], "value": round(values[c], 4),
                      "contribution": round(w[c] * values[c], 4)} for c in prefs.CRITERIA]
        if ltxt:
            delta_l = round(w["learned"] * (learned - 0.5), 3)
            reasons.append(f"{ltxt} ({'+' if delta_l >= 0 else ''}{delta_l:.3f})")
        bonuses = []
        _, pref_ok = prefs.apply_filters(eff, p)
        for lab in pref_ok:
            bonuses.append({"label": f"{lab} preferred", "value": prefs.PREFERRED_BONUS})
        if g in favs:
            bonuses.append({"label": "Favourite", "value": prefs.FAVOURITE_BONUS})
        score = round(sum(b["contribution"] for b in breakdown) + sum(b["value"] for b in bonuses), 4)
        late_only = avail <= 0
        if usage and usage.get("date"):
            dd = s2d(usage["date"])
            if s2d(sched[0]["date"]) + timedelta(days=p.get("shelfLifeDays", 365)) < dd + timedelta(days=1):
                reasons.append(f"Shelf-life risk: {p['shelfLifeDays']} d shelf life vs usage on {day_label(dd)}")
        ranked.append({
            "gtin": g, "name": p["name"], "brand": p["brand"], "category": p["category"], "kind": p["kind"],
            "needGroup": i["group"], "unit": p["unit"], "packSize": p["packSize"], "unitsPerCase": p["unitsPerCase"],
            "caseQty": case_qty, "unitPrice": price, "availByNeedBy": avail, "schedule": sched,
            "earliest": sched[0]["date"] if sched else None, "lateOnly": late_only, "specRelaxed": i["specRelaxed"],
            "certificates": [c["label"] for c in p["certificates"]], "origin": p["origin"], "qualityGrade": p["qualityGrade"],
            "allergens": p["allergens"], "mayContain": p["mayContain"], "diet": p["diet"],
            "score": score, "breakdown": breakdown, "bonuses": bonuses, "reasons": reasons,
            "favourite": g in favs, "scope": eff["scope"], "preset": eff.get("preset"),
            "fullCases": full_cases, "fullOverage": round(over, 3),
        })

    # ordering: manual choice > pinned default > fallback list > score
    ng_prefs = profile.get("needGroups", {})
    def order_key(it):
        if choice and it["gtin"] == choice:
            return (0, 0, -it["score"])
        np_ = ng_prefs.get(it["needGroup"], {})
        if not it["lateOnly"] and np_.get("pinned") == it["gtin"]:
            return (1, 0, -it["score"])
        fb = np_.get("fallback", [])
        if not it["lateOnly"] and it["gtin"] in fb:
            return (2, fb.index(it["gtin"]), -it["score"])
        return (3, 1 if it["specRelaxed"] else 0, -it["score"])
    ranked.sort(key=order_key)
    for idx, it in enumerate(ranked):
        k = order_key(it)
        it["rank"] = idx + 1
        it["tier"] = TIERS[idx] if idx < 3 else "ALSO"
        it["rankReason"] = {0: "Your choice", 1: "Pinned default", 2: f"Fallback #{k[1] + 1}", 3: "Highest score" if idx == 0 else "Score"}[k[0]]

    primary = catalog.by_gtin(ranked[0]["gtin"]) if ranked else None
    for it in ranked:
        it["_short"] = it["availByNeedBy"] < qty
        p = catalog.by_gtin(it["gtin"])
        it["tradeoff"] = tradeoff(it, ranked[0], p, primary, need_by)
        if primary and it["gtin"] != primary["gtin"]:
            it.update(substitution_meta(p, primary))
        else:
            it["changes"], it["priceDeltaPct"] = [], 0.0

    line = {"lineId": req["lineId"], "text": req["text"], "qty": qty_req, "qtyAfterLeftovers": qty,
            "unit": unit_req or (primary["unit"] if primary else None),
            "need": {"kind": need["kind"], "kindLabel": need.get("kindLabel"), "variants": need["variants"],
                     "diet": sorted(diet_req), "certs": need["certs"], "excludedAllergens": sorted(excl_all),
                     "needGroup": ranked[0]["needGroup"] if ranked else None,
                     "needGroupLabel": catalog.need_group_label(ranked[0]["needGroup"]) if ranked else None},
            "habitualGtin": hab["gtin"] if hab else None,
            "primaryGtin": primary["gtin"] if primary else None,
            "agentPickGtin": None, "manualChoice": choice,
            "ranked": ranked, "excluded": excluded, "notices": notices}
    line["plans"] = build_plans(line, need_by, qty)
    return line


def tradeoff(it, best, p, primary, need_by) -> str:
    if it is best:
        bits = []
        if it["rankReason"] in ("Pinned default", "Your choice"):
            bits.append(it["rankReason"].lower())
        top = sorted(it["breakdown"], key=lambda b: -b["contribution"])[:2]
        bits += [b["label"].lower() for b in top]
        if it["lateOnly"]:
            cover = "available only after the need-by date"
        elif it.get("_short"):
            cover = f"only {fmt_qty(it['availByNeedBy'], it['unit'])} by {day_label(need_by)} (partial)"
        else:
            cover = "covers the full quantity"
        return f"Top pick: {', '.join(bits)}; {cover}."
    diffs = []
    if abs(it["availByNeedBy"] - best["availByNeedBy"]) > 1e-9:
        diffs.append(f"{fmt_qty(it['availByNeedBy'], it['unit'])} by {day_label(need_by)} vs {fmt_qty(best['availByNeedBy'], best['unit'])}")
    d = (it["unitPrice"] - best["unitPrice"]) / best["unitPrice"] * 100 if best["unitPrice"] else 0
    if abs(d) >= 0.05:
        diffs.append(f"{'+' if d > 0 else '−'}{abs(d):.1f}% per {it['unit']}")
    if it["brand"] != best["brand"]:
        diffs.append(f"other brand ({it['brand']})")
    if abs(it["packSize"] - best["packSize"]) > 1e-9:
        diffs.append(f"{it['packSize']:g} {it['unit']} packs")
    if primary and sorted(p["variant"]) != sorted(primary["variant"]):
        diffs.append(spec_diff(p, primary))
    if it["lateOnly"] and it["earliest"]:
        diffs.append(f"first delivery {day_label(s2d(it['earliest']))}")
    s = ", ".join(diffs[:4]) or "similar on all criteria"
    return s[0].upper() + s[1:] + "."


def _mk_line(line, it, cases, qty_needed, delivery: date, role_primary_gtin, idx, label):
    p = catalog.by_gtin(it["gtin"])
    qty = round(cases * it["caseQty"], 3)
    over = round(max(0.0, qty - qty_needed), 3)
    primary = catalog.by_gtin(role_primary_gtin)
    is_sub = it["gtin"] != role_primary_gtin
    meta = substitution_meta(p, primary) if is_sub else {"changes": [], "priceDeltaPct": 0.0}
    return {
        "lineId": f"{line['lineId']}-{idx}", "requestLineId": line["lineId"], "offerId": None,
        "gtin": it["gtin"], "name": it["name"], "brand": it["brand"], "category": it["category"], "kind": it["kind"],
        "unit": it["unit"], "packSize": it["packSize"], "unitsPerCase": it["unitsPerCase"], "caseQty": it["caseQty"],
        "cases": cases, "qty": qty, "overage": over, "unitPrice": it["unitPrice"], "lineTotal": r2(qty * it["unitPrice"]),
        "deliveryDate": d2s(delivery), "role": "substitute" if is_sub else "primary",
        "substituteFor": {"gtin": primary["gtin"], "name": primary["name"]} if is_sub else None,
        "changes": meta["changes"], "priceDeltaPct": meta["priceDeltaPct"],
        "changeText": describe_changes(p, primary, meta["changes"]) if is_sub else "",
        "tier": it["tier"], "rank": it["rank"], "certificates": it["certificates"],
        "roundingNote": f"{cases} cases × {it['caseQty']:g} {it['unit']} = {fmt_qty(qty, it['unit'])}" + (f" (+{fmt_qty(over, it['unit'])} over {label})" if over > 1e-9 else ""),
    }


def _deliver_on(it, need_by: date) -> date:
    first = s2d(it["earliest"])
    return need_by if first <= need_by else first


def build_plans(line: dict, need_by: date, qty: float) -> list[dict]:
    ranked = line["ranked"]
    if not ranked or qty <= 0:
        return []
    prim = ranked[0]
    pg = prim["gtin"]
    plans = []

    def finish(strategy, title, lines):
        by = sum(l["qty"] for l in lines if l["deliveryDate"] <= d2s(need_by))
        tot = sum(l["qty"] for l in lines)
        return {"strategy": strategy, "title": title, "lines": lines, "total": r2(sum(l["lineTotal"] for l in lines)),
                "coverage": {"requested": qty, "byNeedBy": round(min(by, qty), 3), "total": round(tot, 3),
                             "pct": round(min(1.0, tot / qty) * 100, 1), "pctByNeedBy": round(min(1.0, by / qty) * 100, 1)},
                "deliveryDates": sorted({l["deliveryDate"] for l in lines}),
                "splitCount": len(lines), "overage": round(sum(l["overage"] for l in lines), 3)}

    if prim["availByNeedBy"] >= qty:
        c = prim["fullCases"]
        plans.append(finish("single", f"{prim['brand']} — full quantity", [_mk_line(line, prim, c, qty, need_by if s2d(prim['earliest']) <= need_by else s2d(prim['earliest']), pg, 1, 'requested')]))
        return label_plans(plans, line, need_by)

    # A: split across products (rank order, on-time stock only)
    lines, rest, idx = [], qty, 1
    for it in ranked:
        if rest <= 1e-9:
            break
        if it["lateOnly"]:
            continue
        maxc = math.floor(it["availByNeedBy"] / it["caseQty"] + 1e-9)
        need_c = math.ceil(rest / it["caseQty"] - 1e-9)
        c = min(maxc, need_c)
        if c <= 0:
            continue
        lines.append(_mk_line(line, it, c, rest, _deliver_on(it, need_by), pg, idx, "requested"))
        rest -= c * it["caseQty"]
        idx += 1
    if lines:
        strat = "split_products" if len(lines) > 1 else ("single" if lines[0]["gtin"] == pg else "substitute")
        title = "Split across products" if len(lines) > 1 else f"{lines[0]['brand']} — {'partial' if rest > 1e-9 else 'full quantity'}"
        if rest > 1e-9:
            strat, title = ("partial", "Partial — best available by need-by") if len(lines) == 1 else ("split_products", "Split across products (partial)")
        plans.append(finish(strat, title, lines))
    # B: single substitute covering the full quantity
    for it in ranked[1:]:
        if it["lateOnly"] or it["availByNeedBy"] < qty:
            continue
        cand = finish("substitute", f"Substitute — {it['brand']} full quantity",
                      [_mk_line(line, it, it["fullCases"], qty, _deliver_on(it, need_by), pg, 1, "requested")])
        if not any(_same(cand, p) for p in plans):
            plans.append(cand)
        break
    # C: split across delivery dates with the primary product
    total_sched = sum(s["qty"] for s in prim["schedule"])
    if total_sched >= qty:
        lines, rest, idx = [], qty, 1
        for s in prim["schedule"]:
            if rest <= 1e-9:
                break
            maxc = math.floor(s["qty"] / prim["caseQty"] + 1e-9)
            need_c = math.ceil(rest / prim["caseQty"] - 1e-9)
            c = min(maxc, need_c)
            if c <= 0:
                continue
            d = max(s2d(s["date"]), need_by) if s2d(s["date"]) <= need_by else s2d(s["date"])
            if s2d(s["date"]) <= need_by:
                d = need_by
            lines.append(_mk_line(line, prim, c, rest, d, pg, idx, "requested"))
            rest -= c * prim["caseQty"]
            idx += 1
        cand = finish("split_dates", f"{prim['brand']} — split across delivery dates", lines)
        if len(lines) > 1 or (lines and lines[0]["deliveryDate"] > d2s(need_by)):
            if not any(_same(cand, p) for p in plans):
                plans.append(cand)
    return label_plans(plans[:3], line, need_by)


def _same(a, b):
    return [(l["gtin"], l["cases"], l["deliveryDate"]) for l in a["lines"]] == [(l["gtin"], l["cases"], l["deliveryDate"]) for l in b["lines"]]


def label_plans(plans, line, need_by):
    for i, p in enumerate(plans):
        p["label"] = f"P{i + 1}"
        parts = [f"{fmt_qty(l['qty'], l['unit'])} {l['brand']} {day_label(s2d(l['deliveryDate']))}" for l in p["lines"]]
        p["summary"] = " + ".join(parts) + f" — €{p['total']:,.2f}, {p['coverage']['pctByNeedBy']:.0f}% by {day_label(need_by)}"
    return plans


def combine(lines: list[dict], need_by: date) -> list[dict]:
    """Request-level plans. Single line -> its plans. Multi-line -> P1 = each line's first plan."""
    if len(lines) == 1:
        return [dict(p) for p in lines[0]["plans"]]
    chosen = [l["plans"][0] for l in lines if l["plans"]]
    if not chosen:
        return []
    all_lines = [x for p in chosen for x in p["lines"]]
    pct = min((p["coverage"]["pct"] for p in chosen), default=0)
    pct_by = min((p["coverage"]["pctByNeedBy"] for p in chosen), default=0)
    missing = [l["lineId"] for l in lines if not l["plans"]]
    if missing:
        pct = pct_by = 0.0
    total = r2(sum(x["lineTotal"] for x in all_lines))
    return [{"label": "P1", "strategy": "multi_line", "title": f"{len(chosen)}-line order", "lines": all_lines,
             "total": total, "coverage": {"pct": pct, "pctByNeedBy": pct_by, "perLine": {p['lines'][0]['requestLineId']: p['coverage'] for p in chosen}},
             "deliveryDates": sorted({x["deliveryDate"] for x in all_lines}), "splitCount": len(all_lines),
             "overage": round(sum(x["overage"] for x in all_lines), 3),
             "summary": f"{len(all_lines)} lines — €{total:,.2f}, delivery {', '.join(day_label(s2d(d)) for d in sorted({x['deliveryDate'] for x in all_lines}))}"}]
