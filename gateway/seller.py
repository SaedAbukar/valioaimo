"""Valio Aimo's proactive seller agent (plan v5 Appendix).

The seller looks at ONE buyer's own data with Valio Aimo (favourites and past orders) and the real
assortment, and suggests at most 3 products at a time:

  seasonal       something for the season on the gateway clock (Christmas, game season)
  better_option  a product like one the buyer orders often that wins on the buyer's own criteria
                 (lower CO2e, a Hyvää Suomesta label, higher delivery reliability)
  new_similar    new to this buyer, similar to something they order often

Each suggestion has a plain reason, a trade-off, its source data, a price from the adapter (mock API
when configured) and an expiry. It is signed by the gateway key as `suggestion+jwt` and marked
promotional, so a buyer's agent can tell it from its own recall.

Hard rules: never anything the signed mandate excludes (allergens, diet, categories) or the buyer's
preferences forbid (never-buy list); never added to a basket (accepting re-plans through the normal
playbook: plan_basket {acceptSuggestion} -> check_basket); no price negotiation; at most 3 open per
buyer; a dismissed product is not suggested again for 30 days; buyers can opt out (mandate
preferences.sellerSuggestions = false, or profile sellerSuggestions = false). Every suggestion
created, shown, accepted or dismissed is audited.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import aimo_products, catalog, lookup, preferences as prefs
from .playbook import discover, recall as R
from .util import d2s, iso, new_id, parse_dt

ACTOR = "agent:valio-aimo-seller"
FEEDBACK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["decision"],
    "properties": {
        "decision": {"enum": ["accepted", "dismissed"], "description": "accepted (you will use it) or dismissed (not again for 30 days)."},
        "reason": {"type": "string", "maxLength": 500, "description": "Optional plain reason, kept in the audit log."},
        "idempotencyKey": {"type": "string", "maxLength": 200, "description": "Retry-safe: one decision per key."}},
    "examples": [{"decision": "dismissed", "reason": "not on our menu this year"}, {"decision": "accepted"}]}
ISSUER = "Valio Aimo seller agent"
MAX_OPEN = 3
DISMISS_DAYS = 30
VALID_DAYS = 7
RERUN_MIN = 10  # the seller looks again at most every 10 minutes of gateway time per buyer

# (month, day) windows on the gateway clock; picks are real-assortment queries with the category they belong to
SEASONS = [
    {"id": "christmas", "label": "Christmas", "from": (11, 1), "to": (12, 24),
     "picks": [("joulukinkku", "meat", "Christmas ham"), ("rosolli", "produce", "beetroot salad (rosolli)"),
               ("glögi", "dry_goods", "glögi")]},
    {"id": "game", "label": "game season", "from": (9, 1), "to": (11, 30),
     "picks": [("poro", "meat", "reindeer"), ("hirvi", "meat", "elk")]},
]
LABEL = "Hyvää Suomesta"


# ------------------------------------------------------------------ state
def state(gw) -> dict:
    if not hasattr(gw, "seller_state") or gw.seller_state is None:
        gw.seller_state = {"suggestions": {}, "dismissed": {}, "lastRun": {}}
    return gw.seller_state


def opted_out(gw, bid: str) -> bool:
    m = (gw.mandates.get(bid) or {}).get("mandate", {})
    if (m.get("preferences") or {}).get("sellerSuggestions") is False:
        return True
    return gw.profiles.get(bid, {}).get("sellerSuggestions") is False


def dismissed_recently(gw, bid: str, product_id: str) -> bool:
    at = state(gw)["dismissed"].get(bid, {}).get(product_id)
    return bool(at) and gw.clock.now() - parse_dt(at) < timedelta(days=DISMISS_DAYS)


def _expire(gw):
    now = iso(gw.clock.now())
    for s in state(gw)["suggestions"].values():
        if s["status"] == "open" and s["validUntil"] < now:
            s["status"] = "expired"


def open_for(gw, bid: str) -> list[dict]:
    _expire(gw)
    if opted_out(gw, bid):
        return []
    return [s for s in state(gw)["suggestions"].values() if s["buyerId"] == bid and s["status"] == "open"]


def get(gw, sid: str) -> dict | None:
    return state(gw)["suggestions"].get(sid)


# ------------------------------------------------------------------ what the buyer buys
def _bought(gw, bid: str) -> tuple[list[dict], set[str]]:
    """Curated products the buyer orders often (favourites first, then by order count) and every
    real Valio Aimo id they have bought (so 'new to you' is true)."""
    mem = R.memory(gw, bid)
    count: dict[str, int] = {}
    for o in mem["orders"]:
        for ln in o["lines"]:
            if ln.get("key"):
                count[ln["key"]] = count.get(ln["key"], 0) + 1
    keys = list(dict.fromkeys([f["key"] for f in mem["favourites"]] + sorted(count, key=lambda k: -count[k])))
    prods = [p for k in keys if (p := catalog.by_key(k))]
    ids = {str(p.get("aimoId") or p.get("aimoProductId") or "") for p in prods} - {""}
    for o in gw.backend.orders:
        for ln in o.get("lines", []):
            p = catalog.by_gtin(ln["gtin"])
            if p and p.get("aimoProductId"):
                ids.add(str(p["aimoProductId"]))
    return prods, ids


def _allowed(gw, bid: str, rec: dict, category: str) -> bool:
    """The signed mandate and the buyer's preferences decide what may be suggested at all."""
    m = gw.mandates[bid]["mandate"]
    pub = aimo_products.public(rec)
    excl = set(m["hardExclusions"]["allergens"])
    if (set(pub["contains"]) | set(pub["mayContain"])) & excl:
        return False
    if not set(m["hardExclusions"]["diet"]) <= set(pub["diet"]):
        return False
    if category not in m.get("allowedCategories", []):
        return False
    shape = {"gtin": f"aimo:{rec['id']}", "brand": rec.get("brand") or rec.get("vendor", "").title()}
    if prefs.never_buy(gw.profiles[bid], shape):
        return False
    avoid = set((m.get("preferences") or {}).get("avoidSuppliers", []))
    return rec.get("vendor") not in avoid


