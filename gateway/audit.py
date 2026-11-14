"""Append-only, hash-chained audit ledger (written by the gateway, never by the agent).

hash_n = SHA-256(canonical(event_n without "hash", with prevHash = hash_{n-1})).
Editing any stored row breaks verification at that row (tamper evidence).
"""
from __future__ import annotations

import json

from .util import canonical, new_id, sha256_hex

GENESIS = "0" * 64

ACTION_TEXT = {
    "search": "searched the catalog",
    "quote": "received signed offers",
    "plan": "built fulfilment plans",
    "candidates_filtered": "filtered out unsuitable products",
    "policy_decision": "policy engine decided",
    "approval_requested": "requested human approval",
    "approved": "approved",
    "rejected": "rejected",
    "modified": "modified and approved",
    "partially_approved": "partially approved",
    "order_placed": "placed the order",
    "notified": "notified the buyer",
    "substitution_proposed": "proposed a substitution",
    "offer_expired": "found an expired offer",
    "price_changed": "detected a price change",
    "requote": "re-quoted offers",
    "checkout_created": "opened a checkout session",
    "checkout_blocked": "blocked the checkout",
    "mandate_registered": "registered a signed Intent Mandate",
    "mandate_updated": "updated the Intent Mandate",
    "preferences_updated": "updated the preference profile",
    "manual_choice": "chose a different product",
    "kill_switch": "changed the agent kill switch",
    "standing_order_paused": "paused standing-order auto-renew",
    "event_planned": "planned an event",
    "reconciliation_recorded": "recorded consumption",
    "delivery_feedback": "recorded delivery feedback",
    "data_deleted": "deleted buyer data",
    "data_exported": "exported buyer data",
}


def event_hash(ev: dict) -> str:
    body = {k: v for k, v in ev.items() if k != "hash"}
    return sha256_hex(canonical(body))


class AuditLedger:
    def __init__(self, store, clock):
        self.store = store
        self.clock = clock
        self._verified = (0, GENESIS)  # (seq, hash) of the verified prefix

    def _last_hash(self) -> str:
        row = self.store.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS

    def append(self, *, trace_id: str | None, actor: str, action: str, buyer_id: str | None = None,
               inputs: dict | None = None, refs: dict | None = None, decision: str | None = None,
               rule_ids: list[str] | None = None, reason: str = "", ts: str | None = None) -> dict:
        from .util import iso
        with self.store.lock:
            seq = (self.store.db.execute("SELECT COALESCE(MAX(seq),0) FROM audit").fetchone()[0]) + 1
            ev = {
                "seq": seq,
                "eventId": new_id("EV"),
                "ts": ts or iso(self.clock.now()),
                "traceId": trace_id,
                "buyerId": buyer_id,
                "actor": actor,
                "action": action,
                "inputs": inputs or {},
                "refs": refs or {},
                "decision": decision,
                "ruleIds": rule_ids or [],
                "reason": reason,
                "prevHash": self._last_hash(),
            }
            ev["hash"] = event_hash(ev)
            self.store.db.execute(
                "INSERT INTO audit(seq,event_id,ts,trace_id,buyer,json,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)",
                (seq, ev["eventId"], ev["ts"], trace_id, buyer_id, json.dumps(ev, ensure_ascii=False),
                 ev["prevHash"], ev["hash"]))
            self.store.db.commit()
        return ev

    def events(self, trace_id: str | None = None, buyer_id: str | None = None, limit: int = 500) -> list[dict]:
        q, args = "SELECT json FROM audit", []
        conds = []
        if trace_id:
            conds.append("trace_id=?"); args.append(trace_id)
        if buyer_id:
            conds.append("buyer=?"); args.append(buyer_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY seq DESC LIMIT ?"
        args.append(limit)
        with self.store.lock:
            rows = self.store.db.execute(q, args).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def rejections(self) -> list[dict]:
        """Only the refused calls (rejected.*), filtered in SQL rather than by parsing every event."""
        with self.store.lock:
            rows = self.store.db.execute("SELECT json FROM audit WHERE json LIKE '%\"action\": \"rejected.%' ORDER BY seq").fetchall()
        return [json.loads(r[0]) for r in rows]

    def events_for(self, caller, trace_id: str | None = None, limit: int = 300) -> list[dict]:
        """A buyer's credentials see their own trail; Valio Aimo operations see every buyer."""
        return self.events(trace_id=trace_id, buyer_id=None if caller.kind == "ops" else caller.buyer_id, limit=limit)

    def verify(self, full: bool = False) -> dict:
        """Check the hash chain. Incremental by default: only events after the last verified one are hashed, and the
        last verified event is re-read to make sure it still links. full=True re-checks every event from genesis."""
        start, prev = (0, GENESIS) if full else self._verified
        with self.store.lock:
            if start:
                row = self.store.db.execute("SELECT hash FROM audit WHERE seq=?", (start,)).fetchone()
                if not row or row[0] != prev:
                    start, prev = 0, GENESIS
            rows = self.store.db.execute("SELECT seq, json, hash FROM audit WHERE seq > ? ORDER BY seq", (start,)).fetchall()
        n = start
        for seq, js, stored_hash in rows:
            n += 1
            ev = json.loads(js)
            if ev.get("prevHash") != prev:
                return {"ok": False, "checked": n, "brokenAt": seq, "detail": f"event {seq}: prevHash does not link to event {seq - 1}"}
            if event_hash(ev) != stored_hash or ev.get("hash") != stored_hash:
                return {"ok": False, "checked": n, "brokenAt": seq, "detail": f"event {seq}: content does not match its SHA-256 hash (edited after write)"}
            prev = stored_hash
        self._verified = (n, prev)
        return {"ok": True, "checked": n, "newlyChecked": n - start, "brokenAt": None, "head": prev, "detail": f"{n} events, chain intact"}


def sentence(ev: dict) -> str:
    """Human-readable timeline sentence (templated, never free LLM text)."""
    actor = ev["actor"]
    who = actor.split(":", 1)[1] if ":" in actor else actor
    kind = actor.split(":", 1)[0]
    who_label = {"agent": f"Agent {who}", "human": who, "system": "Gateway policy" if who == "policy" else "Gateway"}.get(kind, who)
    verb = ACTION_TEXT.get(ev["action"], ev["action"].replace("_", " "))
    s = f"{who_label} {verb}"
    if ev.get("decision"):
        s += f": {ev['decision']}"
    if ev.get("reason"):
        s += f" — {ev['reason']}"
    return s
