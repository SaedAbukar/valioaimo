"""Buyer Preference Profile: criteria weights, hard/soft filters, favourites, pinned defaults.

A profile is versioned and referenced by the Intent Mandate. Scope resolution:
org default <- site override <- category override (most specific wins for
`weights`, `preset` and `filters`; product lists are org-wide).
"""
from __future__ import annotations

import copy

CRITERIA = ["spec", "price", "delivery", "quality", "sustainability", "brand", "packFit", "learned"]
CRITERIA_LABELS = {"spec": "Spec match", "price": "Price per unit", "delivery": "Delivery reliability",
                   "quality": "Quality", "sustainability": "Sustainability & origin", "brand": "Brand preference",
                   "packFit": "Pack-size fit", "learned": "Learned from history"}

PRESETS = {
    # balanced == the original plan weights 0.40 spec / 0.30 price / 0.20 delivery / 0.10 preference+sustainability
    "balanced": {"spec": .40, "price": .30, "delivery": .20, "quality": 0, "sustainability": .03, "brand": .04, "packFit": 0, "learned": .03},
    "lowest_price": {"spec": .30, "price": .50, "delivery": .10, "quality": 0, "sustainability": 0, "brand": 0, "packFit": .05, "learned": .05},
    "premium_quality": {"spec": .30, "price": .10, "delivery": .15, "quality": .30, "sustainability": .05, "brand": .05, "packFit": 0, "learned": .05},
    "domestic_sustainable": {"spec": .30, "price": .15, "delivery": .15, "quality": .05, "sustainability": .30, "brand": 0, "packFit": .05, "learned": 0},
    "fastest_delivery": {"spec": .30, "price": .15, "delivery": .45, "quality": .05, "sustainability": 0, "brand": 0, "packFit": 0, "learned": .05},
}
PRESET_LABELS = {"balanced": "Balanced", "lowest_price": "Lowest price", "premium_quality": "Premium quality",
                 "domestic_sustainable": "Domestic & sustainable", "fastest_delivery": "Fastest delivery"}

FILTER_FIELDS = ["maxUnitPrice", "brand", "certificate", "origin", "minQuality", "packSize", "maxLeadTime", "supplier"]
PREFERRED_BONUS = 0.03
FAVOURITE_BONUS = 0.05


def default_profile(buyer_id: str) -> dict:
    return {
        "profileId": f"PREF-{buyer_id.split('-')[-1]}",
        "buyerId": buyer_id,
        "version": 1,
        "org": {"preset": "balanced", "weights": dict(PRESETS["balanced"]), "filters": []},
        "sites": {},
        "categories": {},
        "favourites": [],
        "neverBuy": {"gtins": [], "brands": []},
        "needGroups": {},       # groupId -> {"pinned": gtin|None, "fallback": [gtin,...]}
        "lists": [],            # [{"id","name","items":[{"gtin","qty"}]}]
        "filterViolationOutcome": "APPROVE",
    }


def normalise(weights: dict) -> dict:
    w = {c: max(0.0, float(weights.get(c, 0) or 0)) for c in CRITERIA}
    s = sum(w.values()) or 1.0
    return {c: round(v / s, 4) for c, v in w.items()}


def effective(profile: dict, category: str | None = None, site_id: str | None = None) -> dict:
    """Merge scopes; returns {preset, weights, filters, scope} (scope = most specific source)."""
    eff = copy.deepcopy(profile["org"])
    scope = "org"
    if site_id and site_id in profile.get("sites", {}):
        eff.update(copy.deepcopy(profile["sites"][site_id]))
        scope = f"site:{site_id}"
    if category and category in profile.get("categories", {}):
        eff.update(copy.deepcopy(profile["categories"][category]))
        scope = f"category:{category}"
    if "weights" not in eff:
        eff["weights"] = dict(PRESETS.get(eff.get("preset", "balanced"), PRESETS["balanced"]))
    eff["weights"] = normalise(eff["weights"])
    eff.setdefault("filters", [])
    eff["scope"] = scope
    return eff


def filter_check(f: dict, p: dict) -> tuple[bool, str]:
    """Evaluate one filter against a product. Returns (passes, label)."""
    field, vals, op = f["field"], f.get("values") or [], f.get("op", "include")
    v = f.get("value")
    if field == "maxUnitPrice":
        return p["unitPrice"] <= float(v), f"Price ≤ €{float(v):.2f}/{p['unit']}"
    if field == "minQuality":
        return p["qualityGrade"] >= float(v), f"Quality ≥ {float(v):.1f}"
    if field == "maxLeadTime":
        return p["leadTimeDays"] <= int(v), f"Lead time ≤ {int(v)} d"
    if field == "brand":
        hit = p["brand"] in vals
        return (hit if op == "include" else not hit), (f"Brand {'in' if op == 'include' else 'not'}: {', '.join(vals)}")
    if field == "supplier":
        hit = p["origin"]["supplierId"] in vals
        return (hit if op == "include" else not hit), (f"Supplier {'in' if op == 'include' else 'not'}: {', '.join(vals)}")
    if field == "certificate":
        labels = {c["label"] for c in p["certificates"]}
        return bool(labels & set(vals)), f"Certificate: {', '.join(vals)}"
    if field == "origin":
        hit = p["origin"]["country"] in vals
        return (hit if op == "include" else not hit), ("Domestic (FI)" if vals == ["FI"] else f"Origin: {', '.join(vals)}")
    if field == "packSize":
        return any(abs(p["packSize"] - float(x)) < 1e-9 for x in vals), f"Pack size: {', '.join(str(x) for x in vals)}"
    return True, field


def apply_filters(profile_eff: dict, p: dict) -> tuple[list[str], list[str]]:
    """Return (failed_required_labels, passed_preferred_labels)."""
    failed, bonus = [], []
    for f in profile_eff.get("filters", []):
        ok, label = filter_check(f, p)
        if f.get("mode") == "required" and not ok:
            failed.append(label)
        elif f.get("mode") == "preferred" and ok:
            bonus.append(label)
    return failed, bonus


def never_buy(profile: dict, p: dict) -> str | None:
    nb = profile.get("neverBuy", {})
    if p["gtin"] in nb.get("gtins", []):
        return "Never-buy list (product)"
    if p["brand"] in nb.get("brands", []):
        return f"Never-buy list (brand {p['brand']})"
    return None


def sustainability_score(p: dict, today_iso: str) -> float:
    s = 0.4 if p["origin"]["country"] == "FI" else 0.0
    labels = {c["label"] for c in p["certificates"] if c["validUntil"] >= today_iso}
    if "EU Organic" in labels:
        s += 0.3
    if labels - {"EU Organic"}:
        s += 0.2
    if p["carbonClass"] in ("A", "B"):
        s += 0.1
    return min(1.0, round(s, 4))