# ------------------------------------------------------------------ candidates
def _season(today: date) -> list[dict]:
    md = (today.month, today.day)
    return [s for s in SEASONS if s["from"] <= md <= s["to"]]


def _query(p: dict) -> str:
    return discover.query_fi(" ".join([*p.get("variant", []), p["kind"]]).replace("_", "-"))


def _candidates(gw, bid: str) -> list[dict]:
    m = gw.mandates[bid]["mandate"]
    excl, diet = m["hardExclusions"]["allergens"], m["hardExclusions"]["diet"]
    prods, bought = _bought(gw, bid)
    out = []
    for season in _season(gw.clock.today()):
        for q, cat, what in season["picks"]:
            for hit in aimo_products.search(q, exclude_allergens=excl, diet=diet, limit=6)["products"]:
                if (hit.get("kgPerSalesUnit") or 1) < 0.2:  # a kitchen buys packs, not 35 g sachets
                    continue
                out.append({"type": "seasonal", "rec": aimo_products.by_id(hit["productId"]), "category": cat, "action": "add",
                            "season": season, "what": what})
                break
    for fav in prods[:6]:
        hits = aimo_products.search(_query(fav), exclude_allergens=excl, diet=diet, limit=6)["products"]
        for hit in hits:
            if hit["productId"] in bought:
                continue
            rec = aimo_products.by_id(hit["productId"])
            wins = _wins(fav, hit)
            out.append({"type": "better_option" if wins else "new_similar", "rec": rec, "category": fav["category"],
                        "action": "replace", "fav": fav, "wins": wins})
    return out


def _wins(fav: dict, hit: dict) -> list[str]:
    """Where a real product beats the buyer's usual one on the buyer's own criteria."""
    w = []
    co2, fco2 = hit.get("co2eKgPerKg"), fav.get("co2eKgPerKg")
    if co2 is not None and fco2 and co2 < fco2 * 0.9:
        w.append(f"has a lower carbon footprint ({co2:.1f} vs {fco2:.1f} kg CO2e per kg)")
    fav_labels = {c["label"] for c in fav.get("certificates", [])}
    if any(LABEL in x for x in hit.get("labels", [])) and not any(LABEL in x for x in fav_labels):
        w.append("carries the Hyvää Suomesta label")
    rel, frel = hit.get("deliveryReliability"), fav.get("onTimeRate")
    if rel is not None and frel and rel >= frel + 0.02:
        w.append(f"is delivered on time more often ({rel:.0%} vs {frel:.0%})")
    return w


