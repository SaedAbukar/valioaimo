"""Who is calling: agents, the humans who approve, and Valio Aimo operations.

Every agent-facing call carries `Authorization: Bearer <token>`. A token is bound
to ONE customer account (buyerId), so an agent can only act for the buyer that
registered it, and only within that buyer's signed mandate.

Three kinds of caller, three different powers:
  agent  - look up, quote, plan, order within authority, ask for approval.
           Can never approve. Bound to buyerId + agentId.
  human  - a named approver of one buyer. Can approve or decline, nothing else.
  ops    - Valio Aimo operations. Reads every audit log, can pause an agent.

Demo credentials (synthetic, safe to publish): the agent's `apiKey` in
gateway/data/buyers.json, `demo-human-<personId>` for approvers and `demo-ops`.
Production: OAuth 2.1 client credentials per agent (the MCP authorization spec),
approvers through the buyer's own SSO. See docs/EXPOSURE.md.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    kind: str  # agent | human | ops
    buyer_id: str | None = None
    agent_id: str | None = None
    person_id: str | None = None
    name: str = ""
    role: str = ""

    @property
    def label(self) -> str:
        return {"agent": f"agent:{(self.agent_id or '').split(':')[-1]}", "human": f"human:{self.name}",
                "ops": "ops:valio-aimo"}[self.kind]


OPS_TOKEN = "demo-ops"


class AuthError(Exception):
    def __init__(self, status: int, error: str, message: str):
        super().__init__(message)
        self.status, self.error, self.message = status, error, message

    def body(self) -> dict:
        return {"error": self.error, "message": self.message}


def human_token(person_id: str) -> str:
    return f"demo-human-{person_id}"


def registry(gw) -> dict[str, Caller]:
    out = {OPS_TOKEN: Caller("ops", name="Valio Aimo operations")}
    for bid, b in gw.buyers.items():
        for a in b["agents"]:
            out[a["apiKey"]] = Caller("agent", bid, agent_id=a["id"], name=a["name"])
        for p in b["approvers"]:
            out[human_token(p["id"])] = Caller("human", bid, person_id=p["id"], name=p["name"], role=p["role"])
    return out


def resolve(gw, header: str | None) -> Caller | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    return registry(gw).get(header.split(None, 1)[1].strip())


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
