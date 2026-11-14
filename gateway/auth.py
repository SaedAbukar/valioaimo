"""Who is calling: agents, the humans who approve, and Valio Aimo operations.

Every agent-facing call carries `Authorization: Bearer <token>`. A token is bound
to ONE customer account (buyerId), so an agent can only act for the buyer that
registered it, and only within that buyer's signed mandate.

Four kinds of caller, four different powers:
  agent  - look up, quote, plan, order within authority, ask for approval.
           Can never approve. Bound to buyerId + agentId.
  human  - a named approver of one buyer. Can approve or decline, nothing else.
  user   - a buyer's staff member in the chef app: chats with the built-in assistant, reads
           the buyer's board, history and insights. Cannot approve.
  ops    - Valio Aimo operations. Reads every audit log, can pause an agent.

Credentials: in demo mode (AIMO_DEMO=1, the default) the synthetic `demo-*` tokens below are
accepted. With AIMO_DEMO=0 they are refused and only tokens from AIMO_TOKENS_FILE (a JSON map
token -> {kind, buyerId, agentId | personId}) work. Tokens are compared with hmac.compare_digest.

Demo credentials (synthetic, safe to publish): the agent's `apiKey` in
gateway/data/buyers.json, `demo-human-<personId>` for approvers and `demo-ops`.
Production: OAuth 2.1 client credentials per agent (the MCP authorization spec),
approvers through the buyer's own SSO. See docs/EXPOSURE.md.
"""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    kind: str  # agent | human | user | ops
    buyer_id: str | None = None
    agent_id: str | None = None
    person_id: str | None = None
    name: str = ""
    role: str = ""

    @property
    def label(self) -> str:
        return {"agent": f"agent:{(self.agent_id or '').split(':')[-1]}", "human": f"human:{self.name}",
                "user": f"user:{self.name}", "ops": "ops:valio-aimo"}[self.kind]


OPS_TOKEN = "demo-ops"


class AuthError(Exception):
    def __init__(self, status: int, error: str, message: str):
        super().__init__(message)
        self.status, self.error, self.message = status, error, message

    def body(self) -> dict:
        return {"error": self.error, "message": self.message}


def human_token(person_id: str) -> str:
    return f"demo-human-{person_id}"


def user_token(buyer_id: str) -> str:
    return f"demo-user-{buyer_id.lower()}"


def demo_mode() -> bool:
    return os.environ.get("AIMO_DEMO", "1") == "1"


def _demo(gw) -> dict[str, Caller]:
    out = {OPS_TOKEN: Caller("ops", name="Valio Aimo operations")}
    for bid, b in gw.buyers.items():
        for a in b["agents"]:
            out[a["apiKey"]] = Caller("agent", bid, agent_id=a["id"], name=a["name"])
        for p in b["approvers"]:
            out[human_token(p["id"])] = Caller("human", bid, person_id=p["id"], name=p["name"], role=p["role"])
        out[user_token(bid)] = Caller("user", bid, name=f"{b['name']} kitchen")
    return out


_CACHE: dict = {}


def _configured(gw) -> dict[str, Caller]:
    path = os.environ.get("AIMO_TOKENS_FILE")
    if not path:
        return {}
    key = (path, os.stat(path).st_mtime_ns, id(gw))
    if _CACHE.get("configured", (None,))[0] == key:  # re-read only when the file changes
        return _CACHE["configured"][1]
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for tok, v in raw.items():
        bid = v.get("buyerId")
        b = gw.buyers.get(bid, {})
        name = v.get("name") or next((p["name"] for p in b.get("approvers", []) if p["id"] == v.get("personId")), "") or \
            next((a["name"] for a in b.get("agents", []) if a["id"] == v.get("agentId")), "")
        out[tok] = Caller(v["kind"], bid, agent_id=v.get("agentId"), person_id=v.get("personId"), name=name, role=v.get("role", ""))
    _CACHE["configured"] = (key, out)
    return out


def registry(gw) -> dict[str, Caller]:
    if demo_mode() and getattr(gw, "_demo_tokens", None) is None:
        gw._demo_tokens = _demo(gw)  # buyers, agents and approvers are fixed for a gateway's lifetime
    return {**(gw._demo_tokens if demo_mode() else {}), **_configured(gw)}


def resolve(gw, header: str | None) -> Caller | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    given = header.split(None, 1)[1].strip().encode() if " " in header.strip() else b""
    hit = None
    for tok, c in registry(gw).items():  # constant time per comparison; no early exit on a match
        if hmac.compare_digest(tok.encode(), given):
            hit = c
    return hit


def require(gw, header: str | None, *kinds: str) -> Caller:
    c = resolve(gw, header)
    if c is None:
        raise AuthError(401, "unauthorized", "Send 'Authorization: Bearer <token>' for a registered agent, approver or operator.")
    if kinds and c.kind not in kinds:
        raise AuthError(403, "forbidden", f"A {c.kind} credential cannot do this (needs {' or '.join(kinds)}).")
    return c


def same_buyer(c: Caller, buyer_id: str):
    if c.kind != "ops" and c.buyer_id != buyer_id:
        raise AuthError(403, "forbidden", "This credential belongs to another customer account.")
