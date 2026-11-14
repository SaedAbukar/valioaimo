"""Step 6 · Present — the session as chef-friendly cards, plus the plain-language lint.

One idea per card, one main action, at most 3 options and 3 numbers, details
behind "Why?". Wording rules and banned words come from the playbook file.
"""
from __future__ import annotations

import re

from .. import catalog
from ..util import day_label, s2d
from .engine import GuardFailed, playbook

WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def eur(x: float) -> str:
    return f"€{x:,.0f}" if x >= 100 else f"€{x:,.2f}"


def qty(q: float, unit: str) -> str:
    return f"{q:,.0f} {unit}" if abs(q - round(q)) < 1e-9 else f"{q:,.1f} {unit}"


def dlabel(s: str) -> str:
    return day_label(s2d(s))


def card(type_: str, title: str | None = None, **kw) -> dict:
    c = {"type": type_, "title": title or playbook()["cards"][type_]["title"], "text": "", "chips": [], "numbers": [],
         "options": [], "actions": [], "why": [], "items": []}
    c.update(kw)
    c["text"] = c["text"].replace("..", ".")
    c["id"] = kw.get("id") or f"{type_}-{abs(hash((type_, c['text'], str(c['chips'])))) % 10**8}"
    return c


def short(name: str) -> str:
    n = re.sub(r"\s+\d[\d,.]*\s*(l|kg|g|ml|dl|pcs)\b.*$", "", name, flags=re.I)
    return n[:48]


# ----------------------------------------------------------------- per step
def understood(brief: dict) -> dict:
    chips = []
    ev = brief.get("event")
    st = lambda k: brief[k]["status"]
    if ev:
        chips.append({"label": ev["name"] if ev["name"] != ev["typeLabel"] else ev["typeLabel"], "status": "found"})
        if ev["date"]:
            chips.append({"label": dlabel(ev["date"]), "status": st("when"), "field": "when"})
        if ev["guests"]:
            chips.append({"label": f"{ev['guests']} guests", "status": st("howMuch"), "field": "howMuch"})
        chips.append({"label": "plated" if ev["style"] == "plated" else "buffet", "status": brief["style"]["status"]})
        for d in ev["dishes"]:
            chips.append({"label": d["name"].split(" (")[0].split(",")[0], "status": "found" if d.get("said") else "assumed"})
        for k, n in brief["constraints"].get("dietCounts", {}).items():
            chips.append({"label": f"{n} {k.replace('_', '-')}", "status": "found"})
        for a, n in brief["constraints"].get("allergies", {}).items():
            word = {"nuts": "nut", "peanuts": "peanut", "cereals_gluten": "gluten"}.get(a, a)
            chips.append({"label": f"{n} {word} allerg{'ies' if n > 1 else 'y'}", "status": "found"})
        text = "Here is the event as I read it." if not brief.get("changed") else f"Now {ev['guests']} guests. I'll redo the amounts."
    else:
        for l in brief["lines"]:
            chips.append({"label": f"{qty(l['qty'], l['unit'])} {l['text']}", "status": "found"})
        if brief["when"]["value"]:
            chips.append({"label": f"by {dlabel(brief['when']['value'])}", "status": st("when"), "field": "when"})
        text = "Here is what you need, as I read it."
    chips.append({"label": brief["site"]["value"], "status": brief["site"]["status"]})
    why = []
    if ev and ev.get("added"):
        why.append("I added " + " and ".join(ev["added"]) + " because you usually serve them at this kind of event.")
    if any(c["status"] == "assumed" for c in chips):
        why.append("Grey chips are my guesses. Tap Change if one is wrong.")
    return card("understood", text=text, chips=chips, why=why,
                actions=[{"id": "ack", "label": "Looks right", "primary": True}, {"id": "change", "label": "Change"}])


def question(q: dict) -> dict:
    return card("question", text=q["text"],
                options=[{"id": f"ans-{i}", "label": a["label"], "value": a["value"], "field": q["field"]} for i, a in enumerate(q["answers"][:3])],
                actions=[], why=["I only ask when I can't safely guess. Everything else I fill in for you."])


