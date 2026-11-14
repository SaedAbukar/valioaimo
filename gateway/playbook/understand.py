"""Step 1 · Understand — turn a chef's sentence (EN or FI) into an Order Brief.

Deterministic, pattern-based parsing (port of the v1 page parser). Every fact is
marked found / assumed / missing so assumptions are shown, never hidden. An LLM
parser can replace `parse()` later as long as it returns the same OrderBrief
JSON Schema (gateway/playbook/order_playbook.v1.yaml).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .. import catalog
from ..util import d2s, s2d

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "maanantai": 0, "tiistai": 1, "keskiviikko": 2, "torstai": 3, "perjantai": 4, "lauantai": 5, "sunnuntai": 6}
UNIT_MAP = {"l": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L", "ltr": "L", "litraa": "L",
            "kg": "kg", "kilo": "kg", "kilos": "kg", "kilograms": "kg", "kiloa": "kg",
            "pcs": "pcs", "pieces": "pcs", "piece": "pcs", "units": "pcs", "kpl": "pcs"}
NUMW = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "twelve": 12, "yksi": 1, "kaksi": 2, "kolme": 3, "neljä": 4, "viisi": 5, "kuusi": 6,
        "seitsemän": 7, "kahdeksan": 8, "yhdeksän": 9, "kymmenen": 10}
ALLERGY_WORDS = {"nut": "nuts", "nuts": "nuts", "tree nut": "nuts", "peanut": "peanuts", "egg": "eggs", "fish": "fish",
                 "shellfish": "crustaceans", "milk": "milk", "dairy": "milk", "sesame": "sesame", "soy": "soybeans",
                 "celery": "celery", "mustard": "mustard", "gluten": "cereals_gluten", "pähkinä": "nuts",
                 "maapähkinä": "peanuts", "kala": "fish", "kananmuna": "eggs", "maito": "milk", "seesami": "sesame"}
ALLERGY_LABEL = {"nuts": "nut", "peanuts": "peanut", "eggs": "egg", "fish": "fish", "crustaceans": "shellfish",
                 "milk": "milk", "sesame": "sesame", "soybeans": "soy", "celery": "celery", "mustard": "mustard",
                 "cereals_gluten": "gluten"}
EVENT_TYPES = [
    (r"pikkujoulu|christmas party|little christmas", "christmas_party", "Christmas party", "buffet"),
    (r"gala", "gala", "Gala dinner", "plated"),
    (r"wedding|häät", "wedding", "Wedding dinner", "plated"),
    (r"conference|seminar|seminaari", "conference", "Conference", "buffet"),
    (r"birthday|syntymäpäiv", "birthday", "Birthday party", "buffet"),
    (r"breakfast|aamiainen", "breakfast", "Breakfast", "buffet"),
    (r"lunch|lounas", "lunch", "Lunch", "buffet"),
    (r"dinner|illallinen", "dinner", "Dinner", "plated"),
]
GUESTS_RE = r"(\d[\d ,]*)\s*(?:guests|people|persons|pax|covers|hengelle|henkeä|henkilölle|henkilöä|vieraalle|vierasta|hlölle|hlö)"


def next_weekday(wd: int, today: date) -> date:
    d = today + timedelta(days=1)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


def parse_date(text: str, today: date) -> tuple[str, str] | None:
    t = text.lower()
    if m := re.search(r"(\d{4}-\d{2}-\d{2})", t):
        return m.group(1), m.group(1)
    if re.search(r"\b(tomorrow|huomenna)\b", t):
        return d2s(today + timedelta(days=1)), "tomorrow"
    if re.search(r"\b(today|tänään)\b", t):
        return d2s(today), "today"
    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.?", t):
        d = date(today.year, int(m.group(2)), int(m.group(1)))
        if d < today:
            d = date(today.year + 1, d.month, d.day)
        return d2s(d), m.group(0)
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", t)
    if m:
        return d2s(date(today.year, months[m.group(2)], int(m.group(1)))), m.group(0)
    for name, wd in WEEKDAYS.items():
        if re.search(r"\b" + name + r"(?:na|ina|ta)?\b", t):
            d = next_weekday(wd, today)
            if re.search(r"(?:next|ensi) " + name, t) and (d - today).days < 6:
                d += timedelta(days=7)
            if m := re.search(r"the (\d{1,2})(?:st|nd|rd|th)", t):
                x = today
                for _ in range(60):
                    x += timedelta(days=1)
                    if x.day == int(m.group(1)):
                        d = x
                        break
            return d2s(d), name
    return None


def _num(s: str) -> int:
    return NUMW.get(s.lower()) or int(s)


def _fact(value, status: str, said: str | None = None) -> dict:
    return {"value": value, "status": status, "said": said}


def is_event(text: str) -> bool:
    return bool(re.search(GUESTS_RE, text, re.I)) or any(re.search(p, text, re.I) for p, *_ in EVENT_TYPES[:5])


def parse(text: str, today: date, site: dict, recipes: list[dict]) -> dict:
    """Return an OrderBrief (see order_playbook.v1.yaml › schemas.OrderBrief)."""
    lang = "fi" if re.search(r"[äö]|hengelle|henkilölle|vieraalle|pikkujoulu|perjantai|lauantai|ensi |huomenna", text, re.I) else "en"
    brief = parse_event(text, today, recipes) if is_event(text) else parse_items(text, today)
    brief.update({"text": text[:280], "lang": lang,
                  "site": _fact(site["name"], "found" if re.search(re.escape(site["name"].split()[0]), text, re.I) else "assumed")})
    brief["missing"] = [k for k in ("when", "howMuch", "what") if brief[k]["status"] == "missing"]
    brief["assumed"] = [k for k in ("when", "howMuch", "what", "site", "style") if k in brief and brief[k]["status"] == "assumed"]
    brief["complete"] = not brief["missing"]
    return brief


def parse_items(text: str, today: date) -> dict:
    nb = parse_date(text, today)
    diet = [tag for pat, tag in [(r"lactose[- ]?free|laktoositon", "lactose-free"), (r"(milk|dairy)[- ]?free|maidoton", "milk-free"),
                                 (r"nut[- ]?free", "nut-free"), (r"gluten[- ]?free|gluteeniton", "gluten-free")] if re.search(pat, text, re.I)]
    body = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)
    body = re.sub(r"\b(find|choose|pick)\b.*$", "", body, flags=re.I)
    lines = []
    for c in re.split(r"[,;:]|\.(?=\s|$)|\band\b|\bja\b|—|–", body):
        m = re.search(r"(\d[\d ]*(?:\.\d+)?)\s*(litres?|liters?|ltr|l|kg|kilos?|kilograms|pcs|pieces?|units|kpl|litraa|kiloa)?\b\s*(?:of\s+)?([a-zåäö][a-zåäö &\-']+)", c, re.I)
        if not m:
            continue
        qty = float(m.group(1).replace(" ", ""))
        unit = UNIT_MAP.get((m.group(2) or "").lower())
        prod = m.group(3).strip()
        if re.match(r"^(guests?|people|persons|pax|covers|hengelle|henkeä|vierasta|minutes|min|days?|weeks?|%)", prod, re.I):
            continue
        prod = re.sub(r"\b(by|for|before|on|next|this|from|at|to|mennessä|ensi)\b.*$", "", prod, flags=re.I)
        prod = re.sub(r"\b(we|i|need|please|order|tarvitaan|tarvitsen)\b", "", prod, flags=re.I).strip()
        if not prod:
            continue
        for d in diet:
            if d.replace("-", "") not in prod.lower().replace("-", "") and not re.search(r"laktoositon", prod, re.I):
                prod = f"{d} {prod}"
        need = catalog.resolve_need(prod)
        lines.append({"lineId": f"L{len(lines) + 1}", "text": prod, "qty": qty, "unit": unit or "pcs",
                      "kind": need.get("kind"), "unitStatus": "found" if unit else "assumed"})
    when = _fact(nb[0], "found", nb[1]) if nb else _fact(None, "missing")
    return {
        "context": "ad_hoc", "kind": "items",
        "what": _fact([l["text"] for l in lines] or None, "found" if lines else "missing"),
        "howMuch": _fact([{"qty": l["qty"], "unit": l["unit"]} for l in lines] or None, "found" if lines else "missing"),
        "when": when, "lines": lines,
        "constraints": {"diet": diet, "allergies": {}, "budget": None, "brands": []},
        "event": None,
    }


def parse_event(text: str, today: date, recipes: list[dict]) -> dict:
    rby = {r["id"]: r for r in recipes}
    et = next(((k, label, style) for pat, k, label, style in EVENT_TYPES if re.search(pat, text, re.I)), ("event", "Event", "buffet"))
    nb = parse_date(text, today)
    gm = re.search(GUESTS_RE, text, re.I) or re.search(r"for\s+(\d+)", text, re.I)
    guests = int(re.sub(r"[ ,]", "", gm.group(1))) if gm else None
    style_found = re.search(r"buffet|seisova|noutopöytä|plated|seated|served|pöytiin", text, re.I)
    style = ("buffet" if re.search(r"buffet|seisova|noutopöytä", style_found.group(0), re.I) else "plated") if style_found else et[2]
    diet = {"vegan": 0, "vegetarian": 0, "gluten_free": 0, "lactose_free": 0}
    for m in re.finditer(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|yksi|kaksi|kolme|neljä|viisi|kuusi|seitsemän|kahdeksan|yhdeksän|kymmenen)\s+"
                         r"(vegans?|vegaania|vegaanit|vegaani|vegetarians?|kasvissyöjää|kasvissyöjä|gluten[- ]free|gluteenitonta|gluteeniton|coeliacs?|keliaakikkoa|keliaakikko|lactose[- ]free|laktoositonta|laktoositon)", text, re.I):
        n, w = _num(m.group(1)), m.group(2).lower()
        key = "vegan" if re.search("vegan|vegaani", w) else "vegetarian" if re.search("vegetarian|kasvis", w) else \
            "gluten_free" if re.search("gluten|coeliac|keliaak|glutee", w) else "lactose_free"
        diet[key] += n
    allergies: dict[str, int] = {}
    for m in re.finditer(r"(\d+|one|a|an|two|three|four|five|yksi|kaksi|kolme|neljä|viisi)?\s*(tree nut|peanut|nut|egg|fish|shellfish|milk|dairy|sesame|soy|celery|mustard|gluten|maapähkinä|pähkinä|kala|kananmuna|maito|seesami)[- ]?(?:allerg(?:y|ies|ic)|allergia|allergikkoa|allergikko|allerginen)", text, re.I):
        a = ALLERGY_WORDS[m.group(2).lower()]
        allergies[a] = allergies.get(a, 0) + (_num(m.group(1)) if m.group(1) else 1)
    # dishes: longest recipe alias first
    dishes, used = [], set()
    rest = " " + text.lower() + " "
    for alias, r in sorted(((a, r) for r in recipes for a in r["aliases"]), key=lambda x: -len(x[0])):
        pat = r"[^a-zåäö]" + re.escape(alias).replace(r"\-", "[- ]") + r"(?:[a-zåäö]{0,3})(?=[^a-zåäö])"
        if re.search(pat, rest, re.I):
            if r["id"] not in used:
                used.add(r["id"])
                dishes.append({"recipeId": r["id"], "name": r["name"], "said": alias})
            rest = re.sub(pat, " ", rest, flags=re.I)
    order = {"starter": 0, "snack": 1, "main": 2, "side": 3, "dessert": 4, "drinks": 5, "breakfast": 6}
    dishes.sort(key=lambda d: order.get(rby[d["recipeId"]]["course"], 9))
    added = []
    if dishes and et[0] in ("gala", "wedding", "dinner") and "bread_basket" not in used and style == "plated":
        dishes.append({"recipeId": "bread_basket", "name": rby["bread_basket"]["name"], "said": None})
        added.append("bread basket")
    if dishes and et[0] in ("gala", "wedding", "dinner", "christmas_party", "conference") and "coffee_service" not in used:
        dishes.append({"recipeId": "coffee_service", "name": rby["coffee_service"]["name"], "said": None})
        added.append("coffee after the meal")
    name_m = re.match(r"\s*([A-ZÅÄÖ][^,:.\d]{2,40}?)(?=\s+(?:on|for|this|next|ensi|huomenna|\d)|[,:])", text)
    name = name_m.group(1).strip() if name_m else et[1]
    return {
        "context": "event", "kind": "event",
        "what": _fact([d["name"] for d in dishes] or None, "found" if dishes else "missing"),
        "howMuch": _fact(guests, "found" if guests else "missing"),
        "when": _fact(nb[0], "found", nb[1]) if nb else _fact(None, "missing"),
        "style": _fact(style, "found" if style_found else "assumed"),
        "lines": [],
        "constraints": {"diet": [], "allergies": allergies, "dietCounts": {k: v for k, v in diet.items() if v},
                        "budget": None, "brands": []},
        "event": {"name": name, "type": et[0], "typeLabel": et[1], "date": nb[0] if nb else None, "guests": guests,
                  "style": style, "dishes": dishes, "added": added},
    }


def apply_answer(brief: dict, field: str, value, today: date, recipes: list[dict]) -> dict:
    """Merge the answer to the one question into the brief (no re-parse of free text)."""
    if field == "when":
        brief["when"] = _fact(value, "found", "your answer")
        if brief.get("event"):
            brief["event"]["date"] = value
    elif field == "howMuch" and brief.get("event"):
        brief["howMuch"] = _fact(int(value), "found", "your answer")
        brief["event"]["guests"] = int(value)
    brief["missing"] = [k for k in ("when", "howMuch", "what") if brief[k]["status"] == "missing"]
    brief["complete"] = not brief["missing"]
    return brief


def question_for(brief: dict, today: date) -> dict | None:
    """At most ONE question, for the first critical missing fact, with tap answers."""
    if not brief["missing"]:
        return None
    k = brief["missing"][0]
    if k == "when":
        if brief["kind"] == "items":
            opts = [today + timedelta(days=1), next_weekday(0, today), next_weekday(2, today)]
        else:  # events: the next Friday/Saturday that leaves time to deliver (>= 5 days)
            fri = next_weekday(4, today + timedelta(days=4))
            opts = [fri, fri + timedelta(days=1), fri + timedelta(days=7)]
        seen, answers = set(), []
        for d in opts:
            if d not in seen:
                seen.add(d)
                answers.append({"label": f"{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday()]} {d.day}.{d.month}.", "value": d2s(d)})
        return {"field": "when", "text": "When do you need it?" if brief["kind"] == "items" else "Which day is the event?", "answers": answers[:3]}
    if k == "howMuch":
        return {"field": "howMuch", "text": "How many guests?", "answers": [{"label": str(n), "value": n} for n in (50, 100, 150)]}
    return {"field": "what", "text": "What would you like to order?", "answers": []}


def rescale(brief: dict, guests: int) -> dict:
    brief["howMuch"] = _fact(guests, "found", "your change")
    brief["event"]["guests"] = guests
    return brief


def parse_change(text: str) -> int | None:
    """'now 200 guests' / 'nyt 200 hengelle' -> 200."""
    m = re.search(GUESTS_RE, text, re.I) or re.search(r"\b(?:now|nyt|make it)\s+(\d+)", text, re.I)
    return int(re.sub(r"[ ,]", "", m.group(1))) if m else None


def is_event_new(text: str) -> bool:
    """A long message with dishes or an event word is a new request; 'now 200 guests' is a change."""
    if re.search(r"\b(now|nyt|make it|change|instead|actually|muutos|sittenkin)\b", text, re.I):
        return False
    return len(text) > 40


def due(date_s: str) -> date:
    return s2d(date_s)
