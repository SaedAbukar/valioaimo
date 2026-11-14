"""MCP over stdio: `python -m gateway.mcp_server` (or `make mcp`).

Two modes:
  * AIMO_GATEWAY_URL set (e.g. http://127.0.0.1:8000): a thin stdio proxy to the running gateway's
    Streamable HTTP endpoint /mcp (scripts/mcp_stdio_proxy.py). The agent then shares sessions,
    approvals, stock and audit with every REST client: this is the mode to use with `make run`.
  * not set: an in-process gateway of its own (tests and quick experiments only; approvals made in
    another process cannot reach it).

Identity: AIMO_AGENT_TOKEN, the agent's bearer token (defaults to the demo Pohjola agent).
The tools themselves live in gateway/mcp_app.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .adapter import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

if __name__ == "__main__" and os.environ.get("AIMO_GATEWAY_URL"):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.mcp_stdio_proxy import main as _proxy

    sys.exit(_proxy())

from . import auth, mcp_app  # noqa: E402
from .analytics.analyst import Analyst  # noqa: E402
from .core import Gateway  # noqa: E402

GW = Gateway(live=os.environ.get("AIMO_LIVE", "1") == "1")
ME = auth.resolve(GW, "Bearer " + os.environ.get("AIMO_AGENT_TOKEN", "demo-key-pohjola"))
if ME is None or ME.kind != "agent":
    raise SystemExit("AIMO_AGENT_TOKEN is not a registered agent credential.")
ANALYST = Analyst(GW)

mcp, _fns = mcp_app.build(lambda: GW, lambda: ANALYST, lambda: ME,
                          base_url=os.environ.get("AIMO_PUBLIC_URL", "http://127.0.0.1:8000"))
globals().update(_fns)  # tools callable as module functions (tests)

if __name__ == "__main__":
    mcp.run()
