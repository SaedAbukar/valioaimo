"""Task 11: Valio Aimo operations view — channel metrics, forward demand, lost sales; ops credential only, k >= 3."""
import json
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402

OPS = {"Authorization": "Bearer demo-ops"}
TOKENS = {"BUY-POHJOLA": "demo-key-pohjola", "BUY-KAARI": "demo-key-kaari", "BUY-KOULU": "demo-key-kaarela", "BUY-UUSI": "demo-key-uusi"}


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def agent_run(c, bid, text):
    """A scripted external agent over REST (the bench's agent): follows next_allowed_tools, orders when allowed."""
    from scripts import agent_bench
    return agent_bench.Agent(agent_bench.local_transport(c), bid, {"token": TOKENS[bid], "text": text}).run()["outcome"]


def test_ops_endpoints_forbid_agents_and_humans(c):
    for path in ("/v1/ops/metrics", "/v1/ops/demand", "/v1/ops/lost-sales"):
        assert c.get(path).status_code == 401
        for tok in ("demo-key-pohjola", "demo-human-usr-lvirtanen", "demo-user-buy-pohjola"):
            assert c.get(path, headers={"Authorization": f"Bearer {tok}"}).status_code == 403, (path, tok)
        assert c.get(path, headers=OPS).status_code == 200
        assert path in c.get("/openapi.json").json()["paths"]


def test_forward_demand_aggregates_across_buyers_with_k_anonymity(c):
    agent_run(c, "BUY-POHJOLA", "I need 1,000 litres of lactose-free milk by Monday.")
    agent_run(c, "BUY-KAARI", "40 L soy drink by Monday")
    agent_run(c, "BUY-KOULU", "60 L oat drink by Monday")
    agent_run(c, "BUY-UUSI", "100 L milk by Wednesday")
    r = c.get("/v1/ops/demand?by=day&from=2026-11-13&to=2026-11-30", headers=OPS).json()
    days = {row["date"]: row for row in r["rows"]}
    assert "2026-11-16" in days and days["2026-11-16"]["planned_qty"] > 0  # Monday: three customers
    assert r["suppressed"] >= 1 and r["kAnonymity"] == 3  # Wednesday: only one customer, so hidden
    assert "BUY-" not in json.dumps(r) and r["chart"]["$schema"]
    assert c.get("/v1/ops/demand?by=buyer", headers=OPS).status_code == 422


def test_lost_sales_lists_reasons(c):
    gw = c.app.state.gw()
    body = dict(gw.mandates["BUY-POHJOLA"]["mandate"])
    body["hardExclusions"] = {"allergens": ["milk"], "diet": []}
    gw.register_mandate("BUY-POHJOLA", gw.sign_mandate("BUY-POHJOLA", body))
    agent_run(c, "BUY-POHJOLA", "I need 1,000 litres of lactose-free milk by Monday.")
    agent_run(c, "BUY-KAARI", "30 L whipping cream by Monday")
    agent_run(c, "BUY-KOULU", "60 L oat drink by Monday")
    r = c.get("/v1/ops/lost-sales", headers=OPS).json()
    reasons = {row["unmet_reason"]: row for row in r["rows"]}
    assert "blocked_allergen" in reasons and reasons["blocked_allergen"]["unmet_qty"] >= 1090
    assert r["explain"] and "BUY-" not in json.dumps(r)


def test_ops_metrics_match_bench_runs(c):
    from scripts import agent_bench
    agent_bench.bench(agent_bench.local_transport(c), agents=8)
    gw = c.app.state.gw()
    decided = [s["data"]["decision"]["decision"] for s in gw.engine.sessions.values() if s["data"].get("decision")]
    want = 100.0 * sum(d in ("auto", "tell_me") for d in decided) / len(decided)
    m = c.get("/v1/ops/metrics", headers=OPS).json()
    assert m["channel"]["autonomous_rate"] == pytest.approx(want, abs=0.01)
    assert {"sessions", "approval_rate", "blocked_rate", "requote_rate", "p50_time_to_order", "p90_approval_wait", "fill_rate"} <= set(m["channel"])
    assert m["raw"]["toolCalls"] and m["kAnonymity"] == 3


def test_ops_mcp_mode_has_only_ops_tools():
    import asyncio
    from gateway import mcp_app
    from gateway.core import Gateway
    gw = Gateway()
    server, fns = mcp_app.build_ops(lambda: gw)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"ops_metrics", "ops_demand", "ops_lost_sales"}
    assert json.loads(fns["ops_demand"](by="day"))["kAnonymity"] == 3
    assert json.loads(fns["ops_demand"](by="buyer"))["status"] == 422


def test_seeded_demo_has_enough_customers_for_the_operations_view(monkeypatch):
    monkeypatch.setenv("AIMO_SEED_DEMO", "1")
    c = TestClient(make_app(live=False))
    m = c.get("/v1/ops/metrics", headers=OPS).json()
    assert m["channel"] and m["channel"]["sessions"] >= 4
    d = c.get("/v1/ops/demand?by=day", headers=OPS).json()
    assert d["rows"] and d["chart"]
    chats = c.get("/v1/chats", headers={"Authorization": "Bearer demo-user-buy-pohjola"}).json()["chats"]
    assert chats and "Gala" in chats[-1]["title"] or any("Gala" in x["title"] for x in chats)  # the app still opens on the gala


def test_demand_chart_uses_thin_bars_and_day_labels(monkeypatch):
    monkeypatch.setenv("AIMO_SEED_DEMO", "1")
    c = TestClient(make_app(live=False))
    ch = c.get("/v1/ops/demand?by=day", headers=OPS).json()["chart"]
    assert ch["mark"]["type"] == "bar" and ch["mark"]["size"] <= 24 and ch["mark"]["cornerRadiusEnd"] == 4
    assert ch["encoding"]["x"]["field"] == "day" and ch["encoding"]["x"]["type"] == "ordinal"
    assert ch["data"]["values"][0]["day"] == "Mon 16.11."
    assert {t["field"] for t in ch["encoding"]["tooltip"]} >= {"planned_qty", "ordered_qty", "unmet_qty"}
