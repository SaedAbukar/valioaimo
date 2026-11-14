"""Chat 'Agent' mode: a Claude agent (stubbed here) drives the gateway through its own /mcp endpoint."""
import json
import os
import threading
import time
from types import SimpleNamespace as NS

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.__main__ import make_app  # noqa: E402

USER = {"Authorization": "Bearer demo-user-buy-pohjola"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
AGENT = {"Authorization": "Bearer demo-key-pohjola"}
MILK = "I need 1,000 litres of lactose-free milk by Monday."
OVER = "I need 3,000 litres of lactose-free milk by Monday."


def use(name, **inp):
    return NS(type="tool_use", id=f"tu_{name}_{time.perf_counter_ns()}", name=name, input=inp)


def reply(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop, usage=NS(output_tokens=50))


def last_result(messages) -> dict:
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            return json.loads(m["content"][-1]["content"])
    return {}


class Scripted:
    """A stand-in for anthropic.Anthropic: plays a buyer agent that follows next_allowed_tools."""

    def __init__(self, text):
        self.text, self.sid, self.offers, self.after, self.tools = text, None, [], 0, None
        self.messages = NS(create=self.create)

    def create(self, **kw):
        self.tools = [t["name"] for t in kw["tools"]]
        r = last_result(kw["messages"])
        if not self.sid and not r:
            return reply(use("start_session"))
        if not self.sid:
            self.sid = r["sessionId"]
            return reply(use("parse_request", sessionId=self.sid, text=self.text))
        nxt = r.get("next_allowed_tools", [])
        if r.get("tool") == "plan_basket":
            self.offers = [o["offerId"] for o in r["output"]["offers"]]
        if r.get("tool") == "place_order":
            return reply(NS(type="text", text=f"Ordered {r['output']['orderId']}."), stop="end_turn")
        if r.get("tool") in ("request_approval", None) or "events" in r:  # waiting for the named human
            if "events" in r:
                self.after = r["next"]
                if any(e["type"] == "approval.decided" for e in r["events"]):
                    return reply(use("place_order", sessionId=self.sid, offerIds=self.offers))
            return reply(use("wait_for_update", sessionId=self.sid, after=self.after, timeoutSeconds=5))
        for t in ("recall", "check_basket", "render_cards", "place_order", "request_approval", "plan_basket"):
            if t in nxt and t != r.get("tool"):
                args = {"sessionId": self.sid}
                if t == "place_order":
                    args["offerIds"] = self.offers
                return reply(use(t, **args))
        return reply(NS(type="text", text="Stuck."), stop="end_turn")


def run_agent(c, client, text, approve=False):
    c.app.state.agent.client = client
    c.app.state.agent.post = lambda payload, headers: c.post("/mcp", json=payload, headers=headers)
    rid = c.post("/v1/agent/runs", json={"text": text}, headers=USER).json()["runId"]
    after, events, deadline = 0, [], time.time() + 30
    while time.time() < deadline:
        r = c.get(f"/v1/agent/runs/{rid}/events?after={after}&wait=2", headers=USER).json()
        events += r["events"]
        after = r["next"]
        if approve and any(e["type"] == "waiting_for_ok" for e in r["events"]):
            aid = next(e for e in r["events"] if e["type"] == "waiting_for_ok")["approvalId"]
            assert c.post(f"/v1/approvals/{aid}", json={"ok": True}, headers=LAURA).status_code == 200
        if r["status"] != "running":
            return r["status"], events
    return "timeout", events


def test_agent_orders_milk_through_mcp():
    with TestClient(make_app(live=False)) as c:
        status, ev = run_agent(c, Scripted(MILK), MILK)
        assert status == "done", ev[-3:]
        calls = [e["name"] for e in ev if e["type"] == "tool_call"]
        assert calls[:2] == ["start_session", "parse_request"] and calls[-1] == "place_order"
        assert ev[-1]["type"] == "done" and "Ordered ORD-" in ev[-1]["answer"]
        sid = next(e for e in ev if e["type"] == "tool_result" and e["name"] == "start_session")["sessionId"]
        assert c.app.state.gw().engine.sessions[sid]["channel"] == "mcp"  # it crossed the real MCP interface


def test_approval_wakes_the_agent_and_it_cannot_approve_itself():
    with TestClient(make_app(live=False)) as c:
        client = Scripted(OVER)
        status, ev = run_agent(c, client, OVER, approve=True)
        assert status == "done", ev[-3:]
        assert any(e["type"] == "waiting_for_ok" and e["approver"] == "Laura Virtanen" for e in ev)
        order = next(e for e in ev if e["type"] == "tool_result" and e["name"] == "place_order")
        assert order["approvedBy"] == "Laura Virtanen"
        assert not [t for t in client.tools if "approv" in t and t != "request_approval"]  # no approve tool for the model
        assert c.post("/v1/agent/runs", json={"text": OVER}, headers=AGENT).status_code == 403  # agents don't use the chef app


def test_step_cap_stops_a_looping_agent(monkeypatch):
    monkeypatch.setenv("AIMO_AGENT_MAX_STEPS", "4")
    loop = NS(messages=NS(create=lambda **kw: reply(use("get_rules"))))
    with TestClient(make_app(live=False)) as c:
        status, ev = run_agent(c, loop, MILK)
        assert status == "stopped" and ev[-1]["type"] == "stopped" and "4 steps" in ev[-1]["reason"]
        assert len([e for e in ev if e["type"] == "tool_call"]) == 4


def test_status_says_why_when_there_is_no_key(monkeypatch):
    c = TestClient(make_app(live=False))
    s = c.get("/v1/agent/status", headers=USER).json()
    assert s["available"] is False and s["reason"]
    assert c.post("/v1/agent/runs", json={"text": MILK}, headers=USER).status_code == 503
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-SECRET-123")
    r = c.get("/v1/agent/status", headers=USER)
    assert r.json()["available"] is True and r.json()["model"] == "claude-haiku-5-5" and "SECRET" not in r.text
