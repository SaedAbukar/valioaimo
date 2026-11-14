"""Step 1 parser: EN + FI cases (ported from the v1 JS parser tests)."""
import json
from datetime import date
from pathlib import Path

import pytest

from gateway.playbook import understand as U

RECIPES = json.loads((Path(__file__).resolve().parents[2] / "gateway" / "data" / "recipes.json").read_text())["recipes"]
TODAY = date(2026, 11, 13)  # demo clock: Fri 13 Nov 2026
SITE = {"name": "Pohjola Helsinki – central kitchen"}


def P(text):
    return U.parse(text, TODAY, SITE, RECIPES)


def dishes(b):
    return {d["recipeId"] for d in b["event"]["dishes"]}


def test_fi_christmas_party():
    b = P("Pikkujoulut lauantaina 21.11. 120 hengelle: kinkku, laatikot, rosolli ja riisipuuro. 6 vegaania, yksi pähkinäallergia.")
    assert b["lang"] == "fi" and b["event"]["date"] == "2026-11-21" and b["event"]["guests"] == 120
    assert b["event"]["type"] == "christmas_party"
    assert b["constraints"]["dietCounts"] == {"vegan": 6} and b["constraints"]["allergies"] == {"nuts": 1}
    assert {"kinkku", "rosolli", "riisipuuro"} <= dishes(b)


def test_fi_next_friday_and_diets():
    b = P("Syntymäpäivät ensi perjantaina 40 vieraalle: lohikeitto ja mustikkapiirakka. 3 gluteenitonta, 2 laktoositonta.")
    assert b["event"]["date"] == "2026-11-20" and b["event"]["guests"] == 40
    assert b["constraints"]["dietCounts"] == {"gluten_free": 3, "lactose_free": 2}
    assert "lohikeitto" in dishes(b)


def test_fi_tomorrow_and_allergy_count():
    b = P("Lounas huomenna 25 henkilölle: kanacurry. Yksi vegaani, kaksi kalaallergikkoa.")
    assert b["event"]["date"] == "2026-11-14" and b["event"]["guests"] == 25
    assert b["constraints"]["dietCounts"] == {"vegan": 1} and b["constraints"]["allergies"] == {"fish": 2}


def test_en_gala():
    b = P("Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. 12 vegan, 8 gluten-free, 1 nut allergy.")
    assert b["lang"] == "en" and b["event"]["date"] == "2026-11-21" and b["event"]["guests"] == 180
    assert {"salmon_starter", "beef_tenderloin", "choc_mousse"} <= dishes(b)
    assert b["complete"] and b["style"]["status"] == "assumed"


def test_en_next_saturday():
    b = P("Wedding next Saturday for 80 guests: salmon soup, reindeer, blueberry pie. 4 vegetarians, two fish allergies.")
    assert b["event"]["date"] == "2026-11-21" and b["event"]["guests"] == 80
    assert b["constraints"]["dietCounts"] == {"vegetarian": 4} and b["constraints"]["allergies"] == {"fish": 2}


@pytest.mark.parametrize("text,qty,unit,when", [
    ("I need 1,000 L lactose-free milk by Monday", 1000, "L", "2026-11-16"),
    ("60 L oat drink by Monday", 60, "L", "2026-11-16"),
    ("Tarvitsen 40 kg perunoita huomenna", 40, "kg", "2026-11-14"),
])
def test_item_orders(text, qty, unit, when):
    b = P(text)
    assert b["kind"] == "items" and b["lines"][0]["qty"] == qty and b["lines"][0]["unit"] == unit
    assert b["when"]["value"] == when and b["complete"]


def test_missing_date_is_marked_missing_not_guessed():
    b = P("200 L milk")
    assert b["missing"] == ["when"] and not b["complete"]
