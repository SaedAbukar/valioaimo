"""Observability: raw counters for Valio Aimo operations, structured JSON request logs with a request id and
W3C trace context (traceparent) passthrough, and an audit entry for every rejected call (403, 409, 422)."""
from __future__ import annotations

import json
import logging
import re
import secrets
import statistics
import threading
import time
from collections import Counter

LOG = logging.getLogger("aimo.gateway")
LOG.setLevel(logging.INFO)
TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
SESSION_IN_PATH = re.compile(r"/v1/sessions/(SES-[0-9A-F]+)")
REJECTED = (403, 409, 422)


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.tool_calls: Counter = Counter()
        self.decisions: Counter = Counter()
        self.status: Counter = Counter()

    def tool(self, name: str, out: dict | None = None):
        with self.lock:
            self.tool_calls[name] += 1
            if name == "check_basket" and isinstance(out, dict) and out.get("decision"):
                self.decisions[out["decision"]] += 1

    def http(self, status: int):
        with self.lock:
            self.status[str(status)] += 1

    def snapshot(self, gw) -> dict:
        with self.lock:
            total = sum(self.status.values()) or 1
            a = getattr(gw, "aimo", None)
            lat = list(getattr(a, "latency_ms", []) or [])
            return {
                "toolCalls": dict(self.tool_calls), "decisions": dict(self.decisions), "status": dict(self.status),
                "requests": sum(self.status.values()),
                "rates": {k: round(self.status.get(k, 0) / total, 4) for k in ("401", "403", "409", "422", "429")},
                "adapter": {"configured": bool(a), "calls": getattr(a, "calls", 0), "errors": getattr(a, "failures", 0),
                            "lastError": getattr(a, "last_error", None),
                            "latencyMs": {"p50": statistics.median(lat) if lat else None,
                                          "p95": sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else None, "n": len(lat)},
                            "breaker": a.breaker_state() if a and hasattr(a, "breaker_state") else None},
                "sessions": len(gw.engine.sessions), "orders": len(gw.orders), "pendingApprovals": len(gw.inbox),
            }


def audit_rejection(gw, actor: str, buyer_id: str | None, name: str, status: int, body: dict, trace_id: str | None = None):
    """Every refused call is evidence too: who tried what, and which guard stopped it."""
    if status not in REJECTED:
        return
    gw.audit.append(trace_id=trace_id, actor=actor, action=f"rejected.{name}", buyer_id=buyer_id,
                    refs={"status": status, "error": body.get("error"), "guard": body.get("guard")},
                    reason=(body.get("message") or body.get("error") or "")[:280])


class RequestLog:
    """ASGI middleware: one JSON log line per request; X-Request-Id and traceparent on every response."""

    def __init__(self, app, metrics_of):
        self.app = app
        self.metrics_of = metrics_of

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        h = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        rid = (h.get("x-request-id") or secrets.token_hex(8))[:64]
        m = TRACEPARENT.match(h.get("traceparent", ""))
        trace_id = m.group(1) if m else secrets.token_hex(16)
        span = secrets.token_hex(8)
        tp = f"00-{trace_id}-{span}-{m.group(3) if m else '01'}"
        t0 = time.perf_counter()
        st = {"status": 500}

        async def send2(msg):
            if msg["type"] == "http.response.start":
                st["status"] = msg["status"]
                msg = dict(msg, headers=list(msg.get("headers", [])) + [(b"x-request-id", rid.encode()), (b"traceparent", tp.encode())])
            await send(msg)

        try:
            await self.app(scope, receive, send2)
        finally:
            path = scope.get("path", "")
            sm = SESSION_IN_PATH.search(path)
            try:
                self.metrics_of().http(st["status"])
            except Exception:  # noqa: BLE001 - metrics never break a request
                pass
            LOG.info(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "level": "info", "msg": "request",
                                 "requestId": rid, "traceId": trace_id, "spanId": span, "method": scope.get("method"),
                                 "path": path, "status": st["status"], "ms": round((time.perf_counter() - t0) * 1000, 1),
                                 "sessionId": sm.group(1) if sm else None}))