def favourites(rec: dict, brief: dict, plan: dict | None) -> dict | None:
    sim = rec.get("similar")
    favs = [m for m in rec["matched"] if m["source"] == "favourites"]
    if brief.get("event") and sim:
        reused = sorted({short(catalog.by_gtin(m["productId"])["name"]) for m in rec["matched"] if m.get("productId")})
        text = f"Same as your {sim['name']}. It went well."
        why = [f"{sim['name']}: most products were just right."] + [f"Reused: {n}" for n in reused[:6]]
        if any(m["source"] == "learned_quantities" for m in rec["matched"]):
            why.append("Amounts follow what your guests really ate last time.")
        if any(m["source"] == "leftovers" for m in rec["matched"]):
            why.append("Leftovers you still have are used first.")
        return card("favourites", text=text, why=why, chips=[{"label": n, "status": "found"} for n in reused[:3]],
                    actions=[{"id": "ack", "label": "Use this", "primary": True}])
    if favs:
        names = [short(m["name"]) for m in favs]
        fb = [short(catalog.by_gtin(g)["name"]) for m in favs for g in m.get("fallbacks", [])]
        why = [f"Your usual: {n}" for n in names] + [f"Good stand-in last time: {n}" for n in fb]
        so = [m for m in rec["matched"] if m["source"] == "standing_orders"]
        if so:
            why.append("Your weekly standing order is separate and stays as it is.")
        return card("favourites", text=f"Your usual {names[0]}" + (" and more." if len(names) > 1 else "."),
                    chips=[{"label": n, "status": "found"} for n in names[:3]], why=why,
                    actions=[{"id": "ack", "label": "Use this", "primary": True}])
    return None


def tip(t: dict, brief: dict) -> dict:
    ev = brief["event"]["typeLabel"].lower().replace(" dinner", "")
    return card("tip", text=f"Your last 3 {ev}s had {t['need']} left over. Order {t['cutPct']}% less?",
                numbers=[], why=[f"Each time some {t['need']} was left after the event.",
                                 "If you apply it, I order less of it this time only."],
                actions=[{"id": "apply_tip", "label": "Apply", "primary": True, "payload": {"tipId": t["tipId"]}},
                         {"id": "ignore_tip", "label": "Ignore", "payload": {"tipId": t["tipId"]}}])


def choice(pc: dict) -> dict:
    opts = []
    for o in pc["options"][:3]:
        p = catalog.by_gtin(o["productId"])
        price = f"{eur(o['unitPrice'])} per {o['unit']}"
        label = o["name"] if len(o["name"]) <= 44 else o["name"][:43] + "…"
        opts.append({"id": o["productId"], "label": label, "sub": price, "tag": o["tag"], "why": o["why"],
                     "payload": {"lineId": pc["lineId"], "productId": o["productId"]}})
    return card("choice", text=f"Which {pc['need']} would you like?", options=opts,
                why=["You haven't ordered this before, so you choose once. Next time I remember it.",
                     "Prices and stock are checked with Valio Aimo right now."])


def cant_do(c: dict) -> dict:
    alt = c.get("alternative")
    if c.get("blockedProduct"):
        reason = "it may contain nuts" if "nut" in (c.get("allergen") or "").lower() else "it has something your kitchen never orders"
        late = f" Your usual one comes {dlabel(c['lateDate'])}, too late." if c.get("lateDate") else ""
        text = f"I can't get {c['need']} in time.{late} The only other one is not safe: {reason}."
    else:
        text = f"I can't find {c['need']} that fits your rules."
    acts = [{"id": "use_alternative", "label": "Use alternative", "primary": True, "payload": {"lineId": c["lineId"]}}] if alt else []
    return card("cant_do", text=text,
                chips=[{"label": f"Safe choice: {short(alt['name'])}", "status": "found"}] if alt else [],
                why=[f"{c['blockedProduct']} is not allowed for your kitchen." if c.get("blockedProduct") else "",
                     f"{short(alt['name'])} is safe for everyone and can arrive in time." if alt else "Ask your Valio Aimo contact."],
                actions=acts)


