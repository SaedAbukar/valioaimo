"""The chat's Agent mode: a Claude agent that orders for the kitchen through the gateway's own MCP endpoint.

The agent gets the buyer's agent credential and talks to POST /mcp (Streamable HTTP, JSON-RPC), so every call
crosses the same interface any external MCP agent uses: the playbook rails, signed offers, the gateway's rules and
the named-human approval all apply unchanged. The model only chooses the next tool; the gateway decides outcomes.
There is no approve tool: when an OK is needed, Laura approves with her own credential and the agent is woken by
wait_for_update. Each run streams events to the chat (long-poll). The API key never leaves this process.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable

import logging

from .playbook.engine import _summary

LOG = logging.getLogger("aimo.gateway")
from .util import new_id

DEFAULT_MODEL = "claude-haiku-5-5"
MODELS = {"claude-haiku-5-5", "claude-sonnet-5-5"}
MAX_TOKENS = 4096
TOTAL_OUTPUT_TOKENS = 60000
HIDDEN = {"call_tool", "list_tools", "ask_insight", "get_insight_playbook", "start_analysis", "describe_data", "get_values",
          "run_query", "suggest_chart", "build_chart", "explain_result", "explain_change"}
SYSTEM = (
    "You are the purchasing agent of a professional kitchen, connected to Valio Aimo's agent gateway over MCP. "
    "Order what the chef asks for by following the gateway's playbook: call start_session, then parse_request with the "
    "chef's words, then only tools listed in next_allowed_tools (recall, request_offers only for gaps, plan_basket, "
    "check_basket, render_cards). If place_order is allowed, cite exactly the offerIds from plan_basket. "
    "If request_approval is allowed instead, call it, then call wait_for_update (timeoutSeconds 20, after = the last "
    "'next') until an approval.decided event arrives; if approved, call place_order; if declined, stop. "
    "If a call is refused, follow its fix or next_allowed_tools. Never invent or negotiate prices. "
    "Finish with two or three plain sentences for the chef: what was ordered, the total, delivery, and who approved.")


def key_set() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def model() -> str:
    m = os.environ.get("AIMO_AGENT_MODEL", DEFAULT_MODEL)
    return m if m in MODELS else DEFAULT_MODEL


def _param(b) -> dict:
    """A response block back as a request block (thinking blocks pass back unchanged)."""
    if isinstance(b, dict):
        return b
    if hasattr(b, "model_dump"):
        return b.model_dump(exclude_none=True)
    return {k: v for k, v in vars(b).items()}


class Run:
    def __init__(self, buyer_id: str, text: str):
        self.id, self.buyer_id, self.text = new_id("RUN"), buyer_id, text
        self.events: list[dict] = []
        self.status = "running"
        self.cond = threading.Condition()

    def emit(self, type_: str, **data):
        with self.cond:
            self.events.append({"seq": len(self.events) + 1, "type": type_, "at": round(time.time(), 3), **data})
            if type_ in ("done", "stopped", "error"):
                self.status = type_
            self.cond.notify_all()

    def wait(self, after: int, timeout: float) -> list[dict]:
        with self.cond:
            self.cond.wait_for(lambda: len(self.events) > after or self.status != "running", timeout=max(0, min(timeout, 25)))
            return self.events[after:]


class ChatAgent:
    """Runs agent conversations in background threads. `client` (anthropic.Anthropic) and `post` (one JSON-RPC
    message to /mcp) can be replaced, e.g. by tests."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.runs: dict[str, Run] = {}
        self.client = None
        self.post: Callable | None = None

    # ------------------------------------------------------------ plumbing
    def _client(self):
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic(max_retries=2, timeout=60.0)
        return self.client

    def _post(self, payload: dict, headers: dict):
        if self.post:
            return self.post(payload, headers)
        import httpx  # our own gateway's MCP endpoint (not a Valio Aimo system)
        return httpx.post(self.base_url + "/mcp", json=payload, headers=headers, timeout=40.0)

    def _mcp(self, token: str, method: str, params: dict) -> dict:
        r = self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                       {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "MCP error"))
        return body["result"]

    def available(self) -> dict:
        ok = key_set() or self.client is not None  # a key, or an injected client (tests)
        return {"available": ok, "model": model(),
                "reason": None if ok else "Set ANTHROPIC_API_KEY in .env to let a Claude agent order through the gateway's MCP."}

    # ------------------------------------------------------------ a run
    def start(self, buyer_id: str, token: str, text: str) -> Run:
        run = Run(buyer_id, text)
        self.runs[run.id] = run
        threading.Thread(target=self._safe, args=(run, token), daemon=True).start()
        return run

    def _safe(self, run: Run, token: str):
        try:
            self._loop(run, token)
        except Exception as e:  # noqa: BLE001 - the error class only: never a key, URL or prompt
            run.emit("error", reason=f"The agent stopped: {type(e).__name__}.")

    def _loop(self, run: Run, token: str):
        tools = [{"name": t["name"], "description": (t.get("description") or "")[:1000], "input_schema": t["inputSchema"]}
                 for t in self._mcp(token, "tools/list", {})["tools"] if t["name"] not in HIDDEN]
        run.emit("start", model=model(), tools=len(tools), via="MCP (Streamable HTTP) as the buyer's agent")
        messages = [{"role": "user", "content": run.text}]
        max_steps = int(os.environ.get("AIMO_AGENT_MAX_STEPS", 25))
        spent = 0
        for _ in range(max_steps):
            resp = self._client().messages.create(model=model(), max_tokens=MAX_TOKENS, system=SYSTEM, tools=tools,
                                                  messages=messages)
            spent += getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0
            if resp.stop_reason == "refusal":
                run.emit("stopped", reason="The model declined this request.")
                return
            messages.append({"role": "assistant", "content": [_param(b) for b in resp.content]})
            texts = [b.text for b in resp.content if b.type == "text" and b.text.strip()]
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                run.emit("done", answer="\n".join(texts) or "Done.")
                return
            for t in texts:
                run.emit("text", text=t)
            results = []
            for u in uses:
                args = dict(u.input or {})
                run.emit("tool_call", name=u.name, args={k: v for k, v in args.items() if k != "sessionId"})
                LOG.info(json.dumps({"msg": "agent.tool_call", "runId": run.id, "buyerId": run.buyer_id, "tool": u.name,
                                     "args": {k: v for k, v in args.items() if k != "text"}}, default=str))
                res = self._mcp(token, "tools/call", {"name": u.name, "arguments": args})
                text = "".join(c.get("text", "") for c in res.get("content", []))
                self._report(run, u.name, text, bool(res.get("isError")))
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": text[:12000], "is_error": bool(res.get("isError"))})
            messages.append({"role": "user", "content": results})
            if spent > TOTAL_OUTPUT_TOKENS:
                run.emit("stopped", reason=f"Token budget reached ({TOTAL_OUTPUT_TOKENS:,} output tokens).")
                return
        run.emit("stopped", reason=f"Step limit reached ({max_steps} steps).")

    @staticmethod
    def _report(run: Run, name: str, text: str, is_error: bool):
        """One short line per result for the chat; refusals show the gateway's own message and fix."""
        try:
            d = json.loads(text)
        except ValueError:
            d = {}
        if is_error or "error" in d:
            run.emit("tool_result", name=name, ok=False, status=d.get("status"), summary=d.get("message") or d.get("error", "refused"),
                     guard=d.get("guard"), fix=d.get("fix"), next=d.get("next_allowed_tools"))
            return
        out = d.get("output") if isinstance(d.get("output"), dict) else d
        extra = {}
        if name == "start_session":
            extra["sessionId"] = d.get("sessionId")
        if name == "place_order":
            extra.update(orderId=out.get("orderId"), total=out.get("total"), approvedBy=out.get("approvedBy"))
        if name == "wait_for_update":
            summary = ", ".join(e["type"] for e in d.get("events", [])) or "no news yet"
        else:
            summary = _summary(name, out) if d.get("tool") else f"{name} done"
        run.emit("tool_result", name=name, ok=True, summary=summary, next=d.get("next_allowed_tools"), **extra)
        if name == "request_approval":
            ap = out.get("approval", {})
            run.emit("waiting_for_ok", approvalId=ap.get("approvalId"), approver=ap.get("approver", {}).get("name"),
                     total=ap.get("total"), reasons=ap.get("reasons", []))
