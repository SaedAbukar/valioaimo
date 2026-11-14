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


# ---------------------------------------------------------------- Task 9: agent_activity and demand datasets
from gateway.analytics import datasets, query  # noqa: E402

OVER = "I need 3,000 litres of lactose-free milk by Monday."
BRIEF = "I need 1,000 litres of lactose-free milk by Monday."
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
KOULU = {"Authorization": "Bearer demo-key-kaarela"}


def flow(c, text, headers=AGENT, approve=None, stale=False):
    sid = c.post("/v1/sessions", json={}, headers=headers).json()["sessionId"]
    plan = None
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards"):
        r = c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": text} if t == "parse_request" else {}, headers=headers).json()
        if t == "plan_basket":
            plan = r["output"]
        if t == "check_basket":
            dec = r["output"]["decision"]
    if dec == "needs_ok" and approve:
        aid = c.post(f"/v1/sessions/{sid}/tools/request_approval", json={}, headers=headers).json()["output"]["approval"]["approvalId"]
        c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=approve)
    if dec in ("auto", "tell_me") or approve:
        if stale:
            c.post("/v1/demo/clock", json={"advanceMinutes": 16}, headers=OPS)
        ids = [o["offerId"] for o in plan["offers"]]
        r = c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": ids}, headers=headers)
        if r.status_code == 409:
            for t in ("plan_basket", "check_basket", "render_cards"):
                plan = c.post(f"/v1/sessions/{sid}/tools/{t}", json={}, headers=headers).json()["output"] if t == "plan_basket" else plan
                if t != "plan_basket":
                    c.post(f"/v1/sessions/{sid}/tools/{t}", json={}, headers=headers)
            c.post(f"/v1/sessions/{sid}/tools/place_order", json={"offerIds": [o["offerId"] for o in plan["offers"]]}, headers=headers)
    return sid


def test_agent_activity_counts_requotes_and_approval_wait(c):
    flow(c, OVER, approve=LAURA)
    flow(c, "20 kg butter by Monday", stale=True)
    gw = c.app.state.gw()
    rows = datasets.agent_activity(gw)
    assert {"buyer", "site", "agent", "channel", "date", "decision", "top_rule", "requotes", "c409", "c422",
            "time_to_order_s", "approval_wait_s", "approver", "approved", "order_total", "live_price_share"} <= set(rows[0])
    sid = c.post("/v1/insights/sessions", json={}, headers=AGENT).json()["sessionId"]
    c.post(f"/v1/insights/sessions/{sid}/tools/describe_data", json={"dataset": "agent_activity"}, headers=AGENT)
    r = c.post(f"/v1/insights/sessions/{sid}/tools/run_query", headers=AGENT,
               json={"dataset": "agent_activity", "measures": ["sessions", "requote_rate", "p90_approval_wait", "autonomous_rate"]}).json()
    row = r["output"]["rows"][0]
    assert row["sessions"] == 2 and row["requote_rate"] > 0 and row["p90_approval_wait"] is not None


def test_describe_data_lists_datasets(c):
    sid = c.post("/v1/insights/sessions", json={}, headers=AGENT).json()["sessionId"]
    d = c.post(f"/v1/insights/sessions/{sid}/tools/describe_data", json={"dataset": "demand"}, headers=AGENT).json()["output"]
    assert set(d["datasets"]) == {"orders", "agent_activity", "demand"} and "unmet_qty" in d["measures"]


def test_demand_records_unmet_with_reason(c):
    flow(c, "60 L oat drink by Monday", headers=KOULU)
    rows = [r for r in datasets.demand(c.app.state.gw()) if r["buyer"] == "BUY-KOULU"]
    unmet = [r for r in rows if r["source"] == "unmet"]
    assert unmet and unmet[0]["unmet_reason"] == "blocked_allergen" and unmet[0]["qty"] == 60


def test_buyer_sees_only_own_rows(c):
    flow(c, "60 L oat drink by Monday", headers=KOULU)
    flow(c, BRIEF)
    gw = c.app.state.gw()
    res = query.run(datasets.connect(gw), {"dataset": "demand", "measures": ["planned_qty"], "dimensions": ["buyer"]}, "BUY-POHJOLA")
    assert {r["buyer"] for r in res["rows"]} == {"BUY-POHJOLA"}


def test_ops_k_anonymity_suppresses_small_groups(c):
    flow(c, BRIEF)
    flow(c, "60 L oat drink by Monday", headers=KOULU)
    gw = c.app.state.gw()
    res = query.run(datasets.connect(gw), {"dataset": "demand", "measures": ["planned_qty", "unmet_qty"], "dimensions": ["category"]},
                    None, k_anon=3)
    assert res["rows"] == [] and res["suppressed"] >= 1  # every category has fewer than 3 buyers
    with pytest.raises(Exception):
        query.run(datasets.connect(gw), {"dataset": "demand", "measures": ["planned_qty"], "dimensions": ["buyer"]}, None, k_anon=3)
