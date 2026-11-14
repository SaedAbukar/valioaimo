"""Playbook state machine: which tool may run now, schema-checked outputs, audit per call.

Any agent (Claude, GPT, Gemini, a script, the built-in chef assistant) drives a
session through the same calls. Out-of-order calls raise StepNotAllowed, which
the HTTP and MCP facades turn into `409 step_not_allowed` + next_allowed_tools.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import jsonschema
import yaml

from ..util import iso, new_id, parse_dt

PLAYBOOK_FILE = Path(__file__).resolve().parent / "order_playbook.v1.yaml"
HUMAN_TOOLS = {"decide_approval"}
IDEMPOTENT_TOOLS = {"place_order", "request_approval", "record_usage"}  # state-changing; read-only tools ignore the key
IDEMPOTENCY_TTL = timedelta(hours=24)


class PlaybookError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        return {"error": self.code, "message": self.message, **self.extra}


class StepNotAllowed(PlaybookError):
    status = 409
    code = "step_not_allowed"


class GuardFailed(PlaybookError):
    status = 422
    code = "guard_failed"


class NotFound(PlaybookError):
    status = 404
    code = "not_found"


@lru_cache(maxsize=1)
def playbook() -> dict:
    pb = yaml.safe_load(PLAYBOOK_FILE.read_text())
    pb["byId"] = {s["id"]: s for s in pb["steps"]}
    pb["toolStep"] = {t: s["id"] for s in pb["steps"] for t in s["tools"]}
    return pb


def public_playbook() -> dict:
    pb = copy.deepcopy(playbook())
    pb.pop("byId")
    pb.pop("toolStep")
    return pb


def _schema(name: str) -> dict:
    pb = playbook()
    s = copy.deepcopy(pb["schemas"][name])
    s["schemas"] = pb["schemas"]  # so "#/schemas/X" refs resolve
    return s


def _expected(schema: dict) -> dict:
    """A short, readable summary of an input schema: field -> 'type, required: description'."""
    req = set(schema.get("required", []))
    out = {}
    for k, p in schema.get("properties", {}).items():
        t = p.get("type") or ("one of " + "|".join(map(str, p["enum"])) if "enum" in p else "value")
        out[k] = f"{'|'.join(t) if isinstance(t, list) else t}{', required' if k in req else ''}: {p.get('description', '')}".rstrip(": ")
    return out


def validate_input(schema: dict | None, tool: str, args: dict):
    """Check a tool's input against its playbook schema; a mismatch is 422 bad_input with what is expected and an example."""
    if not schema:
        return
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(args))
    if not errors:
        return
    e = jsonschema.exceptions.best_match(errors)
    where = ".".join(str(p) for p in e.absolute_path)
    example = next((x for x in schema.get("examples", []) if x), (schema.get("examples") or [{}])[0])
    raise GuardFailed(f"{tool}: {(where + ': ') if where else ''}{e.message}", guard="bad_input",
                      fix={"expected": _expected(schema), "example": example})


def validate(name: str, output: dict):
    try:
        jsonschema.validate(output, _schema(name))
    except jsonschema.ValidationError as e:
        raise GuardFailed(f"{name} output does not match the playbook schema: {e.message}",
                          path=list(e.absolute_path))


