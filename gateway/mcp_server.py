"""MCP facade over the same playbook tools: `python -m gateway.mcp_server` (stdio).

Every MCP tool call goes through the same state machine as REST, so an MCP
client (Claude Desktop, Claude Code, any MCP agent) gets the same rails:
an out-of-order call returns {"error": "step_not_allowed", "next_allowed_tools": [...]}.
"""
from __future__ import annotations

import json
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .adapter import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .core import Gateway  # noqa: E402
from .playbook.engine import PlaybookError, playbook, public_playbook  # noqa: E402
from .analytics.analyst import Analyst  # noqa: E402
from .analytics.engine import insight_playbook, public as insight_public  # noqa: E402
from . import manifest  # noqa: E402

GW = Gateway(live=True)
mcp = FastMCP("aimo-agent-gateway")


def _run(session_id: str | None, tool: str, args: dict) -> str:
    try:
        return json.dumps(GW.engine.call(session_id, tool, args), ensure_ascii=False, default=str)
    except PlaybookError as e:
        return json.dumps({"status": e.status, **e.body()}, ensure_ascii=False)


@mcp.tool()
def get_playbook() -> str:
    """The versioned order playbook: steps 0-8, tools per step, output schemas and guards. Read this first."""
    return json.dumps(public_playbook(), ensure_ascii=False)


@mcp.tool()
def start_session(buyerId: str, agentId: str | None = None) -> str:
    """Step 0 · Receive. Start a playbook session for a buyer (e.g. BUY-POHJOLA). Returns sessionId and next_allowed_tools."""
    return _run(None, "start_session", {"buyerId": buyerId, **({"agentId": agentId} if agentId else {})})


@mcp.tool()
def call_tool(sessionId: str, tool: str, args_json: str = "{}") -> str:
    """Run any playbook tool for a session, e.g. parse_request {"text": "..."}, recall, request_offers,
    plan_basket, check_basket, render_cards, place_order. Out-of-order calls return step_not_allowed."""
    return _run(sessionId, tool, json.loads(args_json or "{}"))


def _register(name: str):
    def fn(sessionId: str, args_json: str = "{}") -> str:
        return _run(sessionId, name, json.loads(args_json or "{}"))
    fn.__name__ = name
    step = playbook()["toolStep"][name]
    fn.__doc__ = f"Playbook step '{step}': {playbook()['byId'][step]['does']} (args as JSON)."
    mcp.tool(name=name, description=fn.__doc__)(fn)


for _t in playbook()["toolStep"]:
    if _t != "start_session":
        _register(_t)

ANALYST = Analyst(GW)


def _run_insight(session_id, tool, args):
    try:
        return json.dumps(GW.insights.call(session_id, tool, args), ensure_ascii=False, default=str)
    except PlaybookError as e:
        return json.dumps({"status": e.status, **e.body()}, ensure_ascii=False)


@mcp.tool()
def list_tools() -> str:
    """Every tool for the whole journey (order + insight playbooks), in order, with how to call them."""
    return json.dumps(manifest.tools(), ensure_ascii=False)


@mcp.tool()
def get_insight_playbook() -> str:
    """The insight playbook: steps, inputs and worked examples for answering questions with charts."""
    return json.dumps(insight_public(), ensure_ascii=False)


def _register_insight(name: str, step: dict):
    if name == "start_analysis":
        def fn(buyerId: str, siteId: str | None = None) -> str:
            return _run_insight(None, "start_analysis", {"buyerId": buyerId, "siteId": siteId, "agent": "mcp"})
    else:
        def fn(sessionId: str, args_json: str = "{}") -> str:
            return _run_insight(sessionId, name, json.loads(args_json or "{}"))
    fn.__name__ = name
    mcp.tool(name=name, description=f"Insight step '{step['id']}': {step['does']} (args as JSON)")(fn)


for _st in insight_playbook()["steps"]:
    for _t in _st["tools"]:
        _register_insight(_t, _st)


@mcp.tool()
def ask_insight(buyerId: str, prompt: str, filters_json: str = "{}") -> str:
    """Shortcut: answer a question with a chart using the gateway's own analyst (runs the insight rails)."""
    return json.dumps(ANALYST.ask(prompt, json.loads(filters_json or "{}"), buyerId), ensure_ascii=False, default=str)

if __name__ == "__main__":
    mcp.run()
