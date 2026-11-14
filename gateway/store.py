"""SQLite persistence (stdlib). Entities are JSON documents keyed by (kind, id);
the audit ledger is a separate append-only, hash-chained table."""
from __future__ import annotations

import json
import sqlite3
import threading


class Store:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL") if path != ":memory:" else None
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS objects(kind TEXT, id TEXT, buyer TEXT, created TEXT, json TEXT,
                                               PRIMARY KEY(kind, id));
            CREATE INDEX IF NOT EXISTS ix_obj_buyer ON objects(kind, buyer);
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY, event_id TEXT, ts TEXT, trace_id TEXT,
                                             buyer TEXT, json TEXT, prev_hash TEXT, hash TEXT);
            CREATE INDEX IF NOT EXISTS ix_audit_trace ON audit(trace_id);
            """
        )

    def wipe(self):
        with self.lock:
            self.db.executescript("DELETE FROM objects; DELETE FROM audit;")
            self.db.commit()

    # -- documents ---------------------------------------------------------
    def put(self, kind: str, id_: str, doc: dict, buyer: str | None = None, created: str | None = None):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO objects(kind,id,buyer,created,json) VALUES(?,?,?,?,?)",
                            (kind, id_, buyer, created or doc.get("createdAt") or "", json.dumps(doc, ensure_ascii=False)))
            self.db.commit()
        return doc

    def get(self, kind: str, id_: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT json FROM objects WHERE kind=? AND id=?", (kind, id_)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str, buyer: str | None = None) -> list[dict]:
        with self.lock:
            if buyer:
                rows = self.db.execute("SELECT json FROM objects WHERE kind=? AND buyer=? ORDER BY created, id",
                                       (kind, buyer)).fetchall()
            else:
                rows = self.db.execute("SELECT json FROM objects WHERE kind=? ORDER BY created, id", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete(self, kind: str, id_: str | None = None, buyer: str | None = None) -> int:
        with self.lock:
            if id_:
                cur = self.db.execute("DELETE FROM objects WHERE kind=? AND id=?", (kind, id_))
            else:
                cur = self.db.execute("DELETE FROM objects WHERE kind=? AND buyer=?", (kind, buyer))
            self.db.commit()
            return cur.rowcount
