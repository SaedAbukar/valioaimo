"""Catalog fixtures, need groups and free-text need resolution."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .util import tokens

DATA = Path(__file__).resolve().parent / "data"

KIND_LABELS = {
    "milk": "milk", "cream": "cream", "butter": "butter", "cheese": "cheese", "yogurt": "yogurt", "quark": "quark",
    "sour_cream": "sour cream", "eggs": "eggs", "plant_drink": "plant-based drink", "plant_cream": "plant cream",
    "plant_yogurt": "plant yogurt", "tofu": "tofu", "plant_protein": "plant protein", "spread": "spread",
    "pasta": "pasta", "rice": "rice", "cereal": "cereal", "flour": "flour", "oil": "oil", "sugar": "sugar",
    "coffee": "coffee", "tea": "tea", "canned": "canned goods", "pulses": "pulses", "condiment": "condiment",
    "seeds": "seeds", "salt": "salt", "dried_fruit": "dried fruit", "potato": "potatoes", "root_veg": "root vegetables",
    "onion": "onions", "tomato": "tomatoes", "cucumber": "cucumbers", "salad": "salad", "celery": "celery",
    "mushroom": "mushrooms", "fruit": "fruit", "berries": "berries", "beef": "beef", "chicken": "chicken",
    "pork": "pork", "cold_cuts": "cold cuts", "game": "game", "sausage": "sausages", "salmon": "salmon",
    "trout": "trout", "cod": "cod", "herring": "herring", "pikeperch": "pike-perch", "shellfish": "shellfish",
    "bread": "bread", "pastry": "pastry", "nut_butter": "nut butter", "chocolate": "chocolate", "ham_whole": "whole ham",
    "beetroot": "beetroot", "pickles": "pickles", "herbs": "herbs",
}

DIET_PATTERNS = [
    (r"lactose[- ]?free|laktoositon", "lactose_free"),
    (r"(?:milk|dairy)[- ]?free|maidoton", "milk_free"),
    (r"nut[- ]?free|pähkinätön", "nut_free"),
    (r"gluten[- ]?free|gluteeniton", "gluten_free"),
    (r"egg[- ]?free|munaton", "egg_free"),
    (r"\bvegan\b|vegaani", "vegan"),
    (r"\bvegetarian\b", "vegetarian"),
]
CERT_PATTERNS = [(r"\borganic\b|\bluomu\b", "EU Organic"), (r"\bmsc\b", "MSC"), (r"\bfairtrade\b", "Fairtrade")]
DIET_LABELS = {"lactose_free": "lactose-free", "milk_free": "milk-free", "nut_free": "nut-free",
               "gluten_free": "gluten-free", "egg_free": "egg-free", "vegan": "vegan", "vegetarian": "vegetarian"}


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    return json.loads((DATA / "catalog.json").read_text())


@lru_cache(maxsize=1)
def load_buyers() -> dict:
    return json.loads((DATA / "buyers.json").read_text())


def products() -> list[dict]:
    return load_catalog()["products"]


@lru_cache(maxsize=1)
def _idx():
    by_gtin = {p["gtin"]: p for p in products()}
    by_key = {p["key"]: p for p in products()}
    return by_gtin, by_key


_REAL: dict[str, dict] = {}  # real Valio Aimo products bridged in by the Discover step (see register_real)


def by_gtin(gtin: str) -> dict | None:
    return _idx()[0].get(gtin) or _REAL.get(gtin)


def register_real(p: dict) -> dict:
    """Make a real Valio Aimo product (curated shape, see playbook.discover.bridge) visible to planner and policy."""
    _REAL[p["gtin"]] = p
    return p


def by_key(key: str) -> dict | None:
    return _idx()[1].get(key)


def need_group_id(p: dict) -> str:
    return f"{p['kind']}:{'+'.join(sorted(p['variant']))}"


def need_group_label(group_id: str) -> str:
    kind, _, variants = group_id.partition(":")
    words = [v.replace("_", "-") for v in variants.split("+") if v]
    return " ".join(words + [KIND_LABELS.get(kind, kind)]).capitalize()


def need_groups() -> list[dict]:
    groups: dict[str, list] = {}
    for p in products():
        groups.setdefault(need_group_id(p), []).append(p["gtin"])
    return [{"id": g, "label": need_group_label(g), "kind": g.split(":")[0], "gtins": v} for g, v in sorted(groups.items())]


def digital_link(p: dict) -> str:
    return f"https://id.gs1.org/01/{p['gtin']}"


def public_product(p: dict) -> dict:
    """L0 catalog view (unsigned, browse-only)."""
    out = {k: p[k] for k in ("gtin", "aimoSku", "name", "brand", "category", "kind", "variant", "unit", "packSize",
                             "unitsPerCase", "caseQty", "allergens", "mayContain", "diet", "certificates", "origin",
                             "qualityGrade", "carbonClass", "leadTimeDays", "onTimeRate")}
    out["listPrice"] = p["unitPrice"]
    out["priceBasis"] = p["priceBasis"]
    out["needGroup"] = need_group_id(p)
    out["digitalLink"] = digital_link(p)
    out["trustLevel"] = "L0"
    return out


def _contains(seq: list[str], sub: list[str]) -> bool:
    n = len(sub)
    return any(seq[i:i + n] == sub for i in range(len(seq) - n + 1)) if n else False


def resolve_need(text: str) -> dict:
    """Map free text ("lactose-free milk") to kind, explicit variants and hard requirements."""
    t = text.lower()
    diet, certs = [], []
    for pat, tag in DIET_PATTERNS:
        if re.search(pat, t):
            diet.append(tag)
            t = re.sub(pat, " ", t)
    for pat, label in CERT_PATTERNS:
        if re.search(pat, t):
            certs.append(label)
            t = re.sub(pat, " ", t)
    toks = tokens(t)
    kind_score: dict[str, int] = {}
    matched: dict[str, int] = {}
    for p in products():
        s = 0
        for kw in p["keywords"] + [KIND_LABELS.get(p["kind"], p["kind"])]:
            kt = tokens(kw)
            if _contains(toks, kt):
                s += len(" ".join(kt))
        if s:
            matched[p["gtin"]] = s
            kind_score[p["kind"]] = max(kind_score.get(p["kind"], 0), s)
    if not kind_score:
        return {"kind": None, "variants": [], "diet": diet, "certs": certs, "candidates": [], "text": text}
    kind = sorted(kind_score.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    variants = set()
    for p in products():
        if p["kind"] != kind:
            continue
        for v in p["variant"]:
            if v in diet or v in ("lactose_free", "gluten_free"):
                continue
            if _contains(toks, tokens(v.replace("_", " "))):
                variants.add(v)
    # drop variants whose tokens are a strict subset of another matched variant (skimmed vs semi_skimmed)
    vs = sorted(variants)
    variants = [v for v in vs if not any(v != w and set(v.split("_")) < set(w.split("_")) for w in vs)]
    cands = [g for g, _ in sorted(matched.items(), key=lambda kv: -kv[1])]
    # include every product of the resolved kind (so the buyer sees the whole need group)
    for p in products():
        if p["kind"] == kind and p["gtin"] not in matched:
            cands.append(p["gtin"])
    return {"kind": kind, "kindLabel": KIND_LABELS.get(kind, kind), "variants": sorted(variants), "diet": diet,
            "certs": certs, "candidates": cands, "text": text}


def search(query: str, category: str | None = None, diet: list[str] | None = None,
           exclude_allergens: list[str] | None = None, limit: int = 20) -> dict:
    need = resolve_need(query) if query else {"candidates": [p["gtin"] for p in products()], "kind": None}
    out = []
    for g in need["candidates"]:
        p = by_gtin(g)
        if category and p["category"] != category:
            continue
        if diet and not set(diet) <= set(p["diet"]):
            continue
        if exclude_allergens and set(exclude_allergens) & set(p["allergens"] + p["mayContain"]):
            continue
        out.append(public_product(p))
    return {"query": query, "resolved": {k: need.get(k) for k in ("kind", "variants", "diet", "certs")},
            "count": len(out[:limit]), "products": out[:limit],
            "note": "L0 catalog data is browse-only. Request signed offers (POST /v1/offers) before acting."}
