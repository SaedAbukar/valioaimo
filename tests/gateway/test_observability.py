"""Task 19 (audit H6, M7): rejected calls are audited; JSON request logs with request id and W3C traceparent;
raw operations metrics."""
import json
import logging
import os

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402

AGENT = {"Authorization": "Bearer demo-key-pohjola"}
OPS = {"Authorization": "Bearer demo-ops"}
OVER = "I need 3,000 litres of lactose-free milk by Monday."


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def to_approval(c):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    for t in ("parse_request", "recall", "plan_basket", "check_basket", "render_cards", "request_approval"):
        r = c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": OVER} if t == "parse_request" else {}, headers=AGENT)
    return sid, r.json()["output"]["approval"]["approvalId"]


def test_agent_approving_itself_is_audited_as_rejected(c):
    sid, aid = to_approval(c)
    assert c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=AGENT).status_code == 403
    ev = c.get("/v1/audit", headers=OPS).json()["events"]
    rej = [e for e in ev if e["action"].startswith("rejected.")]
    hit = next(e for e in rej if e["action"] == "rejected.approvals")
    assert hit["actor"] == "agent:pohjola-buyer-01" and hit["refs"]["status"] == 403 and hit["refs"]["error"] == "forbidden"
    assert hit["buyerId"] == "BUY-POHJOLA"
    assert c.get("/v1/audit", headers=OPS).json()["verify"]["ok"]


def test_out_of_order_and_bad_input_are_audited(c):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    c.post(f"/v1/sessions/{sid}/tools/place_order", json={}, headers=AGENT)
    c.post(f"/v1/sessions/{sid}/tools/parse_request", json={"txt": 1}, headers=AGENT)
    ev = c.get(f"/v1/audit?sessionId={sid}", headers=AGENT).json()["events"]
    got = {(e["action"], e["refs"]["status"], e["refs"].get("guard")) for e in ev if e["action"].startswith("rejected.")}
    assert ("rejected.place_order", 409, None) in got and ("rejected.parse_request", 422, "bad_input") in got


def test_request_log_is_json_with_request_id_and_traceparent(c, caplog):
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with caplog.at_level(logging.INFO, logger="aimo.gateway"):
        r = c.post("/v1/products/search", json={"query": "milk"}, headers={**AGENT, "traceparent": tp, "X-Request-Id": "req-42"})
    assert r.headers["X-Request-Id"] == "req-42" and r.headers["traceparent"].startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")
    line = json.loads([m for m in caplog.messages if "req-42" in m][-1])
    assert line["requestId"] == "req-42" and line["traceId"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert line["status"] == 200 and line["path"] == "/v1/products/search" and "ms" in line
    r2 = c.get("/v1/rules")
    assert len(r2.headers["X-Request-Id"]) >= 8 and r2.headers["traceparent"].count("-") == 3  # generated when absent


def test_session_id_is_in_the_log_line(c, caplog):
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    with caplog.at_level(logging.INFO, logger="aimo.gateway"):
        c.get(f"/v1/sessions/{sid}", headers=AGENT)
    assert json.loads(caplog.messages[-1])["sessionId"] == sid


def test_raw_metrics_are_ops_only_and_count_calls(c):
    to_approval(c)
    sid = c.post("/v1/sessions", json={}, headers=AGENT).json()["sessionId"]
    c.post(f"/v1/sessions/{sid}/tools/place_order", json={}, headers=AGENT)
    assert c.get("/v1/ops/metrics-raw", headers=AGENT).status_code == 403
    m = c.get("/v1/ops/metrics-raw", headers=OPS).json()
    assert m["toolCalls"]["check_basket"] >= 1 and m["decisions"]["needs_ok"] >= 1
    assert m["status"]["409"] >= 1 and 0 < m["rates"]["409"] < 1
    assert {"calls", "errors", "latencyMs", "breaker"} <= set(m["adapter"])
    assert "/v1/ops/metrics-raw" in c.get("/openapi.json").json()["paths"]
