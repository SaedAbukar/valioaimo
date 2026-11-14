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


# ---------------------------------------------------------------- Task 10: forecast, anomaly, explain_change
from gateway.analytics import charts, explain, store  # noqa: E402

MONTHLY = {"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}]}


def test_forecast_marks_future_rows_and_bounds():
    res = query.run(store.load(), {**MONTHLY, "calc": [{"type": "forecast", "of": "spend", "horizon": 3}]}, "BUY-POHJOLA")
    fut = [r for r in res["rows"] if r.get("is_forecast")]
    past = [r for r in res["rows"] if not r.get("is_forecast")]
    assert len(fut) == 3 and [r["date"] for r in fut] == ["2026-12", "2027-01", "2027-02"]
    assert all(r["spend_lo"] <= r["spend"] <= r["spend_hi"] for r in fut) and fut[0]["spend"] > 0
    full = [r for r in past if not r.get("is_partial")]
    assert full[-1]["forecast_anchor"] is True and past[-1]["date"] == "2026-11" and past[-1]["is_partial"]  # Nov is still running
    assert "forecast" in json_facts(res)


def json_facts(res):
    return " ".join(explain.run(res)["facts"]).lower()


def test_forecast_needs_one_time_dimension():
    from gateway.playbook.engine import GuardFailed
    with pytest.raises(GuardFailed) as e:
        query.run(store.load(), {"measures": ["spend"], "dimensions": ["category"], "calc": [{"type": "forecast"}]}, "BUY-POHJOLA")
    assert e.value.extra["fix"]


def test_anomaly_flags_a_spike():
    conn = store.load()
    conn.execute("UPDATE line SET value_eur = value_eur * 6 WHERE buyer_id = 'BUY-POHJOLA' AND month = '2026-07'")
    res = query.run(conn, {**MONTHLY, "calc": [{"type": "anomaly", "of": "spend"}]}, "BUY-POHJOLA")
    flagged = [r["date"] for r in res["rows"] if r.get("is_anomaly")]
    assert flagged == ["2026-07"] and abs(next(r for r in res["rows"] if r["date"] == "2026-07")["spend_z"]) > 3
    assert "unusual" in json_facts(res)
    clean = query.run(store.load(), {**MONTHLY, "calc": [{"type": "anomaly", "of": "spend"}]}, "BUY-POHJOLA")
    assert not [r for r in clean["rows"] if r.get("is_anomaly")]


def test_explain_change_contributions_sum_to_total(c):
    sid = c.post("/v1/insights/sessions", json={}, headers=AGENT).json()["sessionId"]
    c.post(f"/v1/insights/sessions/{sid}/tools/describe_data", json={}, headers=AGENT)
    r = c.post(f"/v1/insights/sessions/{sid}/tools/explain_change", headers=AGENT, json={
        "measure": "spend", "period_a": {"from": "2026-08-01", "to": "2026-08-31"},
        "period_b": {"from": "2026-09-01", "to": "2026-09-30"}, "by": "site"}).json()["output"]
    total = r["change"]
    assert abs(sum(x["contribution"] for x in r["contributions"]) - total) <= 0.05
    assert len(r["contributions"]) <= 6 and r["sentences"][0].startswith(r["contributions"][0]["value"])
    assert "of the" in r["sentences"][0]
    bad = c.post(f"/v1/insights/sessions/{sid}/tools/explain_change", headers=AGENT, json={
        "measure": "waste_pct", "period_a": {"from": "2026-08-01", "to": "2026-08-31"},
        "period_b": {"from": "2026-09-01", "to": "2026-09-30"}, "by": "site"})
    assert bad.status_code == 422 and bad.json()["fix"]


def test_forecast_chart_is_dashed_and_has_band():
    res = query.run(store.load(), {**MONTHLY, "calc": [{"type": "forecast", "of": "spend", "horizon": 3}]}, "BUY-POHJOLA")
    spec = charts.build(res, {"type": "line"})
    layers = spec["layer"]
    marks = [l["mark"]["type"] if isinstance(l["mark"], dict) else l["mark"] for l in layers]
    assert "area" in marks and marks.count("line") == 2
    dashed = [l for l in layers if isinstance(l["mark"], dict) and l["mark"].get("strokeDash")]
    assert dashed and dashed[0]["transform"]
    band = next(l for l in layers if l["mark"]["type"] == "area")
    assert band["encoding"]["y"]["field"] == "spend_lo" and band["encoding"]["y2"]["field"] == "spend_hi"


def test_anomaly_chart_rings_the_points_with_a_tooltip():
    conn = store.load()
    conn.execute("UPDATE line SET value_eur = value_eur * 6 WHERE buyer_id = 'BUY-POHJOLA' AND month = '2026-07'")
    res = query.run(conn, {**MONTHLY, "calc": [{"type": "anomaly", "of": "spend"}]}, "BUY-POHJOLA")
    spec = charts.build(res, {"type": "line"})
    pts = [l for l in spec["layer"] if l["mark"]["type"] == "point"]
    assert pts and pts[0]["mark"]["strokeWidth"] >= 2 and pts[0]["encoding"]["tooltip"]
