"""Task 3: the query compiler — whitelisted fields, bound parameters, calcs and comparisons."""
import pytest

from gateway.analytics import explain, query, store
from gateway.playbook.engine import GuardFailed

CONN = store.load()
POH = "BUY-POHJOLA"


def q(spec, buyer=POH):
    return query.run(CONN, spec, buyer)


def test_spend_by_month_for_one_kitchen_has_12_rows():
    r = q({"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}],
           "filters": [{"field": "site", "op": "eq", "value": "Pohjola Helsinki"}]})
    assert len(r["rows"]) == 12 and r["shape"]["timeDim"] == "date"
    assert all(row["spend"] > 0 for row in r["rows"])


def test_top_n_with_other_keeps_the_total():
    total = q({"measures": ["spend"]})["rows"][0]["spend"]
    r = q({"measures": ["spend"], "dimensions": ["product"], "sort": [{"by": "spend", "dir": "desc"}], "limit": 5, "other": True})
    assert len(r["rows"]) == 6 and r["rows"][-1]["product"] == "Other"
    assert sum(x["spend"] for x in r["rows"]) == pytest.approx(total, rel=1e-6)


def test_share_sums_to_100():
    r = q({"measures": ["spend"], "dimensions": ["category"], "calc": [{"type": "share", "of": "spend"}]})
    assert sum(x["spend_share"] for x in r["rows"]) == pytest.approx(100, abs=0.05)  # 2-decimal rounding per row


def test_compare_previous_period_adds_change():
    r = q({"measures": ["waste"], "dimensions": ["site"], "period": {"from": "2026-08-01", "to": "2026-10-31"},
           "compare": "previous_period"})
    row = r["rows"][0]
    assert "waste_prev" in row and "waste_change_pct" in row


def test_running_total_and_rank_and_moving_average():
    r = q({"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}],
           "calc": [{"type": "running_total", "of": "spend"}, {"type": "moving_avg", "of": "spend", "window": 3},
                    {"type": "rank", "of": "spend"}, {"type": "change_pct", "of": "spend"}]})
    rows = r["rows"]
    assert rows[-1]["spend_running_total"] == pytest.approx(sum(x["spend"] for x in rows))
    assert sorted(x["spend_rank"] for x in rows) == list(range(1, 13))
    assert rows[0]["spend_change_pct"] is None and rows[1]["spend_change_pct"] is not None


def test_relative_period_last_3_months():
    r = q({"measures": ["orders"], "dimensions": [{"field": "date", "grain": "month"}], "period": "last_3_months"})
    assert len(r["rows"]) == 3


def test_unknown_field_gives_a_fix_hint():
    with pytest.raises(GuardFailed) as e:
        q({"measures": ["revenue"]})
    assert "spend" in e.value.extra["fix"]
    with pytest.raises(GuardFailed) as e:
        q({"measures": ["spend"], "dimensions": ["colour"]})
    assert "category" in e.value.extra["fix"]


def test_bad_operator_and_injection_are_rejected():
    with pytest.raises(GuardFailed):
        q({"measures": ["spend"], "filters": [{"field": "site", "op": "drop", "value": "x"}]})
    r = q({"measures": ["spend"], "filters": [{"field": "product", "op": "eq", "value": "x' OR '1'='1"}]})
    assert r["rows"] == []  # the quote is a bound value, not SQL


def test_buyers_only_see_their_own_data():
    r = q({"measures": ["spend"], "dimensions": ["site"]}, buyer="BUY-KOULU")
    assert {x["site"] for x in r["rows"]} == {"Kaarela production kitchen", "Kannelmäki school kitchen"}


def test_empty_result_explains_itself():
    r = q({"measures": ["spend"], "dimensions": ["product"], "filters": [{"field": "product", "op": "eq", "value": "Nothing like this"}]})
    assert r["rows"] == []
    assert explain.run(r)["caption"] == "No orders match these filters."


def test_explain_gives_three_plain_facts():
    r = q({"measures": ["waste"], "dimensions": [{"field": "date", "grain": "month"}]})
    e = explain.run(r)
    assert e["caption"] and len(e["facts"]) == 3


def test_monthly_caption_names_the_grain_and_skips_the_partial_month():
    r = q({"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}]})
    e = explain.run(r)
    assert e["caption"].startswith("Spend by month")
    assert "Nov 2026" not in e["facts"][2] and "still running" in e["facts"][2]


def test_running_month_is_not_called_the_lowest():
    e = explain.run(q({"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}]}))
    assert "Nov 2026" not in e["facts"][1]
