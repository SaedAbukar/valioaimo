"""Event menu -> ingredient needs (used by Step 4 · Plan for events).

Guests x per-portion recipe use / trim yield x (1 + service buffer), split by
diet and allergy groups into safe dish variants, then right-sized with learned
per-guest factors (Recall c) and any tip the chef accepted. Leftovers are
netted later by the planner. Port of the v1 Event Autopilot logic.
"""
from __future__ import annotations

from datetime import timedelta

from .. import catalog
from ..util import d2s, s2d

DIET_LABEL = {"vegan": "vegan", "vegetarian": "vegetarian", "gluten_free": "gluten-free", "lactose_free": "lactose-free"}


def diet_groups(brief: dict) -> list[dict]:
    c = brief["constraints"]
    g = []
    for key, n in c.get("dietCounts", {}).items():
        if key == "lactose_free":
            continue
        g.append({"key": key, "label": f"{n} {DIET_LABEL[key]}", "n": n,
                  "diet": [key] if key in ("vegan", "vegetarian") else [], "excl": ["cereals_gluten"] if key == "gluten_free" else []})
    for a, n in c.get("allergies", {}).items():
        word = {"nuts": "nut", "peanuts": "peanut", "cereals_gluten": "gluten"}.get(a, a)
        g.append({"key": a, "label": f"{n} {word} allerg{'ies' if n > 1 else 'y'}", "n": n, "allergy": True,
                  "diet": ["nut_free"] if a in ("nuts", "peanuts") else ["milk_free"] if a == "milk" else [], "excl": [a]})
    return g


def needs_variant(r: dict, grp: dict) -> bool:
    al = set(r.get("allergens", [])) | set(r.get("mayContain") or [])
    if grp["key"] == "vegan":
        return "vegan" not in r["diet"]
    if grp["key"] == "vegetarian":
        return "vegetarian" not in r["diet"] and "vegan" not in r["diet"]
    if grp["key"] == "gluten_free":
        return "gluten_free" not in r["diet"]
    if grp.get("allergy"):
        return grp["key"] in al or (grp["key"] == "nuts" and r["id"] == "choc_mousse")
    return False


def build(brief: dict, recipes_doc: dict, learned: dict, accepted_tips: list[dict]) -> dict:
    rby = {r["id"]: r for r in recipes_doc["recipes"]}
    ev = brief["event"]
    guests = ev["guests"]
    buffer = recipes_doc["styleBuffer"].get(ev["style"], 0.05)
    groups = diet_groups(brief)
    menu, ing, warnings = [], {}, []
    for d in ev["dishes"]:
        r = rby[d["recipeId"]]
        std = guests
        variants: dict[str, dict] = {}
        for g in groups:
            if not needs_variant(r, g):
                continue
            vid = r["variants"].get(g["key"])
            if not vid:
                warnings.append(f"{r['name']} has no safe version for {g['label']}.")
                continue
            std -= g["n"]
            v = variants.setdefault(vid, {"recipe": rby[vid], "n": 0, "groups": [], "diet": set(), "excl": set()})
            v["n"] += g["n"]
            v["groups"].append(g["label"])
            v["diet"].update(g["diet"])
            v["excl"].update(g["excl"])
        portions = [{"recipe": r, "n": max(0, std), "groups": ["standard"], "diet": set(), "excl": set()}] + list(variants.values())
        menu.append({"dish": d["name"], "recipeId": r["id"],
                     "portions": [{"recipeId": p["recipe"]["id"], "name": p["recipe"]["name"], "n": p["n"], "groups": p["groups"]} for p in portions]})
        for p in portions:
            if not p["n"]:
                continue
            for need, qpp, unit, yld, label in p["recipe"]["ing"]:
                e = ing.setdefault(need, {"need": need, "label": label, "unit": unit, "diet": [], "excl": [], "base": 0.0,
                                          "buffered": 0.0, "sources": [], "standard": False})
                base = p["n"] * qpp / (yld or 1)
                e["base"] += base
                e["buffered"] += base * (1 + buffer)
                e["standard"] |= "standard" in p["groups"]
                for x in p["diet"]:
                    if x != "vegetarian" and x not in e["diet"]:
                        e["diet"].append(x)
                for x in p["excl"]:
                    if x not in e["excl"]:
                        e["excl"].append(x)
                e["sources"].append({"dish": p["recipe"]["name"], "portions": p["n"], "perPortion": qpp, "unit": unit, "groups": p["groups"]})
    tipf = {t["need"]: t for t in accepted_tips}
    lines = []
    for e in ing.values():
        if e["standard"]:
            e["diet"] = [d for d in e["diet"] if d != "vegan"]
        lf = learned.get(e["need"])
        tp = tipf.get(e["need"])
        factor = (lf["factor"] if lf else 1.0) * (tp["factor"] if tp else 1.0)
        planned = e["buffered"] * factor
        need = catalog.resolve_need(e["need"])
        sample = catalog.by_gtin(need["candidates"][0]) if need["candidates"] else {}
        fresh = (sample.get("shelfLifeDays") or 365) <= 7
        need_by = s2d(ev["date"]) - timedelta(days=1 if fresh else 2)
        text = " ".join([DIET_LABEL.get(d, d.replace("_", "-")) for d in e["diet"]] + [e["need"]])
        why = [f"{s['portions']} × {s['dish']}" for s in e["sources"]]
        adj = None
        if lf or tp:
            adj = {"baseline": round(e["buffered"], 3), "planned": round(planned, 3),
                   "why": (f"your last {lf['n']} similar events used {round((1 - lf['factor']) * 100)}% less" if lf and lf["factor"] < 1
                           else f"your last {lf['n']} similar events used {round((lf['factor'] - 1) * 100)}% more" if lf else "")
                   + (" and " if lf and tp else "") + (f"you chose to order {tp['cutPct']}% less" if tp else "")}
        lines.append({"lineId": f"I{len(lines) + 1}", "text": text, "need": e["need"], "label": e["label"],
                      "qty": round(planned, 3), "unit": e["unit"], "needBy": d2s(need_by), "useLeftovers": True,
                      "excludeAllergens": e["excl"], "diet": e["diet"], "sources": e["sources"], "why": why,
                      "learned": lf, "tip": tp, "qtyAdjustment": adj})
    return {"menu": menu, "lines": lines, "groups": [g["label"] for g in groups], "warnings": warnings, "buffer": buffer}
