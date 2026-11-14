"""v5 analytics: authenticated insight rails (Task 8), new datasets (Task 9), forecast/anomaly/explain_change (Task 10)."""
import asyncio
import json
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402

AGENT = {"Authorization": "Bearer demo-key-pohjola"}
OPS = {"Authorization": "Bearer demo-ops"}


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


# ---------------------------------------------------------------- Task 8
def test_insight_session_for_other_buyer_is_403(c):
    assert c.post("/v1/insights/sessions", json={"buyerId": "BUY-KOULU"}, headers=AGENT).status_code == 403
    assert c.post("/v1/insights/sessions", json={"buyerId": "BUY-POHJOLA"}).status_code == 401
    sid = c.post("/v1/insights/sessions", json={}, headers=AGENT).json()["sessionId"]
    r = c.post(f"/v1/insights/sessions/{sid}/tools/describe_data", json={}, headers={"Authorization": "Bearer demo-key-kaarela"})
    assert r.status_code == 403


def test_insight_mcp_tools_are_typed():
    os.environ["AIMO_LIVE"] = "0"
    import gateway.mcp_server as m
    tools = {t.name: t for t in asyncio.run(m.mcp.list_tools())}
    rq = tools["run_query"].input_schema["properties"]
    assert {"measures", "dimensions", "filters", "dataset"} <= set(rq) and "args_json" not in rq
    assert "type" in tools["build_chart"].input_schema["required"]
    assert json.loads(m.start_analysis("BUY-KOULU"))["status"] == 403