def basket(plan: dict, decision: dict, brief: dict) -> dict:
    ev = brief.get("event")
    nums = [{"label": "Total", "value": eur(plan["total"])}]
    if plan.get("perGuest"):
        nums.append({"label": "Per guest", "value": eur(plan["perGuest"])})
    nums.append({"label": "Deliveries" if len(plan["deliveryDays"]) > 1 else "Arrives",
                 "value": str(len(plan["deliveryDays"])) if len(plan["deliveryDays"]) > 1 else dlabel(plan["deliveryDays"][0])})
    groups = []
    for day in plan["deliveryDays"]:
        ls = [l for l in plan["lines"] if l["deliveryDate"] == day]
        groups.append({"day": dlabel(day), "lines": [{"name": short(l["name"]), "qty": qty(l["qty"], l["unit"]),
                                                      "price": eur(l["lineTotal"]), "why": l["why"], "source": l["source"],
                                                      "productId": l["productId"]} for l in ls]})
    dec = decision["decision"]
    text = {"auto": "Everything fits your rules. Ready when you are.",
            "tell_me": "Ready to order. I'll keep you posted.",
            "needs_ok": "Ready, but it needs an OK first.",
            "blocked": "This can't be ordered yet."}[dec]
    why = [l for l in decision["reasons"]] if dec != "auto" else ["Within your spending limit, safe for your guests, arrives on time."]
    if plan.get("leftoversUsed"):
        why.append("Uses what you already have first: " + ", ".join(f"{short(x['name'])}" for x in plan["leftoversUsed"]) + ".")
    if plan.get("adjustments"):
        why.append("Some amounts follow what your guests really used last time.")
    if decision.get("offersVerified"):
        why.append("Prices are locked with Valio Aimo for 15 minutes.")
    acts = [{"id": "order", "label": "Order", "primary": True}] if dec in ("auto", "tell_me") else []
    acts.append({"id": "see_items", "label": "See items"})
    title = "Shopping basket" if not ev else f"Basket for {ev['guests']} guests"
    return card("basket", title=title, text=text, numbers=nums, items=groups, why=why, actions=acts,
                state=dec)


def needs_ok(plan: dict, decision: dict) -> dict:
    ap = decision["approver"]
    over = decision.get("overBy") or 0
    text = (f"It's {eur(over)} over your limit, so {ap['name'].split()[0]} needs to OK it." if over > 0
            else f"{decision['reasons'][0]} {ap['name'].split()[0]} needs to OK it.")
    return card("needs_ok", text=text, numbers=[{"label": "Total", "value": eur(plan["total"])}],
                why=decision["reasons"] + [f"{ap['name']} ({ap['role']}) gets one message with everything."],
                actions=[{"id": "send_for_ok", "label": "OK", "primary": True}, {"id": "not_now", "label": "Not now"}])


def waiting(approval: dict) -> dict:
    ap = approval["approver"]
    return card("needs_ok", title="Waiting for OK", text=f"Sent to {ap['name']}. I'll order as soon as it's OK.",
                state="sent", why=["You'll see it under Orders › Waiting for OK."], actions=[])


def delivery(order: dict) -> dict:
    d = order["deliveries"]
    first = d[0]
    text = (f"Ordered. Arrives {first['label']} {first['window']}." if len(d) == 1
            else f"Ordered. {len(d)} deliveries, first on {first['label']}.")
    if order.get("amended"):
        text = "Order updated. " + text.split(". ", 1)[1]
    items = [{"day": x["label"] + " " + x["window"], "lines": [{"name": short(n)} for n in x["items"]]} for x in d]
    return card("delivery", text=text, items=items, numbers=[{"label": "Total", "value": eur(order["total"])}],
                why=["Valio Aimo confirmed the order at the locked prices."],
                actions=[{"id": "track", "label": "Track", "primary": True, "payload": {"orderId": order["orderId"]}}],
                ref={"orderId": order["orderId"]})


