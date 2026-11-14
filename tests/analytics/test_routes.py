"""REST facade for insights, history and kitchens; one tool manifest for any agent."""
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402


@pytest.fixture(scope="module")
def c():
    return TestClient(make_app(live=False))


def test_tool_manifest_covers_order_and_insight_journeys(c):
    m = c.get("/v1/tools").json()
    names = {t["name"] for t in m["tools"]}
    assert {"start_session", "parse_request", "place_order", "record_usage"} <= names
    assert {"start_analysis", "describe_data", "run_query", "build_chart", "explain_result"} <= names
    assert m["playbooks"] == {"order": "1.0.0", "insight": "1.0.0"}


def test_insight_rails_over_rest(c):
    sid = c.post("/v1/insights/sessions", json={"buyerId": "BUY-POHJOLA"}).json()["sessionId"]
    r = c.post(f"/v1/insights/sessions/{sid}/tools/build_chart", json={"type": "line"})
    assert r.status_code == 409 and r.json()["next_allowed_tools"]
    c.post(f"/v1/insights/sessions/{sid}/tools/describe_data", json={})
    bad = c.post(f"/v1/insights/sessions/{sid}/tools/run_query", json={"measures": ["sales"]})
    assert bad.status_code == 422 and "spend" in bad.json()["fix"]


def test_ask_wrapped_history_kitchens(c):
    a = c.post("/v1/insights/ask", json={"buyerId": "BUY-POHJOLA", "prompt": "waste by month", "filters": {}}).json()
    assert a["chart"]["$schema"] and a["caption"]
    assert len(c.get("/v1/insights/wrapped?buyerId=BUY-POHJOLA").json()["cards"]) >= 8
    h = c.get("/v1/orders/history?buyerId=BUY-POHJOLA&page=2&size=25").json()
    assert h["page"] == 2 and len(h["orders"]) == 25
    assert len(c.get("/v1/kitchens?buyerId=BUY-POHJOLA").json()["sites"]) == 3
