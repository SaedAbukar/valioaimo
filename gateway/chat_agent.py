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
    "Follow the gateway's playbook: call start_session once, then parse_request with the chef's words, then only tools "
    "listed in next_allowed_tools (recall, request_offers only for gaps, plan_basket, check_basket, render_cards). "
    "Any number of guests is fine; never refuse a request because of its size.\n"
    "PRODUCT LISTS: the gateway understands events only for dishes it has recipes for (for example salmon starter, beef "
    "tenderloin, chocolate mousse, lohikeitto, kinkku, rosolli, meatballs, chicken curry, caesar salad). For anything else "
    "(pizza, tacos, a BBQ, 'products for ...'), work out the ingredients yourself and call parse_request with a plain "
    "product list with one amount per product sized to the guests, and a concrete date, e.g. 'I need 12 kg vegan cheese, "
    "15 L tomato passata, 8 L oat cooking base and 20 kg flour by tomorrow'. Diets (vegan, gluten-free, nut-free) go into "
    "the product names. Do not use event words then. Call recall before any search; request_offers fetches the gaps.\n"
    "ASK, NEVER ASSUME: after parse_request, look at its 'missing' list and at anything else you would have to guess "
    "(how many guests, which day, which dishes or products, diets). Do not fill gaps yourself and do not call ask_user. "
    "Stop and ask the chef in one short message: a question per missing fact, at most three. You may suggest options "
    "(for a pizza party: 'cheese, passata, flour, toppings?'), but wait for their answer. When they answer, call "
    "parse_request again with the whole request in their words plus the answers, and carry on.\n"
    "CONFIRM FIRST: after check_basket and render_cards, do NOT order yet. Stop and reply to the chef in 2-4 short "
    "sentences: what you understood (event, guests, date, diets), the products you recommend from plan_basket (the main "
    "ones, with amounts), the total, and whether it needs an OK and from whom. Ask them to confirm or say what to change. "
    "Write plain text for a chef: short sentences, no markdown, no asterisks, at most three short questions.\n"
    "When the chef confirms, act: if place_order is allowed, cite exactly the offerIds from the latest plan_basket. If "
    "request_approval is allowed instead, call it, then call wait_for_update (timeoutSeconds 20, after = the last "
    "'next') until an approval.decided event arrives; if approved, call place_order; if declined, stop.\n"
    "When the chef's message starts with EDIT followed by JSON, call plan_basket with lineEdits set to exactly that JSON, "
    "then check_basket and render_cards, and propose again. "
    "When the chef asks for a change, call parse_request with the change in their words (for example 'now 250 guests') "
    "or plan_basket with choices, re-check, and propose again. "
    "If a call is refused, follow its fix or next_allowed_tools. Never invent or negotiate prices. "
    "After ordering, finish with two or three plain sentences: what was ordered, the total, delivery, who approved.")


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
        self.messages: list[dict] = [{"role": "user", "content": text}]
        self.tools: list[dict] | None = None
        self.ordered = False
        self.cond = threading.Condition()
        self.at = round(time.time(), 3)

    def record(self) -> dict:
        """What is saved so the chat shows up again after a reload or a restart (and can be continued)."""
        def msg(m):
            c = m["content"]
            return {"role": m["role"], "content": c if isinstance(c, str) else [_param(b) for b in c]}
        return {"id": self.id, "buyerId": self.buyer_id, "title": " ".join(self.text.split())[:60], "text": self.text,
                "status": self.status, "at": self.at, "events": list(self.events),
                "messages": [msg(m) for m in self.messages], "ordered": self.ordered}

    @classmethod
    def restore(cls, rec: dict) -> "Run":
        run = cls(rec["buyerId"], rec["text"])
        run.id, run.at, run.events, run.messages = rec["id"], rec.get("at", run.at), list(rec["events"]), rec.get("messages") or run.messages
        run.ordered = rec.get("ordered", False)
        run.status = rec["status"] if rec["status"] != "running" else "stopped"  # a run cut off by a restart
        return run

    def emit(self, type_: str, **data):
        with self.cond:
            self.events.append({"seq": len(self.events) + 1, "type": type_, "at": round(time.time(), 3), **data})
            if type_ in ("done", "stopped", "error"):
                self.status = type_
            if type_ in ("proposal", "question"):
                self.status = "waiting_user"  # the chef confirms or changes it
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
        self.on_change: Callable | None = None  # saves a run (set by the app)

    def get(self, rid: str, saved: dict | None = None) -> Run | None:
        """A run in memory, or one saved earlier (brought back so the chat can continue)."""
        if rid not in self.runs and saved and rid in saved:
            self.runs[rid] = Run.restore(saved[rid])
        return self.runs.get(rid)

    def _saved(self, run: Run):
        if self.on_change:
            try:
                self.on_change(run)
            except Exception:  # noqa: BLE001 - saving never breaks the chat
                pass

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

    def reply(self, run: Run, token: str, text: str):
        """The chef answers a proposal ('yes, order it' or a change): the same conversation continues."""
        run.messages.append({"role": "user", "content": text})
        run.emit("user", text=text)
        with run.cond:
            run.status = "running"
        threading.Thread(target=self._safe, args=(run, token), daemon=True).start()

    def _safe(self, run: Run, token: str):
        self._saved(run)
        try:
            self._loop(run, token)
        except Exception as e:  # noqa: BLE001 - the error class only: never a key, URL or prompt
            run.emit("error", reason=f"The agent stopped: {type(e).__name__}.")
        finally:
            self._saved(run)

    def _loop(self, run: Run, token: str):
        if run.tools is None:
            run.tools = [{"name": t["name"], "description": (t.get("description") or "")[:1000], "input_schema": t["inputSchema"]}
                         for t in self._mcp(token, "tools/list", {})["tools"] if t["name"] not in HIDDEN]
            run.emit("start", model=model(), tools=len(run.tools), via="MCP (Streamable HTTP) as the buyer's agent")
        tools, messages = run.tools, run.messages
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
                answer = "\n".join(texts) or "Done."
                if run.ordered:
                    run.emit("done", answer=answer)
                else:
                    brief = next((e.get("brief") for e in reversed(run.events) if e["type"] == "tool_result" and e["name"] == "parse_request" and e.get("ok")), None)
                    planned = any(e["type"] == "tool_result" and e["name"] == "plan_basket" and e.get("ok") and
                                  e["seq"] > max((x["seq"] for x in run.events if x["type"] == "tool_result" and x["name"] == "parse_request"), default=0)
                                  for e in run.events)
                    if not planned:  # nothing planned since the last request: the agent is asking for what is missing
                        run.emit("question", answer=answer, missing=(brief or {}).get("missing", []), brief=brief)
                        return
                    plan = next((e for e in reversed(run.events) if e["type"] == "tool_result" and e["name"] == "plan_basket" and e.get("ok")), None)
                    chk = next((e for e in reversed(run.events) if e["type"] == "tool_result" and e["name"] == "check_basket" and e.get("ok")), None)
                    run.emit("proposal", answer=answer, plan=plan and plan.get("plan"), decision=chk and chk.get("decision"),
                             reasons=chk and chk.get("reasons"))
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
        if name == "parse_request":
            out_b = out or {}
            extra["brief"] = {"missing": out_b.get("missing", []), "complete": out_b.get("complete"),
                              "guests": (out_b.get("event") or {}).get("guests"), "when": (out_b.get("when") or {}).get("value"),
                              "what": (out_b.get("what") or {}).get("value")}
        if name == "plan_basket":
            extra["plan"] = {"total": out.get("total"), "perGuest": out.get("perGuest"),
                             "lines": [{k: l.get(k) for k in ("productId", "name", "qty", "unit", "unitPrice", "lineTotal", "deliveryDate", "why", "source")}
                                       for l in out.get("lines", [])],
                             "cantDo": [{"need": c.get("need"), "allergen": c.get("allergen"),
                                         "alternative": (c.get("alternative") or {}).get("name")} for c in out.get("cantDo", [])]}
        if name == "check_basket":
            extra.update(decision=out.get("decision"), reasons=out.get("reasons"), approver=(out.get("approver") or {}).get("name"))
        if name == "place_order":
            run.ordered = True
            extra.update(orderId=out.get("orderId"), total=out.get("total"), approvedBy=out.get("approvedBy"),
                         lines=[{k: l.get(k) for k in ("name", "qty", "unit", "unitPrice", "lineTotal", "deliveryDate")}
                                for l in out.get("lines", [])],
                         deliveries=[{"label": x.get("label"), "window": x.get("window")} for x in out.get("deliveries", [])])
        if name == "wait_for_update":
            summary = ", ".join(e["type"] for e in d.get("events", [])) or "no news yet"
        else:
            summary = _summary(name, out) if d.get("tool") else f"{name} done"
        run.emit("tool_result", name=name, ok=True, summary=summary, next=d.get("next_allowed_tools"), **extra)
        if name == "request_approval":
            ap = out.get("approval", {})
            run.emit("waiting_for_ok", approvalId=ap.get("approvalId"), approver=ap.get("approver", {}).get("name"),
                     total=ap.get("total"), reasons=ap.get("reasons", []))