def how_did_it_go(s: dict) -> dict:
    plan = s["data"]["plan"]
    seen, rows = set(), []
    for l in sorted(plan["lines"], key=lambda l: (l["source"] not in ("favourites", "similar_orders"), -l["lineTotal"])):
        if l["need"] in seen:
            continue
        seen.add(l["need"])
        rows.append({"need": l["need"], "label": l["label"] if len(l["label"]) < 28 else l["need"],
                     "choices": [{"id": "all", "label": "Used it all"}, {"id": "some", "label": "Some left"},
                                 {"id": "ran_out", "label": "Ran out"}]})
    return card("how_did_it_go", text="Tap one for each. It helps me order better next time.",
                items=rows[:8], why=["Only takes a few seconds. Everything else is filled in for you."],
                actions=[{"id": "save_usage", "label": "Save", "primary": True}])


def thanks(rec: dict, tips: list[dict]) -> dict:
    good = sum(1 for l in rec["lines"] if l["label"] == "right_sized")
    text = f"Saved. {good} of {len(rec['lines'])} were just right."
    why = [f"{l['need']}: {'just right' if l['label'] == 'right_sized' else 'some left over' if l['label'] == 'over_ordered' else 'ran out'}" for l in rec["lines"]]
    if tips:
        why.append("I'll suggest a change next time.")
    return card("tip", title="Thanks", text=text, why=why, actions=[])


# ----------------------------------------------------------------- whole session
def for_session(gw, s: dict) -> list[dict]:
    d = s["data"]
    brief, rec, plan, dec = d["brief"], d["recall"], d["plan"], d["decision"]
    out = [understood(brief)]
    fav = favourites(rec, brief, plan)
    if fav:
        out.append(fav)
    for t in rec.get("tips", [])[:1]:
        out.append(tip(t, brief))
    for c in plan["cantDo"]:
        out.append(cant_do(c))
    for pc in plan["pendingChoices"][:1]:
        out.append(choice(pc))
    if not plan["cantDo"] and not plan["pendingChoices"] and plan["lines"]:
        out.append(basket(plan, dec, brief))
        if dec["decision"] == "needs_ok":
            out.append(needs_ok(plan, dec))
    return out


# ----------------------------------------------------------------- lint
def _texts(c: dict):
    for k in ("title", "text"):
        yield c.get(k, "")
    for x in c.get("chips", []):
        yield x.get("label", "")
    for x in c.get("options", []):
        yield from (x.get("label", ""), x.get("sub", ""), x.get("why", ""), x.get("tag", ""))
    for x in c.get("actions", []):
        yield x.get("label", "")
    yield from c.get("why", [])
    for g in c.get("items", []):
        for l in g.get("lines", []):
            yield l.get("why", "")


def lint(c: dict) -> list[str]:
    lang = playbook()["language"]
    errs = []
    for t in _texts(c):
        for w in lang["banned_words"]:
            flags = 0 if re.fullmatch(r"[RV]\d+", w) else re.I
            if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", t or "", flags):
                errs.append(f"banned word '{w}' in: {t}")
    body = re.sub(r"\b\d{1,2}\.\d{1,2}\.", "", c.get("text", ""))  # dates like 21.11. are not counted
    nums = len(c.get("numbers", [])) + len(re.findall(r"\d+(?:[.,]\d+)*", body))
    if nums > lang["max_numbers_per_card"]:
        errs.append(f"{nums} numbers (max {lang['max_numbers_per_card']})")
    if len(c.get("options", [])) > lang["max_options_per_card"]:
        errs.append("too many options")
    if sum(1 for a in c.get("actions", []) if a.get("primary")) > 1:
        errs.append("more than one main action")
    return errs


def lint_all(cards: list[dict]):
    bad = {c.get("type"): e for c in cards if (e := lint(c))}
    if bad:
        raise GuardFailed("Cards break the plain-language rules.", guard="plain_language", problems=bad)
