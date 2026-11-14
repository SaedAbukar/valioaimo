"""Task 4: the analyst answers typed questions through the insight rails (rule engine, no network)."""
import pytest

from gateway.analytics.analyst import Analyst
from gateway.core import Gateway


@pytest.fixture(scope="module")
def A():
    a = Analyst(Gateway())
    a.client = None  # force the rule engine
    return a


def test_waste_by_month_is_a_12_month_line(A):
    r = A.ask("waste by month", {}, "BUY-POHJOLA")
    assert r["engine"] == "rules" and r["chart"]["usermeta"]["chartType"] == "line"
    assert len(r["rows"]) == 12 and r["spec"]["measures"] == ["waste"]


def test_top_products_in_a_named_kitchen(A):
    r = A.ask("top 5 products by spend in Tampere", {}, "BUY-POHJOLA")
    assert r["chart"]["usermeta"]["chartType"] == "bar" and len(r["rows"]) == 5
    assert {"field": "site", "op": "eq", "value": "Pohjola Tampere"} in r["spec"]["filters"]


def test_finnish_category_breakdown(A):
    r = A.ask("kulutus kategorioittain", {}, "BUY-POHJOLA")
    assert r["spec"]["dimensions"] == ["category"] and r["spec"]["measures"] == ["spend"]


def test_compare_kitchens_to_previous_period(A):
    r = A.ask("waste % by kitchen compared to previous period, last 3 months", {}, "BUY-POHJOLA")
    assert r["spec"]["compare"] == "previous_period" and r["spec"]["period"] == "last_3_months"
    assert "waste_pct_change_pct" in r["rows"][0]


def test_filters_from_the_page_are_applied(A):
    r = A.ask("spend by category", {"site": "Pohjola Turku", "period": "last_6_months"}, "BUY-POHJOLA")
    assert {"field": "site", "op": "eq", "value": "Pohjola Turku"} in r["spec"]["filters"]
    assert r["spec"]["period"] == "last_6_months"


def test_chart_word_wins(A):
    r = A.ask("orders by weekday and kitchen as a heatmap", {}, "BUY-POHJOLA")
    assert r["chart"]["usermeta"]["chartType"] == "heatmap"


def test_gibberish_still_answers_and_says_what_it_assumed(A):
    r = A.ask("blorp zzz", {}, "BUY-POHJOLA")
    assert r["chart"] and r["assumed"]
    assert r["spec"]["measures"] == ["spend"]


def test_steps_follow_the_rails(A):
    r = A.ask("co2 by category share", {}, "BUY-POHJOLA")
    assert [s["tool"] for s in r["steps"]] == ["start_analysis", "describe_data", "run_query", "suggest_chart", "build_chart", "explain_result"]
    assert r["chart"]["usermeta"]["chartType"] == "donut"
