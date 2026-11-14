"""Typed MCP tools generated from the playbooks' input schemas (playbook 1.1.0).

Each order and insight tool becomes an MCP tool with real, described parameters
(sessionId plus the fields of its JSON Schema), so a small model sees what to send
instead of guessing a JSON string. The gateway still validates every call against
the same schema (422 bad_input with fix.expected and fix.example). The generic
`call_tool(sessionId, tool, args_json)` stays as a fallback.
"""
from __future__ import annotations

import inspect
from typing import Annotated, Any, Callable

from pydantic import Field

TYPES = {"string": str, "number": float, "integer": int, "boolean": bool, "array": list, "object": dict}


def _py_type(p: dict):
    t = p.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    if t == "array":
        item = TYPES.get((p.get("items") or {}).get("type"), Any)
        return list[item]
    if t == "object":
        return dict[str, Any]
    return TYPES.get(t, Any)


def make_tool(name: str, schema: dict, call: Callable[[str, str, dict], str], doc: str, session: bool = True) -> Callable:
    """A function whose signature is sessionId + the schema's fields; calls call(sessionId, name, args)."""
    props, req = schema.get("properties", {}), set(schema.get("required", []))
    params = [inspect.Parameter("sessionId", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=Annotated[str, Field(description="The playbook session id from start_session.")])] if session else []
    ordered = sorted(props, key=lambda k: k not in req)
    for k in ordered:
        t = Annotated[_py_type(props[k]), Field(description=props[k].get("description", ""))]
        if k in req:
            params.append(inspect.Parameter(k, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=t))
        else:
            opt = Annotated[_py_type(props[k]) | None, Field(description=props[k].get("description", ""))]
            params.append(inspect.Parameter(k, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=opt, default=None))

    def fn(*a, **kw):
        bound = inspect.Signature(params).bind(*a, **kw)
        vals = dict(bound.arguments)
        sid = vals.pop("sessionId", None)
        return call(sid, name, {k: v for k, v in vals.items() if v is not None})

    fn.__name__ = name
    fn.__qualname__ = name
    fn.__signature__ = inspect.Signature(params, return_annotation=str)
    fn.__annotations__ = {p.name: p.annotation for p in params} | {"return": str}
    ex = (schema.get("examples") or [{}])
    fn.__doc__ = doc + (f" Example: {ex[-1]}" if ex[-1] else "")
    return fn


def register(mcp, order_pb: dict, insight_pb: dict, run: Callable, run_insight: Callable, skip: set[str]) -> dict[str, Callable]:
    """Register one typed MCP tool per order and insight tool (except names in skip). Returns name -> function."""
    done = {}
    for st in order_pb["steps"]:
        for t in st["tools"]:
            if t in skip:
                continue
            fn = make_tool(t, order_pb["inputs"][t], run, f"Order playbook step {st['n']} '{st['id']}': {st['does']}")
            mcp.tool(name=t, description=fn.__doc__)(fn)
            done[t] = fn
    for st in insight_pb["steps"]:
        for t in st["tools"]:
            if t in skip:
                continue
            fn = make_tool(t, insight_pb["inputs"][t], run_insight, f"Insight step {st['n']} '{st['id']}': {st['does']}")
            mcp.tool(name=t, description=fn.__doc__)(fn)
            done[t] = fn
    return done
