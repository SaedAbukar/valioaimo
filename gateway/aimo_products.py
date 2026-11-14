"""Real Valio Aimo product data (17.5k products) for the Discover step.

Built by scripts/build_aimo_index.py from the challenge files. Static data only:
price and availability always come from the adapter (mock API when the key is
set, fixtures otherwise). Search is deliberately simple and explainable:
token match on Finnish + English names, hard allergen / diet filters.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "aimo_products.json"

# Finnish <-> English kitchen words so a query in either language finds both names
SYNONYMS = {
    "milk": ["maito"], "maito": ["milk"], "cream": ["kerma"], "kerma": ["cream"], "whipping": ["kuohu", "vispi"],
    "salmon": ["lohi"], "lohi": ["salmon"], "beef": ["nauta", "naudan", "häränfilee"], "chicken": ["broileri", "kana"],
    "butter": ["voi"], "cheese": ["juusto"], "egg": ["muna", "kananmuna"], "eggs": ["muna"], "potato": ["peruna"],
    "potatoes": ["peruna"], "oat": ["kaura"], "drink": ["juoma"], "chocolate": ["suklaa"], "coffee": ["kahvi"],
    "lactose-free": ["laktoositon"], "lactose": ["laktoositon"], "gluten-free": ["gluteeniton"], "vegan": ["vegaani"],
    "bread": ["leipä"], "rye": ["ruis"], "dill": ["tilli"], "lemon": ["sitruuna"], "onion": ["sipuli"],
    "tenderloin": ["sisäfilee"], "fillet": ["filee"], "flour": ["jauho"], "sugar": ["sokeri"], "rice": ["riisi"],
}
# words that make a match the wrong product for a plain need ("milk" is not coconut milk or milk chocolate)
NEGATIVE = {
    "milk": (r"kookos|coconut|suklaa|chocolate|kaakao|cocoa|jauhe|powder|rahka|kahvi|coffee|annos|piltti|baby|riisi|mante|kaura|soija|herne|jug|kannu|kerma|cream"),
    "maito": (r"kookos|suklaa|kaakao|jauhe|rahka|kahvi|annos|kaura|soija"),
    "cream": (r"ice|jää|sauce|kastike|cheese|juusto|candy|karamel|soup|keitto|perunat|powder|jauhe|spray"),
    "drink": (r"kaakao|cocoa|energy"),
}
NON_FOOD_PREFIX = ("63", "64", "65", "66")  # cleaning, disposables, equipment (category codes)
DIET_WORDS = {"lactose_free": ("laktoositon", "lactose free", "lactose-free"),
              "gluten_free": ("gluteeniton", "gluten free", "gluten-free"),
              "vegan": ("vegaani", "vegan")}


@lru_cache(maxsize=1)
def _load() -> dict:
    if not DATA.exists():
        return {"products": [], "byId": {}}
    d = json.loads(DATA.read_text())
    d["byId"] = {p["id"]: p for p in d["products"]}
    for p in d["products"]:
        p["_t"] = f" {p.get('fi', '')} {p.get('en', '')} ".lower()
    return d


def available() -> bool:
    return bool(_load()["products"])


def by_id(pid: str) -> dict | None:
    return _load()["byId"].get(str(pid))


def count() -> int:
    return len(_load()["products"])


def _tokens(q: str) -> list[str]:
    return [t for t in re.findall(r"[a-zåäö0-9-]+", q.lower()) if len(t) > 1]


def diet_of(p: dict) -> set[str]:
    out = set(p.get("diet", []))
    t = p.get("_t") or f" {p.get('fi', '')} {p.get('en', '')} ".lower()
    for tag, words in DIET_WORDS.items():
        if any(w in t for w in words):
            out.add(tag)
    if "milk" not in p.get("contains", []) and "milk" not in p.get("may", []):
        out.add("milk_free")
    if "vegan" in out:
        out.add("vegetarian")
    if "nuts" not in p.get("contains", []) + p.get("may", []) and "peanuts" not in p.get("contains", []) + p.get("may", []):
        out.add("nut_free")
    return out


def public(p: dict, lang: str = "en") -> dict:
    return {
        "productId": p["id"], "name": p.get(lang) or p.get("en") or p.get("fi"), "nameFi": p.get("fi"),
        "brand": p.get("brand"), "vendor": p.get("vendor"), "salesUnit": p.get("unit"), "category": p.get("cat"),
        "contains": p.get("contains", []), "mayContain": p.get("may", []), "diet": sorted(diet_of(p)),
        "kgPerSalesUnit": p.get("kg"), "co2eKgPerKg": p.get("co2"), "deliveryReliability": p.get("rel"), "labels": p.get("labels", []),
        "substitutes": p.get("subs", []), "gtin": p.get("gtin"),
    }


def search(query: str, exclude_allergens: list[str] | None = None, diet: list[str] | None = None,
           limit: int = 10, lang: str = "en") -> dict:
    """Token search over fi+en names. Returns matches plus the ones removed by hard filters (with reason)."""
    toks = _tokens(query)
    if not toks:
        return {"query": query, "count": 0, "products": [], "excluded": []}
    groups = [[t] + SYNONYMS.get(t, []) for t in toks]
    excl = set(exclude_allergens or [])
    need = set(diet or [])
    scored, removed = [], []
    for p in _load()["products"]:
        if str(p.get("cat", "")).startswith(NON_FOOD_PREFIX):
            continue
        t = p["_t"]
        hits = sum(1 for g in groups if any(w in t for w in g))
        if hits == 0:
            continue
        score = hits / len(groups)
        if hits == len(groups):
            score += 0.5
        # prefer the head noun appearing early and shorter names (less "composite" products)
        first = min((t.find(w) for w in groups[-1] if w in t), default=99)
        score += max(0, 0.2 - first / 400) + max(0, 0.1 - len(t) / 1200)
        en = f" {p.get('en', '').lower()} "
        if all(re.search(r"\b" + re.escape(g[0]) + r"\b", en) for g in groups):
            score += 0.3  # every word appears as a whole word in the English name
        if NEGATIVE.get(toks[-1]) and re.search(NEGATIVE[toks[-1]], t):
            score -= 0.8
        if p.get("rel") is not None:
            score += 0.05 * p["rel"]
        scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    out = []
    for score, p in scored:
        if score < 1.0:  # require every query concept
            break
        bad = sorted((set(p.get("contains", [])) | set(p.get("may", []))) & excl)
        miss = sorted(need - diet_of(p))
        if bad or miss:
            if len(removed) < 10:
                why = []
                if bad:
                    why.append(("contains " if set(bad) & set(p.get("contains", [])) else "may contain ") + ", ".join(bad))
                if miss:
                    why.append("not " + ", ".join(m.replace("_", "-") for m in miss))
                removed.append({"productId": p["id"], "name": p.get(lang) or p.get("en"), "reason": "; ".join(why)})
            continue
        item = public(p, lang)
        item["match"] = round(score, 3)
        out.append(item)
        if len(out) >= limit:
            break
    return {"query": query, "count": len(out), "products": out, "excluded": removed}
