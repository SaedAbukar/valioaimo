"""State that survives a restart: sessions, orders, approvals, the approver inbox, stock and backend
orders, the kill switch, session events, idempotency records and the kitchens' memory, saved as JSON
documents in the gateway's SQLite store (the audit chain and signed offers already live there).

save(gw) runs after every state-changing call when the store is a file (AIMO_DB); load(gw) at boot.
Signing keys are PEM files in the keys directory, so the JWKS is stable across restarts and an old
confirmation still verifies. An in-memory gateway (tests, :memory:) writes nothing.
"""
from __future__ import annotations

from datetime import date

KIND = "state"


def enabled(gw) -> bool:
    return gw.store.path != ":memory:"


def _backend(be) -> dict:
    return {"stock": be.stock, "base_stock": be.base_stock, "inbound": be.inbound, "prices": be.prices,
            "earliest_override": {g: d.isoformat() for g, d in be.earliest_override.items()},
            "orders": be.orders, "live": be.live, "restock_used": be.restock_used, "sold": be.sold}


def snapshot(gw) -> dict:
    return {"sessions": gw.engine.sessions, "orders": gw.orders, "approvals": gw.approvals, "inbox": gw.inbox,
            "kill_switch": gw.kill_switch, "events": gw.events.log, "idem": gw.engine.idem,
            "memory": getattr(gw, "memory", None), "backend": _backend(gw.backend),
            "seller": getattr(gw, "seller_state", None)}


def save(gw):
    if not enabled(gw):
        return
    with gw.lock:
        for k, v in snapshot(gw).items():
            if v is not None:
                gw.store.put(KIND, k, {"v": v})


def load(gw) -> bool:
    """Restore a saved state. Returns True when there was one."""
    if not enabled(gw):
        return False
    got = {k: (gw.store.get(KIND, k) or {}).get("v") for k in snapshot(gw)}
    if got["sessions"] is None:
        return False
    gw.engine.sessions.update(got["sessions"])
    gw.orders.update(got["orders"] or {})
    gw.approvals.update(got["approvals"] or {})
    gw.inbox[:] = got["inbox"] or []
    gw.kill_switch.update(got["kill_switch"] or {})
    gw.events.log.update(got["events"] or {})
    gw.engine.idem.update(got["idem"] or {})
    if got["memory"] is not None:
        gw.memory = got["memory"]
    if got["seller"] is not None:
        gw.seller_state = got["seller"]
    b = got["backend"]
    if b:
        be = gw.backend
        be.stock, be.base_stock, be.inbound, be.prices = b["stock"], b["base_stock"], b["inbound"], b["prices"]
        be.earliest_override = {g: date.fromisoformat(d) for g, d in b["earliest_override"].items()}
        be.orders, be.live = b["orders"], b["live"]
        be.restock_used = b.get("restock_used", {})
        be.sold = b.get("sold", {})
    return True
