"""MCP facade over the same playbook tools: `python -m gateway.mcp_server` (stdio).

Every MCP tool call goes through the same state machine as REST, so an MCP
client (Claude Desktop, Claude Code, any MCP agent) gets the same rails:
an out-of-order call returns {"error": "step_not_allowed", "next_allowed_tools": [...]}.

Identity: the server acts for ONE agent, set by AIMO_AGENT_TOKEN (the agent's bearer
token; defaults to the demo Pohjola agent). Sessions of other buyers or agents are
refused. There is deliberately no approve tool: approvals belong to named humans
(POST /v1/approvals/{id} with their own credential).
"""
from __future__ import annotations

import json
import os
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
from . import auth, discovery, lookup, manifest, mcp_tools, trust  # noqa: E402
from .crypto import verify_jws  # noqa: E402
from .policy import published_rules  # noqa: E402

GW = Gateway(live=os.environ.get("AIMO_LIVE", "1") == "1")
ME = auth.resolve(GW, "Bearer " + os.environ.get("AIMO_AGENT_TOKEN", "demo-key-pohjola"))
if ME is None or ME.kind != "agent":
    raise SystemExit("AIMO_AGENT_TOKEN is not a registered agent credential.")
mcp = FastMCP("aimo-agent-gateway")


def _dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def _run(session_id: str | None, tool: str, args: dict) -> str:
    try:
        if session_id:
            s = GW.engine.session(session_id)
            if s["buyerId"] != ME.buyer_id or s["agentId"] != ME.agent_id:
                return _dump({"status": 403, "error": "forbidden", "message": "This session belongs to another agent."})
        return _dump(GW.engine.call(session_id, tool, args, actor=ME.label if tool == "start_session" else None))
    except PlaybookError as e:
        return _dump({"status": e.status, **e.body()})


@mcp.tool()
def get_playbook() -> str:
    """The versioned order playbook: steps 0-8, tools per step, output schemas and guards. Read this first."""
    return json.dumps(public_playbook(), ensure_ascii=False)


@mcp.tool()
def start_session(buyerId: str | None = None) -> str:
    """Step 0 · Receive. Start a playbook session for this agent's buyer. Returns sessionId and next_allowed_tools."""
    if buyerId and buyerId != ME.buyer_id:
        return _dump({"status": 403, "error": "forbidden", "message": f"This agent acts only for {ME.buyer_id}."})
    return _run(None, "start_session", {"buyerId": ME.buyer_id, "agentId": ME.agent_id, "channel": "mcp"})


@mcp.tool()
def whoami() -> str:
    """The customer account and agent this MCP server acts for, and the signed authority (mandate) it works under."""
    signed = GW.mandates[ME.buyer_id]
    return _dump({"buyerId": ME.buyer_id, "agentId": ME.agent_id, "mandate": signed["mandate"], "jws": signed["jws"],
                  "buyerJwks": GW.buyer_jwks(ME.buyer_id)})


@mcp.tool()
def discover_gateway() -> str:
    """The gateway's UCP-style profile: services, capabilities, trust keys, rules and playbook links."""
    return _dump(discovery.ucp_profile("http://127.0.0.1:8000"))


@mcp.tool()
def get_rules() -> str:
    """Published guardrails: what the agent may decide alone, what needs a named human, what is never allowed."""
    return _dump(published_rules(GW))


@mcp.tool()
def lookup_products(query: str, qty: float | None = None, needBy: str | None = None,
                    excludeAllergens: list[str] | None = None, limit: int = 8) -> str:
    """Search Valio Aimo products with price (per sales unit and per kg/L) and availability for a need-by date (YYYY-MM-DD).
    Read-only; ranked good-better-best. To buy, start a session."""
    return _dump(lookup.search(GW, query, qty, needBy, excludeAllergens, None, limit))


@mcp.tool()
def get_price_availability(productIds: list[str], needBy: str | None = None, qty: float | None = None) -> str:
    """Price and availability for known Valio Aimo product ids (max 20)."""
    return _dump(lookup.price_availability(GW, productIds, needBy, qty))


def _my_offer(offerId: str):
    of = GW.store.get("offer", offerId)
    return of if of and of.get("buyerId") == ME.buyer_id else None