# ------------------------------------------------------------------ build, sign, deliver
def _price(gw, rec: dict, need_by: date) -> dict:
    prices, avail = lookup._live(gw, [rec["id"]], need_by)
    row = lookup._row(gw, rec, need_by, None, prices, avail)
    return {"perUnit": row["price"]["perUnit"], "unit": row["price"]["unit"], "perSalesUnit": row["price"]["perSalesUnit"],
            "currency": "EUR", "source": row["price"]["source"], "availability": row["availability"]["status"],
            "content": row["content"]["perSalesUnit"]}


def _build(gw, bid: str, cand: dict) -> dict:
    rec = cand["rec"]
    now = gw.clock.now()
    need_by = gw.clock.today() + timedelta(days=3)
    price = _price(gw, rec, need_by)
    name = rec.get("en") or rec.get("fi")
    if cand["type"] == "seasonal":
        reason = f"It is {cand['season']['label']}: {name} is in season in the Valio Aimo assortment."
        trade = "A product you have not ordered before; one pack is suggested, change the amount if you add it."
        source = [f"season '{cand['season']['id']}' on the gateway clock ({d2s(gw.clock.today())})", "Valio Aimo assortment"]
        replaces = None
        until = min(now + timedelta(days=VALID_DAYS),
                    now.replace(month=cand["season"]["to"][0], day=cand["season"]["to"][1], hour=21, minute=59, second=0))
    else:
        fav = cand["fav"]
        fav_price = gw.backend.price(fav["gtin"]) if fav["gtin"] in gw.backend.prices else fav["unitPrice"]
        if cand["type"] == "better_option":
            reason = f"Like your usual {fav['name']}, but it {' and '.join(cand['wins'])}."
        else:
            reason = f"New to you, similar to {fav['name']} that you order often."
        diff = price["perUnit"] - fav_price if price["unit"] == fav["unit"] else None
        if diff is None:
            trade = f"Sold per {price['unit']}, your usual is per {fav['unit']}."
        elif abs(diff) < 0.005:
            trade = f"Same price per {fav['unit']} as your usual."
        else:
            trade = f"€{abs(diff):.2f} per {fav['unit']} {'more' if diff > 0 else 'less'} than your usual; a different brand."
        source = [f"your favourites and order history ({fav['name']})", "Valio Aimo assortment (CO2e, labels, delivery reliability)"]
        replaces = {"need": fav["kind"], "productName": fav["name"], "productId": fav["gtin"]}
        until = now + timedelta(days=VALID_DAYS)
    unit, size = price["unit"], price.pop("content")
    s = {"suggestionId": new_id("SUG"), "type": cand["type"], "buyerId": bid, "issuer": ISSUER, "promotional": True,
         "productId": rec["id"], "name": name, "nameFi": rec.get("fi"), "brand": rec.get("brand") or rec.get("vendor", "").title(),
         "category": cand["category"], "action": cand["action"], "replaces": replaces,
         "suggestedQty": {"qty": size, "unit": unit}, "price": price, "reason": reason, "tradeOff": trade, "source": source,
         "createdAt": iso(now), "validUntil": iso(until), "status": "open",
         "howToUse": "plan_basket {acceptSuggestion: suggestionId} in a playbook session; the gateway re-plans and re-checks it."}
    claim = {k: s[k] for k in ("suggestionId", "type", "buyerId", "issuer", "promotional", "productId", "name", "action",
                               "replaces", "price", "reason", "tradeOff", "createdAt", "validUntil")}
    s["proof"] = {"format": "suggestion+jwt", "alg": "ES256", "kid": gw.gateway_key.kid, "jwksUri": "/.well-known/jwks.json",
                  "jws": gw.gateway_key.sign(claim, typ="suggestion+jwt")}
    return s


