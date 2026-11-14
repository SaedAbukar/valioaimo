"""Stdio MCP for clients that only speak stdio (Claude Desktop), proxied to a RUNNING gateway's
Streamable HTTP endpoint, so the agent shares sessions, approvals, stock and audit with REST.

    AIMO_GATEWAY_URL=http://127.0.0.1:8000 AIMO_AGENT_TOKEN=demo-key-pohjola python -m gateway.mcp_server

Reads one JSON-RPC message per line from stdin, POSTs it to <url>/mcp with the agent's Bearer token,
and writes the JSON-RPC response (if any) to stdout. Stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def http_post(url: str, token: str):
    def post(msg: dict) -> tuple[int, str]:
        req = urllib.request.Request(url.rstrip("/") + "/mcp", data=json.dumps(msg).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                              "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    return post


def forward(line: str, post) -> str | None:
    """One stdin line -> the line to write to stdout (None for notifications)."""
    try:
        msg = json.loads(line)
    except ValueError:
        return json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    status, body = post(msg)
    if "id" not in msg:
        return None
    if status != 200:
        return json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": f"gateway HTTP {status}: {body[:300]}"}})
    if body.startswith("event:") or body.startswith("data:"):  # SSE framing: take the data line
        body = next((ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")), "{}")
    return body


def main() -> int:
    post = http_post(os.environ["AIMO_GATEWAY_URL"], os.environ.get("AIMO_AGENT_TOKEN", "demo-key-pohjola"))
    for line in sys.stdin:
        if line.strip():
            out = forward(line, post)
            if out:
                sys.stdout.write(out + "\n")
                sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
