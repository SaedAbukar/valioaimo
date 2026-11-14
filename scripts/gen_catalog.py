"""Generate the synthetic Valio Aimo foodservice catalog fixture.

All brands, suppliers and GTIN company prefixes are FICTIONAL. Only the
wholesaler name "Valio Aimo" and public certification labels are real.
Run:  python scripts/gen_catalog.py   (writes gateway/data/catalog.json)
"""
import json
from pathlib import Path

ALLERGENS = ["cereals_gluten", "crustaceans", "eggs", "fish", "peanuts", "soybeans", "milk",
             "nuts", "celery", "mustard", "sesame", "sulphites", "lupin", "molluscs"]

CERT = {
    "organic": {"label": "EU Organic", "issuer": "Ruokavirasto FI-EKO-201", "validUntil": "2027-06-30"},
    "hs": {"label": "Hyvää Suomesta", "issuer": "Ruokatieto Yhdistys ry", "validUntil": "2027-12-31"},
    "msc": {"label": "MSC", "issuer": "Marine Stewardship Council", "validUntil": "2027-03-31"},
    "asc": {"label": "ASC", "issuer": "Aquaculture Stewardship Council", "validUntil": "2027-02-28"},
    "fairtrade": {"label": "Fairtrade", "issuer": "Fairtrade International", "validUntil": "2027-09-30"},
    "ra": {"label": "Rainforest Alliance", "issuer": "Rainforest Alliance", "validUntil": "2027-05-31"},
    "glutenfree": {"label": "Crossed Grain", "issuer": "AOECS", "validUntil": "2027-01-31"},
    "msc_expired": {"label": "MSC", "issuer": "Marine Stewardship Council", "validUntil": "2026-10-31"},
}

