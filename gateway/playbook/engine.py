"""Playbook state machine: which tool may run now, schema-checked outputs, audit per call.

Any agent (Claude, GPT, Gemini, a script, the built-in chef assistant) drives a
session through the same calls. Out-of-order calls raise StepNotAllowed, which
the HTTP and MCP facades turn into `409 step_not_allowed` + next_allowed_tools.
"""
from __future__ import annotations

import copy
import time
from functools import lru_cache
from pathlib import Path

import jsonschema
import yaml

from ..util import iso, new_id

PLAYBOOK_FILE = Path(__file__).resolve().parent / "order_playbook.v1.yaml"
HUMAN_TOOLS = {"decide_approval"}


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
            if ready and dec == "needs_ok":
                out.append("request_approval")
            out += ["plan_basket", "parse_request"]
        elif step == "act":
            appr = d.get("approval")
            if appr and appr["status"] == "approved" and not appr.get("used"):
                out.append("place_order")
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

    def call(self, sid: str | None, tool: str, args: dict | None = None, actor: str | None = None) -> dict:
        args = args or {}
        pb = playbook()
        s = self.sessions.get(sid) if sid else None
        if sid and not s:
            raise NotFound(f"no session {sid}")
        if tool in ("get_session", "get_playbook") and s:
            return {"tool": tool, "output": self.view(s) if tool == "get_session" else public_playbook(),
                    "next_allowed_tools": self.allowed(s)}
        if tool not in pb["toolStep"]:
            raise NotFound(f"unknown tool {tool}", known=sorted(pb["toolStep"]))
        allowed = self.allowed(s)
        if tool not in allowed:
            raise StepNotAllowed(f"'{tool}' is not allowed at step '{s['step'] if s else 'none'}'.",
                                 step=s["step"] if s else None, next_allowed_tools=allowed,
                                 playbookVersion=pb["version"])
        step_id = pb["toolStep"][tool]
        t0 = time.perf_counter()
        if tool == "start_session":
            out = self.tools.start_session(self.gw, args)
            s = self._new(out, args)
        else:
            if step_id in ("understand", "plan") and pb["byId"][step_id]["n"] < pb["byId"][s["step"]]["n"]:
                self._rewind(s, step_id)
            out = getattr(self.tools, tool)(self.gw, s, args)
        step = pb["byId"][step_id]
        exit_tool = step.get("exit_tool")
        if step.get("output") and (exit_tool is None or exit_tool == tool) and tool != "ask_user":
            validate(step["output"], out)
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
        return {"tool": tool, "step": step_id, "output": out, "next_allowed_tools": self.allowed(s),
                "sessionId": s["sessionId"], "playbookVersion": pb["version"]}

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
        keep = {"choices", "alternatives", "acceptedTips", "ignoredTips", "brief", "order", "approval", "asked", "history"}
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
    if not isinstance(out, dict):
        return ""
    if tool == "parse_request":
        return f"brief {'complete' if out.get('complete') else 'missing ' + ','.join(out.get('missing', []))}"
    if tool == "recall":
        return f"{len(out['matched'])} matched, {len(out['gaps'])} gaps"
    if tool == "request_offers":
        return f"{len(out['gaps'])} gaps searched"
    if tool == "plan_basket":
        return f"{len(out['lines'])} lines, total {out['total']:.2f}"
    if tool == "check_basket":
        return out.get("decision", "")
    if tool == "render_cards":
        return ", ".join(c["type"] for c in out["cards"])
    if tool in ("place_order", "request_approval"):
        return out.get("status", "")
    if tool == "record_usage":
        return ", ".join(out.get("labels", []))
    return ""


def new_session_id() -> str:
    return new_id("SES")