class Engine:
    """Holds sessions for one gateway; tool handlers live in playbook/tools.py."""

    def __init__(self, gw):
        from . import tools
        self.gw = gw
        self.tools = tools
        self.sessions: dict[str, dict] = {}
        self.idem: dict[str, dict] = {}  # "scope|key" -> {hash, response, at}
        self.locks: dict[str, "threading.RLock"] = {}  # one lock per session: its calls run one at a time
        self._locks_guard = threading.Lock()

    def lock_for(self, sid: str):
        with self._locks_guard:
            return self.locks.setdefault(sid, threading.RLock())

    # ------------------------------------------------------------------ idempotency
    def idempotent(self, scope: str, key: str | None, args: dict, fn) -> tuple[dict, bool]:
        """Run fn once per (scope, key). A retry with the same body gets the stored response (replayed=True);
        the same key with a different body is 422 idempotency_conflict. Failures are not stored, so a retry
        after an error runs again."""
        if not key:
            return fn(), False
        h = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        k = f"{scope}|{key}"
        with self.gw.lock:
            hit = self.idem.get(k)
            if hit and self.gw.clock.now() - parse_dt(hit["at"]) < IDEMPOTENCY_TTL:
                if hit["hash"] != h:
                    raise GuardFailed("This Idempotency-Key was already used with a different request body.",
                                      guard="idempotency_conflict",
                                      fix={"idempotencyKey": "use a new key for a new request, or resend the original body"})
                return copy.deepcopy(hit["response"]), True
            out = fn()
            self.idem[k] = {"hash": h, "response": copy.deepcopy(out), "at": iso(self.gw.clock.now())}
            return out, False

    # ------------------------------------------------------------------ rules
    def allowed(self, s: dict | None) -> list[str]:
        if s is None:
            return ["start_session"]
        pb = playbook()
        d = s["data"]
        step = s["step"]
        out: list[str] = []
        if step == "receive":
            out = ["parse_request"]
        elif step == "understand":
            out = ["parse_request"]
            brief = d.get("brief")
            if brief and not brief["complete"] and not d.get("asked"):
                out.append("ask_user")
            if brief and brief["complete"]:
                out += pb["byId"]["recall"]["tools"]
        elif step == "recall":
            out = list(pb["byId"]["recall"]["tools"])
            if d.get("recall"):
                out = ["search_products", "get_product", "request_offers"] if d["recall"]["gaps"] else ["plan_basket"]
        elif step == "discover":
            out = ["search_products", "get_product", "request_offers"] + (["plan_basket"] if d.get("candidates") else [])
        elif step == "plan":
            out = ["plan_basket", "check_basket"]
        elif step == "check":
            out = ["render_cards"]
        elif step == "present":
            dec = (d.get("decision") or {}).get("decision")
            ready = d.get("plan") and not d["plan"].get("pendingChoices") and not d["plan"].get("cantDo")
            if ready and dec in ("auto", "tell_me"):
                out.append("place_order")
            appr = d.get("approval") or {}
            covered = appr.get("status") == "approved" and not appr.get("used") and \
                d["plan"]["total"] <= appr.get("total", 0) + 0.005  # a re-quote at the same or lower total keeps the OK
            if ready and dec == "needs_ok" and covered:
                out.append("place_order")
            elif ready and dec == "needs_ok":
                out.append("request_approval")
            out += ["plan_basket", "parse_request"]
        elif step == "act":
            appr = d.get("approval")
            if appr and appr["status"] == "approved" and not appr.get("used"):
                out.append("place_order")
            if not d.get("order"):  # an expired or changed offer before ordering: re-quote
                out.append("plan_basket")
            out += ["record_usage", "get_tips", "parse_request"]
        elif step == "learn":
            out = ["record_usage", "get_tips", "parse_request"]
        return list(dict.fromkeys(out)) + playbook()["always_allowed"]

    # ------------------------------------------------------------------ calls
    def session(self, sid: str) -> dict:
        s = self.sessions.get(sid)
        if not s:
            raise NotFound(f"no session {sid}")
        return s

    def call(self, sid: str | None, tool: str, args: dict | None = None, actor: str | None = None,
             idempotency_key: str | None = None) -> dict:
        args = dict(args or {})
        key = idempotency_key or args.pop("idempotencyKey", None)
        args.pop("idempotencyKey", None)
        if not sid:
            return self._call(sid, tool, args, actor)
        with self.lock_for(sid):
            if key and tool in IDEMPOTENT_TOOLS:
                out, replayed = self.idempotent(f"{sid}|{tool}", key, args, lambda: self._call(sid, tool, args, actor))
                return {**out, "idempotentReplay": True} if replayed else out
            return self._call(sid, tool, args, actor)

    def _call(self, sid: str | None, tool: str, args: dict, actor: str | None) -> dict:
        pb = playbook()
        s = self.sessions.get(sid) if sid else None
        if sid and not s:
            raise NotFound(f"no session {sid}")
        if tool in ("get_session", "get_playbook") and s:
            return {"tool": tool, "output": self.view(s) if tool == "get_session" else public_playbook(),
                    "next_allowed_tools": self.allowed(s)}
        if tool not in pb["toolStep"]:
            raise NotFound(f"unknown tool {tool}", known=sorted(pb["toolStep"]),
                           next_allowed_tools=self.allowed(s), fix={"tools": "GET /v1/playbook lists every tool and its input"})
        if s and self.gw.kill_switch.get(s["agentId"]):  # checked on every call, not only at start_session
            raise GuardFailed("This agent is paused by Valio Aimo operations; nothing more can run in this session.",
                              guard="agent_paused", next_allowed_tools=["get_session"],
                              fix={"contact": "Valio Aimo operations", "why": "kill switch (rule V3)"})
        allowed = self.allowed(s)
        if tool not in allowed:
            raise StepNotAllowed(f"'{tool}' is not allowed at step '{s['step'] if s else 'none'}'.",
                                 step=s["step"] if s else None, next_allowed_tools=allowed,
                                 playbookVersion=pb["version"])
        if tool == "place_order":
            self.tools.reject_negotiation(s, args)  # a price field is a negotiation attempt, not a typo
        validate_input(pb["inputs"].get(tool), tool, args)
        step_id = pb["toolStep"][tool]
        t0 = time.perf_counter()
        if tool == "start_session":
            out = self.tools.start_session(self.gw, args)
            s = self._new(out, args)
        else:
            snapshot = copy.deepcopy(s)  # the step is atomic: any failure (guard, schema, crash) leaves the session as it was
            try:
                if step_id in ("understand", "plan") and pb["byId"][step_id]["n"] < pb["byId"][s["step"]]["n"]:
                    self._rewind(s, step_id)
                out = getattr(self.tools, tool)(self.gw, s, args)
                self._check_output(pb, step_id, tool, out)
            except BaseException:
                s.clear()
                s.update(snapshot)
                raise
        step = pb["byId"][step_id]
        if tool == "start_session":
            self._check_output(pb, step_id, tool, out)
        if step.get("output") and (step.get("exit_tool") is None or step.get("exit_tool") == tool) and tool != "ask_user":
            s["outputs"][step_id] = out
        s["step"] = step_id
        s["toolCalls"] += 1
        ms = round((time.perf_counter() - t0) * 1000, 1)
        s["log"].append({"tool": tool, "step": step_id, "ms": ms, "at": iso(self.gw.clock.now())})
        self.gw.audit.append(trace_id=s["sessionId"], actor=actor or (f"system:gateway" if step.get("run_by") == "gateway" else f"agent:{s['agentId'].split(':')[-1]}"),
                             action=f"playbook.{tool}", buyer_id=s["buyerId"],
                             inputs=_trim(args), refs={"step": step_id, "n": step["n"], "playbookVersion": pb["version"], "ms": ms},
                             decision=(out.get("decision") if isinstance(out, dict) else None),
                             reason=_summary(tool, out))
        nxt = self.allowed(s)
        self._emit(s, tool, step_id, out, nxt)
        self.gw.save()
        return {"tool": tool, "step": step_id, "output": out, "next_allowed_tools": nxt,
                "sessionId": s["sessionId"], "playbookVersion": pb["version"]}

    def _emit(self, s: dict, tool: str, step_id: str, out: dict, nxt: list[str]):
        ev = self.gw.events
        sid = s["sessionId"]
        ev.emit(sid, "step.completed", {"tool": tool, "step": step_id, "next_allowed_tools": nxt})
        if tool == "start_session":  # the seller agent looks at this buyer; its open suggestions wake the new session
            from .. import seller
            seller.run(self.gw, s["buyerId"], notify=True)
            for sug in seller.open_for(self.gw, s["buyerId"]):
                if not any(e["type"] == "suggestion.created" and e["data"].get("suggestionId") == sug["suggestionId"]
                           for e in ev.log.get(sid, [])):
                    ev.emit(sid, "suggestion.created", seller.event_data(sug))
        if tool == "check_basket":
            ev.emit(sid, "decision.made", {"decision": out["decision"], "reasons": out["reasons"], "next_allowed_tools": nxt})
        elif tool == "request_approval":
            ap = out["approval"]
            ev.emit(sid, "approval.requested", {"approvalId": ap["approvalId"], "approver": ap["approver"]["name"], "total": ap["total"]})
        elif tool == "place_order":
            ev.emit(sid, "order.placed", {"orderId": out["orderId"], "total": out["total"], "backendOrderRef": out["backendOrderRef"]})

    @staticmethod
    def _check_output(pb: dict, step_id: str, tool: str, out: dict):
        step = pb["byId"][step_id]
        exit_tool = step.get("exit_tool")
        if step.get("output") and (exit_tool is None or exit_tool == tool) and tool != "ask_user":
            validate(step["output"], out)

    def _new(self, out: dict, args: dict) -> dict:
        s = {"sessionId": out["sessionId"], "buyerId": out["buyerId"], "agentId": out["agentId"],
             "playbookVersion": playbook()["version"], "createdAt": iso(self.gw.clock.now()), "step": "receive",
             "outputs": {"receive": out}, "data": {"choices": {}, "alternatives": {}, "acceptedTips": [], "ignoredTips": []},
             "toolCalls": 0, "log": [], "channel": args.get("channel", "api")}
        self.sessions[s["sessionId"]] = s
        return s

    def _rewind(self, s: dict, to_step: str):
        pb = playbook()
        n = pb["byId"][to_step]["n"]
        for st in pb["steps"]:
            if st["n"] >= n and st["id"] not in ("act", "learn"):
                s["outputs"].pop(st["id"], None)
        keep = {"choices", "alternatives", "acceptedTips", "ignoredTips", "brief", "order", "approval", "asked", "history",
                "suggestionCands", "suggestionLines", "acceptedSuggestions"}
        if to_step == "plan":
            keep |= {"recall", "candidates", "menu"}
        for k in list(s["data"]):
            if k not in keep:
                s["data"].pop(k)
        s["rewinds"] = s.get("rewinds", 0) + 1

    def view(self, s: dict) -> dict:
        return {k: s[k] for k in ("sessionId", "buyerId", "agentId", "playbookVersion", "createdAt", "step", "toolCalls", "log")} | {
            "outputs": s["outputs"], "next_allowed_tools": self.allowed(s)}


