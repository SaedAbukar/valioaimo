"""Who may see or touch what: one place for REST and MCP (so the two channels cannot drift).

Rules: an agent acts only in its own sessions (same buyer AND same agent); agents, approvers and users
read only their own buyer's offers, orders and analyses; Valio Aimo operations read across buyers.
"""
from __future__ import annotations

from .auth import AuthError, Caller, same_buyer


def own_session(gw, c: Caller, sid: str) -> dict:
    """The session if this caller may drive it; AuthError 403 otherwise (NotFound when it does not exist)."""
    s = gw.engine.session(sid)
    same_buyer(c, s["buyerId"])
    if c.kind == "agent" and c.agent_id != s["agentId"]:
        raise AuthError(403, "forbidden", "This session belongs to another agent.")
    return s


def can_read_order(gw, c: Caller, order: dict | None) -> bool:
    if not order:
        return False
    s = gw.engine.sessions.get(order["sessionId"])
    return bool(s) and (c.kind == "ops" or c.buyer_id == s["buyerId"])


def can_read_offer(c: Caller, offer: dict | None) -> bool:
    return bool(offer) and (c.kind == "ops" or c.buyer_id == offer.get("buyerId"))


def can_read_analysis(c: Caller, analysis: dict | None) -> bool:
    return bool(analysis) and (c.kind == "ops" or c.buyer_id == analysis["buyerId"])
