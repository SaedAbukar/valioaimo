"""Deterministic guardrail engine. The agent proposes; this decides.

Outcome = strictest fired rule (BLOCK > APPROVE > NOTIFY > AUTO). Every decision
stores ruleId + a templated plain-language reason (rules.yaml).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from . import catalog, signals as sig
from . import preferences as prefs
from .util import money, render

RANK = {"AUTO": 0, "NOTIFY": 1, "APPROVE": 2, "BLOCK": 3}


@lru_cache(maxsize=1)
def rules() -> dict:
    data = yaml.safe_load((Path(__file__).parent / "rules.yaml").read_text())
    data["byId"] = {r["id"]: r for r in data["rules"]}
    return data


def _fmt_q(q, unit):
    return f"{q:,.0f} {unit}" if abs(q - round(q)) < 1e-9 else f"{q:,.1f} {unit}"


def evaluate(ctx: dict) -> dict:
    R = rules()["byId"]
    params = rules()["params"]
    out: list[dict] = []
    suppressed: list[dict] = []
    m = ctx.get("mandate")
    buyer = ctx["buyer"]
    lines = ctx["lines"]
    issuer = m["issuedBy"]["name"] if m else "—"

    def fire(rid, values, line_ids=None, outcome=None):
        out.append({"ruleId": rid, "title": R[rid]["title"], "outcome": outcome or R[rid]["outcome"],
                    "reason": render(R[rid]["reason"], values), "lineIds": line_ids or [], "side": R[rid]["side"]})

    # V3 kill switch / R0 mandate
    if ctx.get("killSwitch", {}).get("on"):
        fire("V3", {"agent": ctx.get("agentId"), "by": ctx["killSwitch"].get("by", "ops")})
    mc = ctx.get("mandateCheck", {"ok": bool(m), "detail": "missing"})
    if not mc["ok"]:
        fire("R0", {"detail": mc["detail"]})
    if m:
        excl = set(m["hardExclusions"]["allergens"])
        diet_req = set(m["hardExclusions"]["diet"])
        sub = m["substitution"]
        silent = set(sub.get("silentCategories", []))
        allowed = set(m["allowedCategories"])
        profile = ctx.get("profile")
        signals = ctx.get("signals")
        for ln in lines:
            p = catalog.by_gtin(ln["gtin"])
            bad = sorted((set(p["allergens"]) | set(p["mayContain"])) & excl)
            miss = sorted(diet_req - set(p["diet"]))
            if bad or miss:
                fire("R1", {"product": p["name"], "violations": ", ".join(bad + [catalog.DIET_LABELS.get(x, x) + " requirement" for x in miss]),
                            "issuer": issuer}, [ln["lineId"]])
            if p["category"] not in allowed:
                fire("R9", {"product": p["name"], "category": p["category"]}, [ln["lineId"]])
            if ln.get("role") == "substitute" and ln.get("substituteFor"):
                prim = catalog.by_gtin(ln["substituteFor"]["gtin"])
                delta = ln.get("priceDeltaPct", 0.0)
                ch = ln.get("changes", [])
                why = []
                if delta > sub["maxPriceDeltaPct"] + 1e-9:
                    why.append(f"price delta above the {sub['maxPriceDeltaPct']:g}% tolerance")
                if "category change" in ch and sub.get("sameCategoryOnly", True):
                    why.append("category changed")
                if "brand switch" in ch and not sub.get("allowBrandSwitch", True):
                    why.append("brand switches not allowed")
                if "pack size" in ch and not sub.get("allowPackSizeChange", True):
                    why.append("pack-size changes not allowed")
                if "spec change" in ch:
                    why.append("product spec differs")
                if "allergen profile" in ch:
                    why.append("allergen/diet profile changed")
                if [prim["gtin"], p["gtin"]] in sub.get("blockedPairs", []):
                    why.append("this swap is blocked by the mandate")
                vals = {"sub": p["name"], "primary": prim["name"], "changes": ln.get("changeText") or ", ".join(ch) or "same spec",
                        "delta": f"{'+' if delta >= 0 else '−'}{abs(delta):.1f}%", "unit": p["unit"],
                        "max": f"{sub['maxPriceDeltaPct']:g}%", "why": " and ".join(why)}
                if why:
                    fire("R5", vals, [ln["lineId"]])
                elif p["category"] in silent:
                    suppressed.append({"ruleId": "R4", "lineIds": [ln["lineId"]],
                                       "reason": f"Silent swap: mandate v{m.get('version', 1)} pre-approves in-tolerance swaps in {p['category']}."})
                else:
                    fire("R4", vals, [ln["lineId"]])
            if not sig.ever_ordered(buyer, signals, p["gtin"]):
                fire("R8", {"product": p["name"], "buyer": buyer["name"]}, [ln["lineId"]])
            if profile:
                eff = prefs.effective(profile, p["category"], buyer.get("site", {}).get("id"))
                failed, _ = prefs.apply_filters(eff, p)
                nb = prefs.never_buy(profile, p)
                for f in failed + ([nb] if nb else []):
                    fire("R11", {"product": p["name"], "filter": f, "version": profile["version"]}, [ln["lineId"]],
                         outcome=profile.get("filterViolationOutcome", "APPROVE"))
            fav = ln.get("favouriteAvailable")
            if fav and fav != p["gtin"]:
                fire("R12", {"product": p["name"], "favourite": catalog.by_gtin(fav)["name"]}, [ln["lineId"]])
            # Valio Aimo-side quantity sanity cap
            wh = sig.weekly_history(buyer).get(p["gtin"])
            if wh and ln["qty"] > params["sanityMultiplier"] * wh["median8w"]:
                fire("V2", {"qty": _fmt_q(ln["qty"], p["unit"]), "product": p["name"], "mult": params["sanityMultiplier"],
                            "median": _fmt_q(wh["median8w"], p["unit"])}, [ln["lineId"]])
            adj = ln.get("qtyAdjustment")
            if adj and adj.get("baseline"):
                d = (ln["qty"] - adj["baseline"]) / adj["baseline"] * 100
                if abs(d) > 10:
                    fire("R13", {"product": p["name"], "planned": _fmt_q(ln["qty"], p["unit"]), "baseline": _fmt_q(adj["baseline"], p["unit"]),
                                 "delta": f"{'+' if d >= 0 else '−'}{abs(d):.0f}%", "why": adj.get("why", "history")},
                         [ln["lineId"]], outcome="APPROVE" if abs(d) > 30 else "NOTIFY")
        total = ctx["total"]
        ev = ctx.get("event")
        per_order = m["limits"].get("perEventEUR", m["limits"]["perOrderEUR"]) if ev else m["limits"]["perOrderEUR"]
        if total > per_order + 1e-9:
            fire("R2", {"total": money(total), "limit": money(per_order) + (" (per event)" if ev else ""), "issuer": issuer})
        if ctx.get("mtd", 0) + total > m["limits"]["perMonthEUR"] + 1e-9:
            fire("R3", {"mtd": money(ctx.get("mtd", 0)), "total": money(total), "limit": money(m["limits"]["perMonthEUR"])})
        if ev and ev.get("guests") and m["limits"].get("perGuestEUR"):
            pg = total / ev["guests"]
            if pg > m["limits"]["perGuestEUR"] + 1e-9:
                fire("R14", {"perGuest": money(pg), "target": money(m["limits"]["perGuestEUR"]), "event": ev.get("name", "the event")})
        # coverage / split / timing per request line
        for rl in ctx.get("requestLines", []):
            ls = [l for l in lines if l.get("requestLineId") == rl["lineId"]]
            if not ls:
                continue
            got = sum(l["qty"] for l in ls)
            by = sum(l["qty"] for l in ls if l["deliveryDate"] <= rl["needBy"])
            name = catalog.by_gtin(ls[0]["gtin"])["name"]
            unit = ls[0]["unit"]
            if got + 1e-9 < rl["qty"]:
                fire("R6", {"detail": f"Only {_fmt_q(got, unit)} of {_fmt_q(rl['qty'], unit)} requested can be supplied ({got / rl['qty'] * 100:.0f}% coverage)."},
                     [l["lineId"] for l in ls])
            elif len({l["gtin"] for l in ls}) > 1:
                cats = {l["category"] for l in ls}
                if cats <= silent:
                    suppressed.append({"ruleId": "R6", "lineIds": [l["lineId"] for l in ls],
                                       "reason": f"Split to 100% in {', '.join(sorted(cats))} pre-approved by mandate v{m.get('version', 1)}."})
                else:
                    fire("R6", {"detail": f"Need split across {len({l['gtin'] for l in ls})} products to reach exactly 100% ({_fmt_q(got, unit)})."},
                         [l["lineId"] for l in ls], outcome="NOTIFY")
            for l in ls:
                if l["deliveryDate"] > rl["needBy"]:
                    fire("R7", {"qty": _fmt_q(l["qty"], l["unit"]), "product": l["name"], "date": l["deliveryDate"], "needBy": rl["needBy"]}, [l["lineId"]])
        so = ctx.get("standingOrder")
        if so and so.get("median"):
            d = (so["qty"] - so["median"]) / so["median"] * 100
            if abs(d) > params["driftThresholdPct"]:
                fire("R10", {"so": so["id"], "qty": _fmt_q(so["qty"], so["unit"]), "drift": f"{'+' if d >= 0 else '−'}{abs(d):.0f}%",
                             "median": _fmt_q(so["median"], so["unit"])})
        b = ctx["buyer"]
        if b.get("openInvoicesEUR", 0) + total > b.get("creditLimitEUR", 1e12):
            fire("V1", {"open": money(b["openInvoicesEUR"]), "total": money(total), "limit": money(b["creditLimitEUR"]), "buyer": b["name"]})
    outcome = "AUTO"
    for d in out:
        if RANK[d["outcome"]] > RANK[outcome]:
            outcome = d["outcome"]
    return {"outcome": outcome, "decisions": out, "suppressed": suppressed,
            "ruleIds": sorted({d["ruleId"] for d in out}, key=lambda x: (x[0], int(x[1:]))),
            "evaluated": [r["id"] for r in rules()["rules"]],
            "summary": summary(outcome, out)}


def summary(outcome: str, decisions: list[dict]) -> str:
    if outcome == "AUTO":
        return "Within mandate: the agent may order without human involvement."
    top = [d for d in decisions if d["outcome"] == outcome]
    ids = ", ".join(sorted({d["ruleId"] for d in top}))
    return {"NOTIFY": f"Allowed; buyer is notified ({ids}).",
            "APPROVE": f"Needs human approval ({ids}).",
            "BLOCK": f"Blocked ({ids}); the agent cannot proceed."}[outcome]


def published_rules(gw) -> dict:
    """The guardrails as published to agents: what the agent decides alone vs. what needs a human.
    Evaluated by the gateway (this module), never by the agent; the strictest fired rule wins."""
    rs = rules()["rules"]
    by = lambda o: [{"id": r["id"], "title": r["title"], "side": r["side"]} for r in rs if r["outcome"] == o]  # noqa: E731
    return {
        "version": rules()["version"], "decidedBy": "the gateway (gateway/policy.py + rules.yaml), never the agent or its LLM",
        "precedence": rules()["precedence"],
        "autonomy": {
            "agentDecidesAlone": "Orders where no rule below fires: placed at once within the signed mandate (AUTO).",
            "agentDecidesAndTells": by("NOTIFY"),
            "needsNamedHumanOk": by("APPROVE"),
            "neverAllowed": by("BLOCK"),
        },
        "limitsPerBuyer": {bid: {"limits": b["mandate"]["limits"], "approvers": [a["name"] + ", " + a["role"] for a in b["approvers"]],
                                 "neverOrder": b["mandate"].get("hardExclusions", {}).get("allergens", [])}
                           for bid, b in gw.buyers.items()},
        "rules": rs,
    }
