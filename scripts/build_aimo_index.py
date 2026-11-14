"""Build the slim, searchable Valio Aimo product index used by the Discover step.

    python scripts/build_aimo_index.py [data_raw/product_data.json]

Reads the challenge files (product data JSON, carbon footprint CSV, delivery
reliability CSV) from data_raw/ and writes gateway/data/aimo_products.json:
one compact record per product with names (fi/en/sv), unit info, allergens
(contains / may contain), diet claims, net content per sales unit, CO2e per kg,
delivery reliability and substitutions. The raw files are not committed.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data_raw"
OUT = ROOT / "gateway" / "data" / "aimo_products.json"

# GS1 allergen type codes -> EU-14 keys used across the gateway
ALLERGEN = {
    "AC": "crustaceans", "AE": "eggs", "AF": "fish", "AM": "milk", "AN": "nuts", "AP": "peanuts", "AS": "sesame",
    "AU": "sulphites", "AW": "cereals_gluten", "AY": "soybeans", "BC": "celery", "BM": "mustard", "NL": "lupin",
    "UM": "molluscs", "UW": "cereals_gluten", "GB": "cereals_gluten", "GO": "cereals_gluten", "NR": "cereals_gluten",
    "GS": "cereals_gluten", "GK": "cereals_gluten",
    # individual tree nuts
    "SA": "nuts", "SC": "nuts", "SH": "nuts", "SM": "nuts", "SP": "nuts", "SR": "nuts", "ST": "nuts", "SW": "nuts",
    "SQ": "nuts",
}
CLAIMS = {"FREE_FROM_LACTOSE": "lactose_free", "FREE_FROM_GLUTEN": "gluten_free", "VEGAN": "vegan",
          "VEGETARIAN": "vegetarian", "FREE_FROM_MILK": "milk_free"}


def _kg(w: dict | None) -> float | None:
    if not w:
        return None
    v = w.get("value")
    if v is None:
        return None
    return v / 1000 if w.get("unit") == "GRM" else v if w.get("unit") == "KGM" else None


def _l(v: dict | None) -> float | None:
    if not v:
        return None
    x = v.get("value")
    if x is None:
        return None
    return x / 1000 if v.get("unit") == "MLT" else x if v.get("unit") == "LTR" else None


def slim(p: dict, co2: dict, rel: dict) -> dict:
    s = p.get("synkkaData") or {}
    names = {n["language"]: n["value"].strip() for n in s.get("names", [])}
    contains, may = set(), set()
    diet = set()
    for g in s.get("classifications", []):
        if g["name"] == "allergen":
            for v in g["values"]:
                k = ALLERGEN.get(v["id"])
                if not k:
                    continue
                if v.get("unit") == "CONTAINS":
                    contains.add(k)
                elif v.get("unit") == "MAY_CONTAIN":
                    may.add(k)
        if g["name"] == "nutritionalClaim":
            for v in g["values"]:
                if v["id"] in CLAIMS:
                    diet.add(CLAIMS[v["id"]])
                if v.get("unit") == "DIET" and v.get("synkkaId") in CLAIMS:
                    diet.add(CLAIMS[v["synkkaId"]])
    may -= contains
    base = next((u for u in s.get("unitConversions", []) if u.get("synkkaPackagingType") == "BASE_UNIT_OR_EACH"), None)
    base_kg = _kg((base or {}).get("netWeight"))
    base_l = _l((base or {}).get("volume"))
    sizes = {u["unitId"]: u.get("sizeInBaseUnits", 1) for u in p.get("units", [])}
    per_sales = sizes.get(p["salesUnit"], 1) / (sizes.get(p["baseUnit"], 1) or 1)
    rec = {
        "id": p["id"],
        "fi": names.get("fi", ""), "en": names.get("en") or names.get("fi", ""), "sv": names.get("sv", ""),
        "brand": s.get("brand") or "", "vendor": p.get("vendorName", ""),
        "cat": p.get("category"), "temp": p.get("temperatureCondition"),
        "unit": p["salesUnit"], "baseUnit": p["baseUnit"], "perSales": round(per_sales, 4), "lot": p.get("allowedLotSize"),
        "gtin": p.get("salesUnitGtin") or s.get("gtin"),
        "contains": sorted(contains), "may": sorted(may), "diet": sorted(diet),
        "kg": round(base_kg * per_sales, 4) if base_kg else None,
        "l": round(base_l * per_sales, 4) if base_l and p["baseUnit"] in ("BOT", "ST", "CS", "PAK", "KI", "PRK") else None,
        "origin": p.get("countryOfOrigin"), "vat": s.get("vatCode"), "varW": bool(s.get("variableUnit")),
        "co2": co2.get(p["id"]), "rel": rel.get(p["id"]),
        "subs": [x["substituteProduct"] for x in p.get("substitutions", []) if x.get("product") == p["id"]],
    }
    return {k: v for k, v in rec.items() if v not in (None, "", [], False)}


def main(path: str | None = None):
    src = Path(path) if path else RAW / "product_data.json"
    data = json.loads(src.read_text())
    co2 = {r["productId"]: round(float(r["AVG kg CO2-eq/kg"]), 3) for r in csv.DictReader((RAW / "carbon_footprint.csv").open())}
    rel = {r["productId"]: round(float(r["deliveryReliability"]), 3) for r in csv.DictReader((RAW / "delivery_reliability.csv").open())}
    out = [slim(p, co2, rel) for p in data if not p.get("deleted")]
    OUT.write_text(json.dumps({"source": "Valio Aimo Junction 2026 product data (challenge use only)",
                               "count": len(out), "products": out}, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, {len(out)} products; co2 {len(co2)}, reliability {len(rel)})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
