"""Push updates for agents: a per-session event log with long-poll.

After request_approval an agent need not poll the session: GET /v1/sessions/{id}/events?after=N&wait=25
(or the MCP tool wait_for_update) blocks until something happens, then returns the new events and
the cursor for the next call. Events: step.completed, decision.made, approval.requested,
approval.decided, order.placed, offer.expiring (2 min before an offer's validUntil, emitted when read)
and suggestion.created. Outbound webhooks are out of scope for the prototype (docs/ASSUMPTIONS.md).
"""
from __future__ import annotations

import os
import threading
from datetime import timedelta

from .util import iso, parse_dt

MAX_WAIT = 25
EXPIRING_BEFORE = timedelta(minutes=2)
KEEP = timedelta(hours=24)  # events older than this are dropped


class Busy(Exception):
    """Every long-poll slot is taken: answer 503 with Retry-After."""


class Events:
    def __init__(self, gw):
        self.gw = gw
        self.log: dict[str, list[dict]] = {}
        self.conds: dict[str, threading.Condition] = {}  # one per session: an emit wakes only that session's waiters
        self.guard = threading.Lock()
        self.max_waiters = int(os.environ.get("AIMO_MAX_WAITERS", 32))
        self.waiting = 0
        self.last_seq: dict[str, int] = {}  # seq keeps counting after old events are evicted

    def cond_for(self, session_id: str) -> threading.Condition:
        with self.guard:
            return self.conds.setdefault(session_id, threading.Condition())

    def emit(self, session_id: str, type_: str, data: dict | None = None) -> dict:
        cond = self.cond_for(session_id)
        with cond:
            evs = self.log.setdefault(session_id, [])
            now = self.gw.clock.now()
            evs[:] = [e for e in evs if now - parse_dt(e["at"]) < KEEP]  # evict old events; seq keeps counting
            e = {"seq": self._last(session_id, evs) + 1, "type": type_, "at": iso(now), "sessionId": session_id, "data": data or {}}
            evs.append(e)
            self.last_seq[session_id] = e["seq"]
            cond.notify_all()
            return e

    def _last(self, session_id: str, evs: list[dict]) -> int:
        return max(self.last_seq.get(session_id, 0), evs[-1]["seq"] if evs else 0)

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
        with self.cond_for(session_id):
            self._expiring(session_id)
            return [e for e in self.log.get(session_id, []) if e["seq"] > after]

    def wait(self, session_id: str, after: int = 0, timeout: float = 0) -> list[dict]:
        """Block up to timeout seconds (max 25) until an event after `after` exists. Raises Busy when all
        long-poll slots (AIMO_MAX_WAITERS, default 64) are taken; timeout 0 never takes a slot."""
        timeout = max(0.0, min(float(timeout), MAX_WAIT))
        if timeout <= 0:
            return self.read(session_id, after)
        with self.guard:
            if self.waiting >= self.max_waiters:
                raise Busy()
            self.waiting += 1
        try:
            self._expiring(session_id)
            cond = self.cond_for(session_id)
            with cond:
                cond.wait_for(lambda: any(e["seq"] > after for e in self.log.get(session_id, [])), timeout=timeout)
                return [e for e in self.log.get(session_id, []) if e["seq"] > after]
        finally:
            with self.guard:
                self.waiting -= 1