# key, name, brand, category, kind, variant, unit, packSize, unitsPerCase, unitPrice,
# allergens, mayContain, explicit diet, certs, country, supplier, lead, onTime, stock, inbound[(days, qty)], keywords
P = [
    # ---------------- DAIRY ----------------
    ("milk_lf_semi_kaarna", "Lactose-free semi-skimmed milk drink 1.5% 1 L", "Kaarna Meijeri", "dairy", "milk", ["lactose_free", "semi_skimmed"], "L", 1.0, 10, 1.29, ["milk"], [], ["lactose_free", "vegetarian"], ["hs"], "FI", "SUP-011", 1, 0.97, 640, [(5, 800)], ["milk", "maito", "laktoositon"]),
    ("milk_lf_semi_maitokaari", "Lactose-free semi-skimmed milk 1.5% 1.5 L", "Maitokaari", "dairy", "milk", ["lactose_free", "semi_skimmed"], "L", 1.5, 6, 1.33, ["milk"], [], ["lactose_free", "vegetarian"], ["hs"], "FI", "SUP-019", 1, 0.95, 800, [], ["milk", "maito", "laktoositon"]),
    ("milk_lf_whole_tunturi", "Lactose-free whole milk 3.5% 1 L", "Tunturi Dairy", "dairy", "milk", ["lactose_free", "whole"], "L", 1.0, 10, 1.41, ["milk"], [], ["lactose_free", "vegetarian"], [], "FI", "SUP-023", 1, 0.96, 1200, [], ["milk", "maito", "laktoositon"]),
    ("milk_semi_laaksola", "Semi-skimmed milk 1.5% 1 L", "Laaksola", "dairy", "milk", ["semi_skimmed"], "L", 1.0, 12, 0.99, ["milk"], [], ["vegetarian"], [], "FI", "SUP-031", 1, 0.98, 2000, [], ["milk", "maito"]),
    ("milk_skim_kaarna", "Skimmed milk 0% 1 L", "Kaarna Meijeri", "dairy", "milk", ["skimmed"], "L", 1.0, 10, 0.95, ["milk"], [], ["vegetarian"], ["hs"], "FI", "SUP-011", 1, 0.97, 900, [], ["milk", "maito", "rasvaton"]),
    ("milk_organic_kaarna", "Organic semi-skimmed milk 1.5% 1 L", "Kaarna Meijeri", "dairy", "milk", ["semi_skimmed", "organic"], "L", 1.0, 10, 1.49, ["milk"], [], ["vegetarian"], ["organic", "hs"], "FI", "SUP-011", 2, 0.94, 300, [], ["milk", "luomu"]),
    ("cream_whip_kaarna", "Whipping cream 35% 1 L", "Kaarna Meijeri", "dairy", "cream", ["whipping"], "L", 1.0, 12, 4.20, ["milk"], [], ["vegetarian"], ["hs"], "FI", "SUP-011", 1, 0.97, 400, [], ["cream", "kerma", "whipping"]),
    ("cream_whip_lf_maitokaari", "Lactose-free whipping cream 35% 1 L", "Maitokaari", "dairy", "cream", ["whipping", "lactose_free"], "L", 1.0, 12, 4.55, ["milk"], [], ["lactose_free", "vegetarian"], [], "FI", "SUP-019", 1, 0.95, 240, [], ["cream", "kerma", "whipping"]),
    ("cream_cook_lf_kaarna", "Lactose-free cooking cream 15% 1 L", "Kaarna Meijeri", "dairy", "cream", ["cooking", "lactose_free"], "L", 1.0, 12, 3.10, ["milk"], [], ["lactose_free", "vegetarian"], ["hs"], "FI", "SUP-011", 1, 0.97, 360, [], ["cream", "ruokakerma", "cooking"]),
    ("butter_kaarna", "Butter 82% unsalted 500 g", "Kaarna Meijeri", "dairy", "butter", ["unsalted"], "kg", 0.5, 20, 9.80, ["milk"], [], ["vegetarian", "lactose_free"], ["hs"], "FI", "SUP-011", 1, 0.97, 300, [], ["butter", "voi"]),
    ("cheese_emmental_tunturi", "Emmental cheese block approx. 3 kg", "Tunturi Dairy", "dairy", "cheese", ["emmental", "block"], "kg", 3.0, 2, 12.40, ["milk"], [], ["lactose_free", "vegetarian"], [], "FI", "SUP-023", 1, 0.96, 120, [], ["cheese", "juusto", "emmental"]),
    ("cheese_edam_slices_laaksola", "Edam cheese slices 1 kg", "Laaksola", "dairy", "cheese", ["edam", "sliced"], "kg", 1.0, 6, 10.90, ["milk"], [], ["vegetarian"], [], "FI", "SUP-031", 1, 0.98, 180, [], ["cheese", "juusto", "edam"]),
    ("cheese_feta_style", "White brine cheese cubes 2 kg", "Laaksola", "dairy", "cheese", ["brine"], "kg", 2.0, 4, 11.50, ["milk"], [], ["vegetarian"], [], "GR", "SUP-044", 2, 0.92, 96, [], ["cheese", "feta"]),
    ("yogurt_natural_kaarna", "Natural yogurt 2.5% 10 kg bucket", "Kaarna Meijeri", "dairy", "yogurt", ["natural"], "kg", 10.0, 1, 2.35, ["milk"], [], ["vegetarian"], ["hs"], "FI", "SUP-011", 1, 0.97, 400, [], ["yogurt", "jogurtti"]),
    ("yogurt_lf_greek_maitokaari", "Lactose-free Greek-style yogurt 10% 5 kg", "Maitokaari", "dairy", "yogurt", ["greek", "lactose_free"], "kg", 5.0, 1, 4.20, ["milk"], [], ["lactose_free", "vegetarian"], [], "FI", "SUP-019", 1, 0.95, 150, [], ["yogurt", "jogurtti", "greek"]),
    ("quark_kaarna", "Plain quark 5 kg", "Kaarna Meijeri", "dairy", "quark", ["plain"], "kg", 5.0, 1, 3.40, ["milk"], [], ["vegetarian"], ["hs"], "FI", "SUP-011", 1, 0.97, 200, [], ["quark", "rahka"]),
    ("sour_cream_laaksola", "Smetana sour cream 20% 1 kg", "Laaksola", "dairy", "sour_cream", ["smetana"], "kg", 1.0, 6, 4.60, ["milk"], [], ["vegetarian"], [], "FI", "SUP-031", 1, 0.98, 90, [], ["smetana", "sour cream"]),
    ("eggs_free_range", "Free-range eggs M, 30-egg tray", "Kanala Peltola", "dairy", "eggs", ["free_range"], "pcs", 30, 6, 0.24, ["eggs"], [], ["vegetarian", "milk_free"], ["hs"], "FI", "SUP-052", 1, 0.96, 5400, [], ["eggs", "kananmuna", "egg"]),
    ("eggs_liquid", "Pasteurised liquid whole egg 1 L", "Kanala Peltola", "dairy", "eggs", ["liquid"], "L", 1.0, 10, 4.90, ["eggs"], [], ["vegetarian"], [], "FI", "SUP-052", 1, 0.96, 200, [], ["egg", "liquid egg"]),
    # ---------------- PLANT-BASED ----------------
    ("oat_drink_kauraco", "Oat drink, enriched 1 L", "Kaura&Co", "plant_based", "plant_drink", ["oat"], "L", 1.0, 10, 1.49, ["cereals_gluten"], [], ["vegan", "milk_free"], ["hs"], "FI", "SUP-061", 1, 0.96, 0, [(6, 600)], ["oat drink", "oat", "kaurajuoma", "milk alternative", "plant drink"]),
    ("oat_drink_aamukaura", "Barista oat drink 1 L", "Aamukaura", "plant_based", "plant_drink", ["oat", "barista"], "L", 1.0, 12, 1.60, ["cereals_gluten"], ["nuts"], ["vegan", "milk_free"], [], "SE", "SUP-066", 2, 0.93, 900, [], ["oat drink", "oat", "barista", "milk alternative", "plant drink", "milk"]),
    ("almond_drink_pahkinapuu", "Almond drink, unsweetened 1 L", "Pähkinäpuu", "plant_based", "plant_drink", ["almond"], "L", 1.0, 12, 1.79, ["nuts"], [], ["vegan", "milk_free"], [], "ES", "SUP-070", 2, 0.92, 500, [], ["almond drink", "milk alternative", "plant drink"]),
    ("hazelnut_drink_pahkinapuu", "Hazelnut drink 1 L", "Pähkinäpuu", "plant_based", "plant_drink", ["hazelnut"], "L", 1.0, 12, 1.85, ["nuts"], [], ["vegan", "milk_free"], [], "IT", "SUP-070", 2, 0.92, 300, [], ["hazelnut drink", "milk alternative", "plant drink"]),
    ("soy_drink_soijanord", "Soy drink, calcium-enriched 1 L", "Soija Nord", "plant_based", "plant_drink", ["soy"], "L", 1.0, 12, 1.55, ["soybeans"], [], ["vegan", "milk_free"], ["organic"], "SE", "SUP-073", 1, 0.95, 600, [], ["soy drink", "soy", "milk alternative", "plant drink"]),
    ("pea_drink_hernelabs", "Pea protein drink 1 L", "Herne Labs", "plant_based", "plant_drink", ["pea"], "L", 1.0, 12, 1.95, [], [], ["vegan", "milk_free"], [], "FI", "SUP-075", 3, 0.88, 120, [], ["pea drink", "milk alternative", "plant drink"]),
    ("oat_cooking_base", "Oat cooking base 15% 1 L", "Kaura&Co", "plant_based", "plant_cream", ["oat"], "L", 1.0, 12, 2.90, ["cereals_gluten"], [], ["vegan", "milk_free"], ["hs"], "FI", "SUP-061", 1, 0.96, 300, [], ["oat cream", "cooking base", "cream alternative"]),
    ("oat_yogurt_kauraco", "Oat-based yogurt alternative, plain 5 kg", "Kaura&Co", "plant_based", "plant_yogurt", ["oat"], "kg", 5.0, 1, 3.90, ["cereals_gluten"], [], ["vegan", "milk_free"], [], "FI", "SUP-061", 1, 0.96, 80, [], ["oat yogurt", "yogurt alternative"]),
    ("tofu_soijanord", "Organic firm tofu 1 kg", "Soija Nord", "plant_based", "tofu", ["firm"], "kg", 1.0, 6, 6.40, ["soybeans"], [], ["vegan", "milk_free"], ["organic"], "SE", "SUP-073", 2, 0.94, 140, [], ["tofu"]),
    ("plant_mince_hernelabs", "Pea-based plant mince 2 kg", "Herne Labs", "plant_based", "plant_protein", ["mince", "pea"], "kg", 2.0, 4, 8.90, [], [], ["vegan", "milk_free"], ["hs"], "FI", "SUP-075", 2, 0.90, 160, [], ["plant mince", "vegan mince", "minced"]),
    ("falafel_frozen", "Falafel balls, frozen 1 kg", "Herne Labs", "plant_based", "plant_protein", ["falafel"], "kg", 1.0, 6, 7.20, ["sesame"], [], ["vegan", "milk_free"], [], "FI", "SUP-075", 2, 0.90, 200, [], ["falafel"]),
    ("vegan_spread", "Plant-based spread 60% 400 g", "Kaura&Co", "plant_based", "spread", ["vegan"], "kg", 0.4, 20, 7.50, [], [], ["vegan", "milk_free"], [], "FI", "SUP-061", 1, 0.96, 160, [], ["spread", "margarine", "levite"]),
    # ---------------- DRY GOODS ----------------
    ("pasta_penne_aitta", "Durum wheat penne 5 kg", "Aitta", "dry_goods", "pasta", ["penne"], "kg", 5.0, 2, 2.10, ["cereals_gluten"], ["eggs"], ["vegan"], [], "IT", "SUP-080", 2, 0.97, 800, [], ["pasta", "penne"]),
    ("pasta_gf_aitta", "Gluten-free corn-rice penne 2 kg", "Aitta", "dry_goods", "pasta", ["penne", "gluten_free"], "kg", 2.0, 4, 5.60, [], [], ["vegan", "gluten_free"], ["glutenfree"], "IT", "SUP-080", 2, 0.95, 160, [], ["pasta", "gluten-free pasta"]),
    ("rice_jasmine", "Jasmine rice 10 kg", "Aitta", "dry_goods", "rice", ["jasmine"], "kg", 10.0, 1, 2.40, [], [], ["vegan", "gluten_free"], [], "TH", "SUP-081", 2, 0.96, 900, [], ["rice", "riisi"]),
    ("rice_risotto", "Arborio risotto rice 5 kg", "Aitta", "dry_goods", "rice", ["arborio"], "kg", 5.0, 2, 3.60, [], [], ["vegan", "gluten_free"], [], "IT", "SUP-081", 2, 0.96, 300, [], ["rice", "risotto"]),
    ("oat_flakes_peltola", "Rolled oat flakes 5 kg", "Peltola Farms", "dry_goods", "cereal", ["oat"], "kg", 5.0, 2, 1.90, ["cereals_gluten"], [], ["vegan"], ["hs"], "FI", "SUP-085", 1, 0.98, 700, [], ["oats", "kaurahiutale", "porridge"]),
    ("oat_flakes_gf_peltola", "Gluten-free oat flakes 3 kg", "Peltola Farms", "dry_goods", "cereal", ["oat", "gluten_free"], "kg", 3.0, 2, 3.80, [], [], ["vegan", "gluten_free"], ["hs", "glutenfree"], "FI", "SUP-085", 1, 0.98, 240, [], ["oats", "gluten-free oats", "porridge"]),
    ("flour_wheat", "Wheat flour, all-purpose 10 kg", "Peltola Farms", "dry_goods", "flour", ["wheat"], "kg", 10.0, 1, 0.98, ["cereals_gluten"], [], ["vegan"], ["hs"], "FI", "SUP-085", 1, 0.98, 1200, [], ["flour", "vehnäjauho"]),
    ("oil_rapeseed", "Cold-pressed rapeseed oil 5 L", "Peltola Farms", "dry_goods", "oil", ["rapeseed"], "L", 5.0, 2, 3.20, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.98, 600, [], ["oil", "rypsiöljy", "rapeseed"]),
    ("sugar", "Granulated sugar 25 kg", "Aitta", "dry_goods", "sugar", ["granulated"], "kg", 25.0, 1, 1.15, [], [], ["vegan", "gluten_free"], [], "FI", "SUP-080", 1, 0.98, 1000, [], ["sugar", "sokeri"]),
    ("coffee_dark", "Dark roast ground coffee 1 kg", "Kahvila Kaarna", "dry_goods", "coffee", ["dark_roast"], "kg", 1.0, 6, 14.90, [], [], ["vegan", "gluten_free"], ["fairtrade", "organic"], "FI", "SUP-090", 2, 0.97, 300, [], ["coffee", "kahvi"]),
    ("coffee_medium", "Medium roast whole beans 1 kg", "Kahvila Kaarna", "dry_goods", "coffee", ["medium_roast"], "kg", 1.0, 6, 13.40, [], [], ["vegan", "gluten_free"], ["ra"], "FI", "SUP-090", 2, 0.97, 400, [], ["coffee", "kahvi", "beans"]),
    ("tea_black", "Black tea, 100 bags", "Teehetki", "dry_goods", "tea", ["black"], "pcs", 100, 10, 0.045, [], [], ["vegan", "gluten_free"], ["ra"], "LK", "SUP-091", 2, 0.95, 20000, [], ["tea", "tee"]),
    ("tomatoes_crushed", "Crushed tomatoes 2.5 kg can", "Aitta", "dry_goods", "canned", ["tomato"], "kg", 2.5, 6, 1.70, [], [], ["vegan", "gluten_free"], [], "IT", "SUP-080", 2, 0.97, 600, [], ["tomatoes", "crushed tomatoes", "tomaattimurska"]),
    ("chickpeas", "Chickpeas in brine 2.5 kg", "Aitta", "dry_goods", "canned", ["chickpea"], "kg", 2.5, 6, 2.30, [], [], ["vegan", "gluten_free"], [], "ES", "SUP-080", 2, 0.97, 300, [], ["chickpeas", "kikherne"]),
    ("lentils_red", "Red lentils 5 kg", "Aitta", "dry_goods", "pulses", ["lentil"], "kg", 5.0, 2, 2.90, [], [], ["vegan", "gluten_free"], [], "CA", "SUP-080", 2, 0.97, 300, [], ["lentils", "linssi"]),
    ("peanut_butter", "Peanut butter, smooth 3 kg", "Aitta", "dry_goods", "nut_butter", ["peanut"], "kg", 3.0, 2, 6.90, ["peanuts"], [], ["vegan"], [], "US", "SUP-080", 3, 0.93, 60, [], ["peanut butter"]),
    ("mustard_dijon", "Dijon mustard 1 kg", "Sinappila", "dry_goods", "condiment", ["mustard"], "kg", 1.0, 6, 5.40, ["mustard"], [], ["vegan"], [], "FR", "SUP-093", 2, 0.95, 120, [], ["mustard", "sinappi"]),
    ("soy_sauce", "Soy sauce 1.8 L", "Aitta", "dry_goods", "condiment", ["soy"], "L", 1.8, 6, 3.80, ["soybeans", "cereals_gluten"], [], ["vegan"], [], "JP", "SUP-080", 2, 0.95, 120, [], ["soy sauce"]),
    ("sesame_seeds", "Hulled sesame seeds 1 kg", "Aitta", "dry_goods", "seeds", ["sesame"], "kg", 1.0, 6, 6.20, ["sesame"], [], ["vegan", "gluten_free"], [], "IN", "SUP-080", 2, 0.95, 60, [], ["sesame"]),
    ("salt_sea", "Sea salt, fine 5 kg", "Aitta", "dry_goods", "salt", ["fine"], "kg", 5.0, 2, 1.20, [], [], ["vegan", "gluten_free"], [], "FR", "SUP-080", 1, 0.98, 400, [], ["salt", "suola"]),
    ("dried_cranberries", "Dried cranberries 1 kg", "Mansikkala", "dry_goods", "dried_fruit", ["cranberry"], "kg", 1.0, 6, 8.20, ["sulphites"], [], ["vegan", "gluten_free"], [], "US", "SUP-095", 2, 0.94, 80, [], ["cranberries", "dried fruit"]),
    # ---------------- PRODUCE ----------------
    ("potatoes_new", "Potatoes, firm (yellow) 10 kg sack", "Peltola Farms", "produce", "potato", ["firm"], "kg", 10.0, 1, 1.45, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.96, 1500, [], ["potatoes", "potato", "peruna"]),
    ("potatoes_peeled", "Peeled potatoes, vacuum 5 kg", "Peltola Farms", "produce", "potato", ["peeled"], "kg", 5.0, 2, 2.10, ["sulphites"], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.95, 400, [], ["potatoes", "peeled potatoes"]),
    ("carrots", "Carrots 10 kg", "Peltola Farms", "produce", "root_veg", ["carrot"], "kg", 10.0, 1, 1.10, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.96, 800, [], ["carrots", "porkkana"]),
    ("onions_yellow", "Yellow onions 10 kg", "Peltola Farms", "produce", "onion", ["yellow"], "kg", 10.0, 1, 1.05, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.96, 700, [], ["onions", "sipuli"]),
    ("tomatoes_fresh", "Tomatoes, greenhouse 6 kg", "Lasitarha Närpiö", "produce", "tomato", ["greenhouse"], "kg", 6.0, 1, 3.40, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-087", 1, 0.95, 300, [], ["tomatoes", "tomaatti"]),
    ("cucumber", "Cucumbers, greenhouse 5 kg", "Lasitarha Närpiö", "produce", "cucumber", ["greenhouse"], "kg", 5.0, 1, 2.90, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-087", 1, 0.95, 250, [], ["cucumber", "kurkku"]),
    ("lettuce_iceberg", "Iceberg lettuce, 10 heads", "Lasitarha Närpiö", "produce", "salad", ["iceberg"], "pcs", 10, 1, 1.30, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-087", 1, 0.94, 400, [], ["lettuce", "salad", "jäävuorisalaatti"]),
    ("celery", "Celery stalks 5 kg", "Peltola Farms", "produce", "celery", ["stalk"], "kg", 5.0, 1, 2.60, ["celery"], [], ["vegan", "gluten_free"], [], "ES", "SUP-088", 2, 0.92, 100, [], ["celery", "selleri"]),
    ("mushrooms", "Champignons 3 kg", "Sienitila Kuusi", "produce", "mushroom", ["champignon"], "kg", 3.0, 1, 4.90, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-089", 1, 0.93, 150, [], ["mushrooms", "herkkusieni"]),
    ("apples", "Apples, Finnish 8 kg", "Hedelmätarha Ahvenanmaa", "produce", "fruit", ["apple"], "kg", 8.0, 1, 2.40, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-086", 1, 0.95, 400, [], ["apples", "omena"]),
    ("bananas", "Bananas 18 kg", "Tropiikki Trade", "produce", "fruit", ["banana"], "kg", 18.0, 1, 1.65, [], [], ["vegan", "gluten_free"], ["fairtrade"], "CO", "SUP-096", 2, 0.94, 900, [], ["bananas", "banaani"]),
    ("lemons", "Lemons 5 kg", "Tropiikki Trade", "produce", "fruit", ["lemon"], "kg", 5.0, 1, 2.90, [], [], ["vegan", "gluten_free"], [], "ES", "SUP-096", 2, 0.94, 200, [], ["lemons", "sitruuna"]),
    ("strawberries_frozen", "Strawberries, frozen 2.5 kg", "Mansikkala", "produce", "berries", ["strawberry", "frozen"], "kg", 2.5, 4, 9.90, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-095", 1, 0.96, 300, [], ["strawberries", "mansikka", "berries"]),
    ("lingonberries_frozen", "Lingonberries, frozen 2 kg", "Mansikkala", "produce", "berries", ["lingonberry", "frozen"], "kg", 2.0, 5, 6.80, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-095", 1, 0.96, 200, [], ["lingonberries", "puolukka", "berries"]),
    ("blueberries_frozen", "Wild blueberries, frozen 2 kg", "Mansikkala", "produce", "berries", ["blueberry", "frozen"], "kg", 2.0, 5, 8.40, [], [], ["vegan", "gluten_free"], ["hs", "organic"], "FI", "SUP-095", 1, 0.96, 220, [], ["blueberries", "mustikka", "berries"]),
    # ---------------- MEAT ----------------
    ("beef_tenderloin", "Beef tenderloin, trimmed, approx. 2.5 kg", "Pohjan Liha", "meat", "beef", ["tenderloin"], "kg", 2.5, 2, 44.50, [], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-101", 1, 0.95, 60, [], ["beef", "tenderloin", "naudan sisäfile"]),
    ("beef_mince", "Minced beef 10% 2 kg", "Pohjan Liha", "meat", "beef", ["mince"], "kg", 2.0, 5, 9.20, [], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-101", 1, 0.96, 400, [], ["beef", "mince", "jauheliha", "minced"]),
    ("chicken_breast", "Chicken breast fillet 2.5 kg", "Kanatila Laine", "meat", "chicken", ["breast"], "kg", 2.5, 4, 11.40, [], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-104", 1, 0.96, 500, [], ["chicken", "broileri", "breast"]),
    ("pork_tenderloin", "Pork tenderloin 2 kg", "Pohjan Liha", "meat", "pork", ["tenderloin"], "kg", 2.0, 4, 12.90, [], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-101", 1, 0.96, 200, [], ["pork", "porsaan sisäfile"]),
    ("ham_sliced", "Smoked ham slices 1 kg", "Pohjan Liha", "meat", "cold_cuts", ["ham"], "kg", 1.0, 6, 13.80, [], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-101", 1, 0.96, 150, [], ["ham", "kinkku"]),
    ("reindeer_saute", "Reindeer sauté, frozen 1 kg", "Lapin Riista", "meat", "game", ["reindeer"], "kg", 1.0, 6, 39.00, [], [], ["gluten_free", "milk_free"], [], "FI", "SUP-108", 3, 0.90, 40, [], ["reindeer", "poronkäristys"]),
    ("sausage_grill", "Grill sausages 1 kg", "Pohjan Liha", "meat", "sausage", ["grill"], "kg", 1.0, 8, 7.40, ["mustard"], ["milk"], [], ["hs"], "FI", "SUP-101", 1, 0.96, 300, [], ["sausage", "makkara"]),
    ("bacon", "Bacon slices 1 kg", "Pohjan Liha", "meat", "pork", ["bacon"], "kg", 1.0, 6, 10.50, [], [], ["gluten_free", "milk_free"], [], "DK", "SUP-102", 2, 0.94, 200, [], ["bacon", "pekoni"]),
    # ---------------- FISH ----------------
    ("salmon_fillet", "Salmon fillet, skin-on, fresh 5 kg box", "Saaristo Fish", "fish", "salmon", ["fillet", "fresh"], "kg", 5.0, 1, 24.90, ["fish"], [], ["gluten_free", "milk_free"], ["asc"], "NO", "SUP-111", 1, 0.94, 120, [], ["salmon", "lohi", "fillet"]),
    ("rainbow_trout", "Rainbow trout fillet, Finnish 5 kg", "Saaristo Fish", "fish", "trout", ["fillet", "fresh"], "kg", 5.0, 1, 21.40, ["fish"], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-111", 1, 0.93, 80, [], ["trout", "kirjolohi", "fillet"]),
    ("cod_loin", "Cod loin, frozen 4 kg", "Pohjoisvesi", "fish", "cod", ["loin", "frozen"], "kg", 4.0, 2, 18.60, ["fish"], [], ["gluten_free", "milk_free"], ["msc"], "IS", "SUP-114", 2, 0.95, 160, [], ["cod", "turska"]),
    ("baltic_herring", "Baltic herring fillets 3 kg", "Saaristo Fish", "fish", "herring", ["fillet"], "kg", 3.0, 2, 8.90, ["fish"], [], ["gluten_free", "milk_free"], ["msc_expired", "hs"], "FI", "SUP-111", 1, 0.92, 90, [], ["herring", "silakka"]),
    ("pikeperch", "Pike-perch fillet, wild 3 kg", "Järvikala", "fish", "pikeperch", ["fillet"], "kg", 3.0, 1, 34.00, ["fish"], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-116", 2, 0.90, 30, [], ["pike-perch", "kuha", "zander"]),
    ("shrimps", "Shrimps, cooked & peeled 1 kg", "Pohjoisvesi", "fish", "shellfish", ["shrimp"], "kg", 1.0, 6, 15.90, ["crustaceans"], [], ["gluten_free", "milk_free"], ["msc"], "GL", "SUP-114", 2, 0.94, 120, [], ["shrimps", "katkarapu", "prawns"]),
    ("mussels", "Blue mussels, cooked 1 kg", "Pohjoisvesi", "fish", "shellfish", ["mussel"], "kg", 1.0, 5, 7.80, ["molluscs"], [], ["gluten_free", "milk_free"], [], "DK", "SUP-114", 3, 0.90, 60, [], ["mussels", "simpukka"]),
    # ---------------- BAKERY ----------------
    ("rye_bread", "Sourdough rye bread, sliced 1 kg", "Leipomo Ruis", "bakery", "bread", ["rye"], "kg", 1.0, 8, 4.10, ["cereals_gluten"], [], ["vegan", "milk_free"], ["hs"], "FI", "SUP-121", 1, 0.97, 400, [], ["rye bread", "ruisleipä", "bread"]),
    ("bread_rolls", "Wheat bread rolls 60 g, frozen 50 pcs", "Leipomo Ruis", "bakery", "bread", ["roll"], "pcs", 50, 4, 0.22, ["cereals_gluten"], ["sesame", "milk"], ["vegetarian"], [], "FI", "SUP-121", 1, 0.97, 4000, [], ["bread rolls", "rolls", "sämpylä", "bread"]),
    ("karelian_pies", "Karelian rice pies, frozen 60 pcs", "Leipomo Ruis", "bakery", "pastry", ["karelian"], "pcs", 60, 2, 0.39, ["cereals_gluten", "milk"], [], ["vegetarian"], ["hs"], "FI", "SUP-121", 1, 0.97, 1800, [], ["karelian pies", "karjalanpiirakka", "pies"]),
    ("croissants", "Butter croissants, frozen 48 pcs", "Leipomo Aamu", "bakery", "pastry", ["croissant"], "pcs", 48, 2, 0.48, ["cereals_gluten", "milk", "eggs"], ["nuts"], ["vegetarian"], [], "FR", "SUP-124", 2, 0.94, 960, [], ["croissants", "pastry"]),
    ("cinnamon_buns", "Cinnamon buns, frozen 40 pcs", "Leipomo Aamu", "bakery", "pastry", ["bun"], "pcs", 40, 2, 0.55, ["cereals_gluten", "milk", "eggs"], [], ["vegetarian"], ["hs"], "FI", "SUP-124", 1, 0.95, 800, [], ["cinnamon buns", "korvapuusti", "buns"]),
    ("gf_bread", "Gluten-free seeded bread 500 g", "Leipomo Aamu", "bakery", "bread", ["gluten_free"], "kg", 0.5, 10, 9.60, ["sesame"], [], ["vegan", "gluten_free", "milk_free"], ["glutenfree"], "FI", "SUP-124", 2, 0.93, 120, [], ["gluten-free bread", "bread"]),
    ("sourdough_wheat", "Wheat sourdough loaf 700 g", "Leipomo Ruis", "bakery", "bread", ["sourdough"], "kg", 0.7, 6, 6.30, ["cereals_gluten"], [], ["vegan", "milk_free"], [], "FI", "SUP-121", 1, 0.96, 200, [], ["sourdough", "bread"]),
    # ---------------- EVENT / SEASONAL ADDITIONS ----------------
    ("choc_dark_kaakaotalo", "Dark chocolate couverture 70% 2.5 kg", "Kaakaotalo", "dry_goods", "chocolate", ["dark"], "kg", 2.5, 4, 14.80, ["soybeans"], ["milk", "nuts"], ["vegetarian"], ["ra"], "BE", "SUP-097", 2, 0.95, 80, [], ["chocolate", "dark chocolate", "suklaa"]),
    ("choc_dark_nutfree", "Dark chocolate drops 60%, nut-free facility 2 kg", "Suklaapaja", "dry_goods", "chocolate", ["dark"], "kg", 2.0, 4, 16.20, ["soybeans"], [], ["vegan"], ["fairtrade"], "FI", "SUP-098", 2, 0.96, 40, [], ["chocolate", "dark chocolate", "suklaa"]),
    ("ham_christmas", "Christmas ham, cured, whole approx. 8 kg", "Pohjan Liha", "meat", "ham_whole", ["christmas"], "kg", 8.0, 1, 11.90, [], [], ["gluten_free", "milk_free"], ["hs"], "FI", "SUP-101", 2, 0.95, 400, [], ["christmas ham", "kinkku", "joulukinkku", "ham"]),
    ("swede", "Swede (lanttu) 10 kg", "Peltola Farms", "produce", "root_veg", ["swede"], "kg", 10.0, 1, 1.30, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.96, 300, [], ["swede", "lanttu", "rutabaga"]),
    ("beetroot_cooked", "Beetroot, cooked & peeled 5 kg", "Peltola Farms", "produce", "beetroot", ["cooked"], "kg", 5.0, 2, 2.40, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-085", 1, 0.96, 300, [], ["beetroot", "punajuuri"]),
    ("pickled_cucumber", "Pickled cucumbers 2.5 kg", "Sinappila", "dry_goods", "pickles", ["cucumber"], "kg", 2.5, 4, 3.90, ["mustard"], [], ["vegan", "gluten_free"], [], "FI", "SUP-093", 2, 0.95, 160, [], ["pickled cucumber", "suolakurkku", "pickles"]),
    ("porridge_rice", "Porridge rice, round grain 5 kg", "Aitta", "dry_goods", "rice", ["porridge"], "kg", 5.0, 2, 2.20, [], [], ["vegan", "gluten_free"], [], "IT", "SUP-081", 2, 0.96, 300, [], ["porridge rice", "puuroriisi", "rice"]),
    ("dill_fresh", "Fresh dill 0.5 kg", "Lasitarha Närpiö", "produce", "herbs", ["dill"], "kg", 0.5, 4, 14.00, [], [], ["vegan", "gluten_free"], ["hs"], "FI", "SUP-087", 1, 0.94, 40, [], ["dill", "tilli", "herbs"]),
]


QUALITY = {"Kaarna Meijeri": 4.7, "Maitokaari": 4.4, "Tunturi Dairy": 4.5, "Laaksola": 4.1, "Kanala Peltola": 4.4,
           "Kaura&Co": 4.6, "Aamukaura": 4.0, "Pähkinäpuu": 4.2, "Soija Nord": 4.3, "Herne Labs": 3.9, "Aitta": 4.0,
           "Peltola Farms": 4.5, "Kahvila Kaarna": 4.6, "Teehetki": 4.0, "Sinappila": 4.3, "Mansikkala": 4.6,
           "Lasitarha Närpiö": 4.4, "Sienitila Kuusi": 4.2, "Hedelmätarha Ahvenanmaa": 4.3, "Tropiikki Trade": 3.9,
           "Pohjan Liha": 4.4, "Kanatila Laine": 4.2, "Lapin Riista": 4.7, "Saaristo Fish": 4.5, "Pohjoisvesi": 4.2,
           "Järvikala": 4.6, "Leipomo Ruis": 4.6, "Leipomo Aamu": 4.1, "Kaakaotalo": 4.5, "Suklaapaja": 4.4}


def carbon_class(cat, kind, country):
    """Indicative climate-impact class A (low) .. E (high) — synthetic, for ranking demos only."""
    if kind == "beef" or kind == "game":
        return "E"
    if cat in ("meat",) or kind in ("cheese", "butter"):
        return "D"
    if cat in ("dairy", "fish"):
        return "C"
    if country != "FI" and cat == "produce":
        return "B"
    return "A"


SHELF_LIFE = {"milk": 10, "cream": 14, "butter": 60, "cheese": 45, "yogurt": 21, "quark": 21, "sour_cream": 21,
              "eggs": 28, "plant_drink": 120, "plant_cream": 120, "plant_yogurt": 30, "tofu": 30, "salmon": 5,
              "trout": 5, "pikeperch": 4, "herring": 4, "beef": 10, "chicken": 7, "pork": 10, "cold_cuts": 21,
              "sausage": 21, "potato": 30, "tomato": 7, "cucumber": 7, "salad": 5, "mushroom": 5, "celery": 10,
              "fruit": 14, "root_veg": 30, "onion": 60, "bread": 5}
# kg CO2e per kg, category/kind level, rounded literature ranges — ESTIMATES for awareness only
CO2E = {"milk": 1.3, "cream": 4.5, "butter": 9.0, "cheese": 9.0, "yogurt": 1.6, "quark": 2.5, "sour_cream": 3.5,
        "eggs": 3.0, "plant_drink": 0.4, "plant_cream": 0.6, "plant_yogurt": 0.7, "tofu": 2.0, "plant_protein": 1.5,
        "beef": 30.0, "game": 15.0, "pork": 6.0, "chicken": 4.0, "cold_cuts": 6.0, "sausage": 5.0, "salmon": 5.0,
        "trout": 4.0, "cod": 3.5, "herring": 1.5, "pikeperch": 2.5, "shellfish": 8.0, "potato": 0.2, "berries": 0.6,
        "bread": 0.9, "pastry": 1.6, "coffee": 9.0, "tea": 5.0, "rice": 2.5, "pasta": 1.2}
PIECE_KG = {"eggs": 0.06, "bread": 0.06, "pastry": 0.07, "tea": 0.002, "salad": 0.5}


def gtin14(n: int) -> str:
    """Build a GTIN-14 (indicator 0) from a fictional GS1 company prefix 643999 + item ref."""
    body = f"0643999{n:06d}"  # 13 digits, check digit appended
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    check = (10 - total % 10) % 10
    return body + str(check)


def derive_diet(allergens, may, explicit):
    d = set(explicit)
    if "milk" not in allergens and "milk" not in may:
        d.add("milk_free")
    if not ({"nuts", "peanuts"} & (set(allergens) | set(may))):
        d.add("nut_free")
    if "eggs" not in allergens and "eggs" not in may:
        d.add("egg_free")
    if "cereals_gluten" in allergens:
        d.discard("gluten_free")
    if "milk" in allergens:
        d.discard("milk_free")
    return sorted(d)


def main():
    out = []
    for i, row in enumerate(P, start=1):
        (key, name, brand, cat, kind, variant, unit, pack, upc, price, allergens, may, diet, certs,
         country, sup, lead, ontime, stock, inbound, kw) = row
        for a in allergens + may:
            assert a in ALLERGENS, a
        case_qty = round(pack * upc, 3)
        out.append({
            "key": key,
            "gtin": gtin14(100 + i * 7),
            "aimoSku": f"AIMO-{400000 + i * 13}",
            "name": name,
            "brand": brand,
            "category": cat,
            "kind": kind,
            "variant": variant,
            "keywords": kw,
            "unit": unit,
            "packSize": pack,
            "unitsPerCase": upc,
            "caseQty": case_qty,
            "unitPrice": price,
            "currency": "EUR",
            "priceBasis": f"per {unit}",
            "allergens": allergens,
            "mayContain": may,
            "diet": derive_diet(allergens, may, diet),
            "certificates": [CERT[c] for c in certs],
            "origin": {"country": country, "supplierId": sup},
            "qualityGrade": QUALITY[brand],
            "carbonClass": carbon_class(cat, kind, country),
            "shelfLifeDays": 365 if "frozen" in variant or "frozen" in name.lower() else SHELF_LIFE.get(kind, 180),
            "kgPerUnit": PIECE_KG.get(kind, 0.06) if unit == "pcs" else (1.03 if unit == "L" else 1.0),
            "co2eKgPerKg": CO2E.get(kind, 1.0),
            "leadTimeDays": lead,
            "onTimeRate": ontime,
            "stock": stock,
            "inbound": [{"inDays": d, "qty": q} for d, q in inbound],
        })
    path = Path(__file__).resolve().parent.parent / "gateway" / "data" / "catalog.json"
    path.write_text(json.dumps({"allergens": ALLERGENS, "products": out}, indent=1, ensure_ascii=False))
    print(f"wrote {len(out)} products -> {path}")


if __name__ == "__main__":
    main()
