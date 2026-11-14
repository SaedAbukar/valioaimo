"""Push updates for agents: a per-session event log with long-poll.

After request_approval an agent need not poll the session: GET /v1/sessions/{id}/events?after=N&wait=25
(or the MCP tool wait_for_update) blocks until something happens, then returns the new events and
the cursor for the next call. Events: step.completed, decision.made, approval.requested,
approval.decided, order.placed, offer.expiring (2 min before an offer's validUntil, emitted when read)
and suggestion.created. Outbound webhooks are out of scope for the prototype (docs/ASSUMPTIONS.md).
"""
from __future__ import annotations

import threading
from datetime import timedelta

from .util import iso, parse_dt

MAX_WAIT = 25
EXPIRING_BEFORE = timedelta(minutes=2)


class Events:
    def __init__(self, gw):
        self.gw = gw
        self.log: dict[str, list[dict]] = {}
        self.cond = threading.Condition()

    def emit(self, session_id: str, type_: str, data: dict | None = None) -> dict:
        with self.cond:
            evs = self.log.setdefault(session_id, [])
            e = {"seq": len(evs) + 1, "type": type_, "at": iso(self.gw.clock.now()), "sessionId": session_id, "data": data or {}}
            evs.append(e)
            self.cond.notify_all()
            return e

    def emit_buyer(self, buyer_id: str, type_: str, data: dict) -> int:
        """Emit to every open session of a buyer (e.g. a seller suggestion). Returns how many sessions were told."""
        n = 0
        for s in list(self.gw.engine.sessions.values()):
            if s["buyerId"] == buyer_id:
                self.emit(s["sessionId"], type_, data)
                n += 1
        return n

    def _expiring(self, session_id: str):
        """Lazily add offer.expiring once per offer when it is within 2 minutes of validUntil."""
        s = self.gw.engine.sessions.get(session_id)
        if not s or not (s["data"].get("plan")) or s["data"].get("order"):
            return
        now = self.gw.clock.now()
        told = {e["data"].get("offerId") for e in self.log.get(session_id, []) if e["type"] == "offer.expiring"}
        for o in s["data"]["plan"].get("offers", []):
            left = parse_dt(o["validUntil"]) - now
            if o["offerId"] not in told and left <= EXPIRING_BEFORE:
                self.emit(session_id, "offer.expiring", {"offerId": o["offerId"], "validUntil": o["validUntil"],
                                                         "secondsLeft": max(0, int(left.total_seconds())),
                                                         "next_allowed_tools": ["plan_basket"]})

    def read(self, session_id: str, after: int = 0) -> list[dict]:
        with self.cond:
            self._expiring(session_id)
            return [e for e in self.log.get(session_id, []) if e["seq"] > after]

    def wait(self, session_id: str, after: int = 0, timeout: float = 0) -> list[dict]:
        """Block up to timeout seconds (max 25) until an event after `after` exists."""
        timeout = max(0.0, min(float(timeout), MAX_WAIT))
        with self.cond:
            self._expiring(session_id)
            self.cond.wait_for(lambda: len(self.log.get(session_id, [])) > after, timeout=timeout)
            return [e for e in self.log.get(session_id, []) if e["seq"] > after]

    def cursor(self, session_id: str) -> int:
        return len(self.log.get(session_id, []))
