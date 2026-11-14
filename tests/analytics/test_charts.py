"""Task 3: chart suggestions by result shape, and Vega-Lite specs for every chart type."""
import pytest

from gateway.analytics import charts, query, store
from gateway.playbook.engine import GuardFailed

CONN = store.load()


def q(spec):
    return query.run(CONN, spec, "BUY-POHJOLA")


MONTHLY = {"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}]}
BY_CAT = {"measures": ["spend"], "dimensions": ["category"]}
CAT_SITE = {"measures": ["spend"], "dimensions": ["category", "site"]}
TWO_MEASURES = {"measures": ["spend", "waste_pct"], "dimensions": ["product"], "limit": 30, "sort": [{"by": "spend", "dir": "desc"}]}
TOTAL = {"measures": ["spend"]}


def test_suggestions_follow_the_shape():
    assert charts.suggest(q(MONTHLY))[0]["type"] == "line"
    assert charts.suggest(q(BY_CAT))[0]["type"] in ("bar", "donut")
    assert charts.suggest(q(CAT_SITE))[0]["type"] in ("heatmap", "stacked", "grouped")
    assert charts.suggest(q(TWO_MEASURES))[0]["type"] == "scatter"
    assert charts.suggest(q(TOTAL))[0]["type"] == "kpi"


@pytest.mark.parametrize("ctype,spec", [
    ("line", MONTHLY), ("area", MONTHLY), ("column", MONTHLY), ("sparkline", MONTHLY), ("waterfall", MONTHLY),
    ("bar", BY_CAT), ("donut", BY_CAT), ("stacked", CAT_SITE), ("grouped", CAT_SITE), ("percent", CAT_SITE),
    ("heatmap", CAT_SITE), ("scatter", TWO_MEASURES), ("bubble", TWO_MEASURES), ("histogram", TWO_MEASURES),
    ("boxplot", {"measures": ["spend"], "dimensions": ["site", {"field": "date", "grain": "month"}]}),
    ("kpi", TOTAL),
])
def test_every_chart_type_builds_a_vega_lite_v5_spec(ctype, spec):
    out = charts.build(q(spec), {"type": ctype})
    assert out["$schema"].startswith("https://vega.github.io/schema/vega-lite/v5")
    assert out["data"]["values"]


def test_heatmap_uses_rect_and_two_encodings():
    out = charts.build(q(CAT_SITE), {"type": "heatmap"})
    assert out["mark"]["type"] == "rect" and {"x", "y", "color"} <= set(out["encoding"])


def test_table_is_a_plain_table():
    out = charts.build(q(BY_CAT), {"type": "table"})
    assert out["type"] == "table" and out["columns"][0]["name"] == "category"


def test_incompatible_chart_names_the_ones_that_fit():
    with pytest.raises(GuardFailed) as e:
        charts.build(q(TOTAL), {"type": "heatmap"})
    assert "kpi" in e.value.extra["fix"]


def test_unknown_chart_type_lists_all_types():
    with pytest.raises(GuardFailed) as e:
        charts.build(q(MONTHLY), {"type": "pie3d"})
    assert "line" in e.value.extra["fix"] and "heatmap" in e.value.extra["fix"]