@mcp.tool()
def get_offer(offerId: str) -> str:
    """A signed, time-limited offer (W3C VC as vc+jwt, ES256). Verify with the gateway JWKS."""
    of = _my_offer(offerId)
    return _dump(of or {"status": 404, "error": "not_found"})


@mcp.tool()
def verify_offer(offerId: str) -> str:
    """Six trust checks on an offer: signature, validity window, stock freshness, binding, revocation, live re-check."""
    of = _my_offer(offerId)
    return _dump(trust.verify_offer(GW, of) if of else {"status": 404, "error": "not_found"})


@mcp.tool()
def get_order(orderId: str) -> str:
    """An order with its signed confirmation (order+jwt) and whether the signature verifies."""
    o = GW.orders.get(orderId)
    if not o or GW.engine.session(o["sessionId"])["buyerId"] != ME.buyer_id:
        return _dump({"status": 404, "error": "not_found"})
    ok, payload, _ = verify_jws(o["confirmation"]["jws"], GW.jwks()["keys"])
    return _dump({**o, "confirmationVerified": ok, "confirmationPayload": payload})


@mcp.tool()
def get_audit_log(sessionId: str | None = None) -> str:
    """This buyer's hash-chained audit log (optionally one session) and whether the chain verifies."""
    return _dump({"verify": GW.audit.verify(), "events": GW.audit.events(trace_id=sessionId, buyer_id=ME.buyer_id, limit=300)})


@mcp.tool()
def wait_for_update(sessionId: str, after: int = 0, timeoutSeconds: float = 20) -> str:
    """Push updates: wait (up to 25 s) for this session's next events after cursor `after`, e.g. approval.decided
    after request_approval. Returns {events, next, next_allowed_tools}; call again with after=next."""
    try:
        s = GW.engine.session(sessionId)
    except PlaybookError as e:
        return _dump({"status": e.status, **e.body()})
    if s["buyerId"] != ME.buyer_id or s["agentId"] != ME.agent_id:
        return _dump({"status": 403, "error": "forbidden", "message": "This session belongs to another agent."})
    evs = GW.events.wait(sessionId, after, timeoutSeconds)
    return _dump({"sessionId": sessionId, "events": evs, "next": evs[-1]["seq"] if evs else after,
                  "next_allowed_tools": GW.engine.allowed(s)})


@mcp.tool()
def call_tool(sessionId: str, tool: str, args_json: str = "{}", idempotencyKey: str | None = None) -> str:
    """Run any playbook tool for a session, e.g. parse_request {"text": "..."}, recall, request_offers,
    plan_basket, check_basket, render_cards, place_order. Out-of-order calls return step_not_allowed.
    idempotencyKey: retry-safe place_order / request_approval / record_usage (same key + same args = same result)."""
    args = json.loads(args_json or "{}")
    if idempotencyKey:
        args["idempotencyKey"] = idempotencyKey
    return _run(sessionId, tool, args)


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


@mcp.tool()
def start_analysis(buyerId: str | None = None, siteId: str | None = None) -> str:
    """Insight step 0 'start': open an analysis for this agent's buyer (optionally one kitchen). Data never crosses buyers."""
    if buyerId and buyerId != ME.buyer_id:
        return _dump({"status": 403, "error": "forbidden", "message": f"This agent acts only for {ME.buyer_id}."})
    return _run_insight(None, "start_analysis", {"buyerId": ME.buyer_id, "siteId": siteId, "agent": "mcp"})


# one typed tool per order and insight tool, generated from the playbooks' input schemas (1.1.0)
globals().update(mcp_tools.register(mcp, playbook(), insight_playbook(), _run, _run_insight,
                                   skip={"start_session", "start_analysis", "get_playbook"}))


@mcp.tool()
def ask_insight(buyerId: str, prompt: str, filters_json: str = "{}") -> str:
    """Shortcut: answer a question with a chart using the gateway's own analyst (runs the insight rails)."""
    if buyerId != ME.buyer_id:
        return _dump({"status": 403, "error": "forbidden", "message": f"This agent acts only for {ME.buyer_id}."})
    return _dump(ANALYST.ask(prompt, json.loads(filters_json or "{}"), buyerId))

if __name__ == "__main__":
    mcp.run()
