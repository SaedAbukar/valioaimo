"""Opt-in: the brief's request against the REAL Valio Aimo mock API (needs AIMO_API_KEY in .env).

    AIMO_LIVE_TESTS=1 pytest tests/gateway/test_live_e2e.py
"""
import os
import time

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.skipif(os.environ.get("AIMO_LIVE_TESTS") != "1", reason="set AIMO_LIVE_TESTS=1 to call the mock API")

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402
from tests.gateway.test_challenge import AGENT, BRIEF, run_agent  # noqa: E402


def test_brief_request_on_the_live_mock_api_under_a_minute():
    c = TestClient(make_app(live=True))
    assert c.get("/health").json()["liveApi"]["reachable"]
    t0 = time.perf_counter()
    found = c.post("/v1/products/search", json={"query": "lactose-free milk", "qty": 1000}, headers=AGENT).json()
    assert found["live"] and found["products"][0]["price"]["source"] == "valio-aimo-mock-api"
    sid, order, _ = run_agent(c, BRIEF)
    assert time.perf_counter() - t0 < 60
    plan = c.get(f"/v1/sessions/{sid}", headers=AGENT).json()["outputs"]["plan"]
    assert all(o["priceSource"] == "valio-aimo-mock-api" for o in plan["offers"])
    assert order["status"] == "ordered" and c.get(f"/v1/orders/{order['orderId']}", headers=AGENT).json()["confirmationVerified"]