def _trim(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        out[k] = v[:280] if isinstance(v, str) else v
    return out


def _summary(tool: str, out: dict) -> str:
    """One plain sentence per call: the human-readable trail for the buyer and for Valio Aimo."""
    if not isinstance(out, dict):
        return f"{tool} done"
    if tool == "start_session":
        return f"session for {out.get('buyerId')} by {out.get('agentId')}, spending limit valid until {out.get('spendingLimitValidUntil')}"
    if tool == "parse_request":
        what = ", ".join(f"{l['qty']:g} {l['unit']} {l['text']}" for l in out.get("lines", []))
        return f"understood: {what or 'event'}" + ("" if out.get("complete") else f"; missing {', '.join(out.get('missing', []))}")
    if tool == "recall":
        return f"{len(out['matched'])} lines from the kitchen's own memory, {len(out['gaps'])} gaps to search"
    if tool == "request_offers":
        return f"{sum(len(g['candidates']) for g in out['gaps'])} signed offers for {len(out['gaps'])} gaps"
    if tool == "plan_basket":
        return f"{len(out['lines'])} lines, total {out['total']:.2f} EUR, on offers {', '.join(o['offerId'] for o in out.get('offers', []))}"
    if tool == "check_basket":
        return f"gateway decided {out.get('decision')}" + (f": {'; '.join(out['reasons'])}" if out.get("reasons") else ": within the agent's authority")
    if tool == "render_cards":
        return "shown as: " + ", ".join(c["type"] for c in out["cards"])
    if tool == "place_order":
        return f"ordered {out.get('orderId')} for {out.get('total', 0):.2f} EUR" + (f", approved by {out['approvedBy']}" if out.get("approvedBy") else "")
    if tool == "request_approval":
        ap = out.get("approval", {}).get("approver", {})
        return f"asked {ap.get('name')} for an OK"
    if tool == "record_usage":
        return "outcome saved: " + ", ".join(out.get("labels", []))
    return f"{tool} done"


def new_session_id() -> str:
    return new_id("SES")
