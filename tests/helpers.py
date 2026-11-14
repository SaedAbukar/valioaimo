"""Test-only helpers (kept out of production classes)."""
import json


def tamper(ledger, seq: int | None = None) -> dict:
    """Silently edit a stored audit row to show tamper evidence (what an attacker with DB access would do)."""
    db = ledger.store.db
    with ledger.store.lock:
        row = db.execute("SELECT seq, json FROM audit WHERE seq=?", (seq,)).fetchone() if seq else \
            db.execute("SELECT seq, json FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        if not row:
            return {"ok": False, "detail": "no events"}
        ev = json.loads(row[1])
        original = ev.get("decision")
        ev["decision"] = "AUTO"
        ev["reason"] = (ev.get("reason") or "") + " [edited]"
        db.execute("UPDATE audit SET json=? WHERE seq=?", (json.dumps(ev, ensure_ascii=False), row[0]))
        db.commit()
    return {"ok": True, "seq": row[0], "changed": {"decision": [original, "AUTO"]}}