def run(gw, bid: str, force: bool = False, notify: bool = True) -> list[dict]:
    """Let the seller look at one buyer. Creates new suggestions up to MAX_OPEN; returns the new ones."""
    if opted_out(gw, bid) or not aimo_products.available() or bid not in gw.buyers:
        return []
    st = state(gw)
    open_now = open_for(gw, bid)
    last = st["lastRun"].get(bid)
    if len(open_now) >= MAX_OPEN or (not force and last and gw.clock.now() - parse_dt(last) < timedelta(minutes=RERUN_MIN)):
        return []
    st["lastRun"][bid] = iso(gw.clock.now())
    taken = {s["productId"] for s in st["suggestions"].values() if s["buyerId"] == bid and s["status"] in ("open", "accepted")}
    new, kinds = [], {s["type"] for s in open_now}
    cands = [c for c in _candidates(gw, bid)
             if c["rec"]["id"] not in taken and not dismissed_recently(gw, bid, c["rec"]["id"]) and _allowed(gw, bid, c["rec"], c["category"])]
    # one of each kind first, then fill
    ordered = sorted(cands, key=lambda c: (c["type"] in kinds, ["seasonal", "better_option", "new_similar"].index(c["type"])))
    for c in ordered:
        if len(open_now) + len(new) >= MAX_OPEN:
            break
        if c["rec"]["id"] in taken or c["type"] in kinds:
            continue
        s = _build(gw, bid, c)
        st["suggestions"][s["suggestionId"]] = s
        taken.add(s["productId"])
        kinds.add(s["type"])
        new.append(s)
        gw.audit.append(trace_id=None, actor=ACTOR, action="suggestion.created", buyer_id=bid,
                        refs={"suggestionId": s["suggestionId"], "productId": s["productId"], "type": s["type"]}, reason=s["reason"])
    for c in ordered:  # fewer kinds than slots: fill with more of the same
        if len(open_now) + len(new) >= MAX_OPEN:
            break
        if c["rec"]["id"] in taken:
            continue
        s = _build(gw, bid, c)
        st["suggestions"][s["suggestionId"]] = s
        taken.add(s["productId"])
        new.append(s)
        gw.audit.append(trace_id=None, actor=ACTOR, action="suggestion.created", buyer_id=bid,
                        refs={"suggestionId": s["suggestionId"], "productId": s["productId"], "type": s["type"]}, reason=s["reason"])
    if notify:
        for s in new:
            gw.events.emit_buyer(bid, "suggestion.created", event_data(s))
    if new:
        gw.save()
    return new


def event_data(s: dict) -> dict:
    return {"suggestionId": s["suggestionId"], "issuer": ISSUER, "promotional": True, "type": s["type"], "name": s["name"],
            "reason": s["reason"], "validUntil": s["validUntil"], "next": "GET /v1/suggestions or get_suggestions"}


def shown(gw, bid: str, sugs: list[dict], trace_id: str | None = None, via: str = "api"):
    for s in sugs:
        gw.audit.append(trace_id=trace_id, actor=ACTOR, action="suggestion.shown", buyer_id=bid,
                        refs={"suggestionId": s["suggestionId"], "productId": s["productId"], "via": via},
                        reason=f"showed {s['name']} to the buyer's agent ({s['type']})")


def for_buyer(gw, bid: str) -> dict:
    run(gw, bid)
    sugs = open_for(gw, bid)
    shown(gw, bid, sugs)
    return {"buyerId": bid, "optedOut": opted_out(gw, bid), "suggestions": sugs,
            "note": "Promotional suggestions from Valio Aimo's seller agent, signed (suggestion+jwt). "
                    "Nothing is added to any order; to use one, plan_basket {acceptSuggestion} in a session."}


def feedback(gw, bid: str, sid: str, decision: str, reason: str | None, actor: str, trace_id: str | None = None) -> dict:
    s = get(gw, sid)
    if not s or s["buyerId"] != bid:
        return None
    if decision not in ("accepted", "dismissed"):
        raise ValueError(decision)
    s["status"] = decision
    s["decidedAt"] = iso(gw.clock.now())
    s["feedback"] = reason
    if decision == "dismissed":
        state(gw)["dismissed"].setdefault(bid, {})[s["productId"]] = s["decidedAt"]
        state(gw)["lastRun"].pop(bid, None)  # a free slot: the seller may look again
    gw.audit.append(trace_id=trace_id, actor=actor, action=f"suggestion.{decision}", buyer_id=bid,
                    refs={"suggestionId": sid, "productId": s["productId"], "type": s["type"], "seller": ACTOR},
                    reason=f"{decision} {s['name']}" + (f": {reason}" if reason else ""))
    gw.save()
    return s
