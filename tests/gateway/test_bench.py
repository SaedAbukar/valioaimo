"""Task 7: multi-agent benchmark — scripted agents over REST hold every invariant; the report lists the scores."""
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402
from scripts import agent_bench  # noqa: E402

OPS = {"Authorization": "Bearer demo-ops"}
AGENT = {"Authorization": "Bearer demo-key-pohjola"}


@pytest.fixture(scope="module")
def result():
    c = TestClient(make_app(live=False))
    return agent_bench.bench(agent_bench.local_transport(c), agents=20)


def test_bench_scripted_20_agents_hold_every_invariant(result):
    inv = result["invariants"]
    assert set(inv) == {"no_oversell", "one_order_per_idempotency_key", "orders_cite_verified_offers",
                        "no_order_without_authority", "approvals_by_named_humans", "audit_chain_verifies"}
    assert all(v["ok"] for v in inv.values()), {k: v for k, v in inv.items() if not v["ok"]}
    assert result["scores"]["determinism"] == 1.0
    assert result["scores"]["completionRate"] == 1.0, [r for r in result["runs"] if not r["completed"]]
    assert result["agents"] == 20 and {r["scenario"] for r in result["runs"]} >= set(agent_bench.SCENARIOS) - {"stale_offer"}
    assert any(r["scenario"] == "stale_offer" and r["requotes"] >= 1 for r in result["runs"])
    assert any(r["scenario"] == "out_of_order" and r["c409"] >= 1 for r in result["runs"])


def test_bench_report_lists_scores(result):
    md = agent_bench.report(result)
    for word in ("Completion rate", "409", "422", "p50", "p95", "Determinism", "No oversell", "Audit chain", "LLM agents"):
        assert word in md, word


def test_demo_clock_and_ops_records_need_credentials():
    c = TestClient(make_app(live=False))
    assert c.post("/v1/demo/clock", json={"advanceMinutes": 16}, headers=AGENT).status_code == 403
    assert c.post("/v1/demo/clock", json={"advanceMinutes": 16}, headers=OPS).json()["now"]
    assert c.get("/v1/ops/orders", headers=AGENT).status_code == 403
    assert c.get("/v1/ops/orders", headers=OPS).json()["orders"] == []
    inv = c.get("/v1/ops/inventory", headers=OPS).json()["inventory"]
    assert inv and all("schedule" in v for v in inv.values())


def test_bench_on_a_seeded_demo_counts_only_its_own_orders(monkeypatch):
    """make bench runs against `make run`, whose reset re-seeds the demo orders: they are not the bench's."""
    monkeypatch.setenv("AIMO_SEED_DEMO", "1")
    c = TestClient(make_app(live=False))
    res = agent_bench.bench(agent_bench.local_transport(c), agents=6)
    assert all(v["ok"] for v in res["invariants"].values()), {k: v for k, v in res["invariants"].items() if not v["ok"]}
