"""Task 2: the insight playbook rails — order, audit, fix hints."""
import pytest

from gateway.analytics.engine import InsightEngine, insight_playbook
from gateway.core import Gateway
from gateway.playbook.engine import GuardFailed, StepNotAllowed


@pytest.fixture
def E():
    return InsightEngine(Gateway())


def start(E):
    return E.call(None, "start_analysis", {"buyerId": "BUY-POHJOLA"})["output"]["sessionId"]


def test_playbook_is_versioned_with_six_steps():
    pb = insight_playbook()
    assert pb["version"] == "1.0.0"
    assert [s["id"] for s in pb["steps"]] == ["start", "describe", "query", "suggest", "chart", "explain"]


def test_chart_before_query_is_409(E):
    sid = start(E)
    with pytest.raises(StepNotAllowed) as e:
        E.call(sid, "build_chart", {"type": "line"})
    assert "describe_data" in e.value.extra["next_allowed_tools"]


def test_full_run_and_audit(E):
    sid = start(E)
    d = E.call(sid, "describe_data")["output"]
    assert "spend" in d["measures"] and "site" in d["dimensions"] and d["sites"]
    vals = E.call(sid, "get_values", {"field": "category"})["output"]["values"]
    assert "Dairy" in vals
    r = E.call(sid, "run_query", {"measures": ["waste"], "dimensions": [{"field": "date", "grain": "month"}]})
    assert "suggest_chart" in r["next_allowed_tools"]
    s = E.call(sid, "suggest_chart")["output"]["suggestions"]
    spec = E.call(sid, "build_chart", {"type": s[0]["type"]})["output"]["chart"]
    assert spec["mark"]
    ex = E.call(sid, "explain_result")["output"]
    assert len(ex["facts"]) == 3
    evs = [e for e in E.gw.audit.events(trace_id=sid) if e["action"].startswith("insight.")]
    assert len(evs) == 7 and all(e["refs"]["insightPlaybookVersion"] == "1.0.0" for e in evs)


def test_bad_input_returns_fix_hint(E):
    sid = start(E)
    E.call(sid, "describe_data")
    with pytest.raises(GuardFailed) as e:
        E.call(sid, "run_query", {"measures": ["sales"]})
    assert e.value.extra["fix"]


def test_unknown_buyer_cannot_start(E):
    with pytest.raises(GuardFailed):
        E.call(None, "start_analysis", {"buyerId": "BUY-NOPE"})
