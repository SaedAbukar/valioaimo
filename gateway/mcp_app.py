"""MCP facade over the same playbook tools, built for ONE shared Gateway.

`build(get_gw, get_analyst, get_me)` returns an MCP server whose tools run on the gateway that
`get_gw()` returns. The REST app (`python -m gateway`) mounts it over Streamable HTTP at /mcp on
its own Gateway, so an MCP agent and the REST approver see the same sessions, inbox, stock and
audit chain; the agent's identity comes from the Bearer header of each request (see `asgi`).
`python -m gateway.mcp_server` runs the same tools over stdio, either in-process (tests, dev) or
as a thin proxy to a running gateway (AIMO_GATEWAY_URL, scripts/mcp_stdio_proxy.py).

Every MCP tool call goes through the same state machine as REST: an out-of-order call returns
{"error": "step_not_allowed", "next_allowed_tools": [...]}. There is deliberately no approve tool:
approvals belong to named humans (POST /v1/approvals/{id} with their own credential).
"""
from __future__ import annotations

import contextvars
import json
from typing import Callable

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

import functools

from mcp.types import CallToolResult, TextContent

from . import auth, authz, discovery, lookup, manifest, mcp_tools, seller, trust
from .analytics.analyst import ASK_FILTERS
from .analytics.engine import insight_playbook, public as insight_public
from .crypto import verify_jws
from .playbook.engine import PlaybookError, playbook, public_playbook, validate_input
from .policy import published_rules
from .events import Busy
from .observability import audit_rejection
from .ratelimit import RateLimiter

CALLER: contextvars.ContextVar[auth.Caller | None] = contextvars.ContextVar("mcp_caller", default=None)


def _dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def _errorize(fn):
    """A tool result with status >= 400 becomes an MCP protocol-level error (isError: true); the text stays the
    gateway's JSON error body (error, message, guard, fix, next_allowed_tools)."""
    @functools.wraps(fn)
    def w(*a, **k):
        out = fn(*a, **k)
        try:
            d = json.loads(out)
        except (TypeError, ValueError):
            return out
        if isinstance(d, dict) and isinstance(d.get("status"), int) and d["status"] >= 400:  # orders have status "ordered"
            return CallToolResult(content=[TextContent(type="text", text=out)], is_error=True)
        return out
    return w


class _Registrar:
    """Registers tools on the MCP server with _errorize, keeping the plain functions callable."""

    def __init__(self, server):
        self.server = server

    def tool(self, name: str | None = None, description: str | None = None):
        def deco(fn):
            self.server.tool(name=name or fn.__name__, description=description or fn.__doc__)(_errorize(fn))
            return fn
        return deco


def build(get_gw: Callable, get_analyst: Callable, get_me: Callable[[], auth.Caller], base_url: str = "http://127.0.0.1:8000"):
    """Build the MCP server. Returns (server, {tool name: function}) so callers (and tests) can call tools directly."""
    server = FastMCP("aimo-agent-gateway")
    mcp = _Registrar(server)
    limit = RateLimiter.from_env()
    fns: dict[str, Callable] = {}

    def tool(fn):
        mcp.tool()(fn)
        fns[fn.__name__] = fn
        return fn

    def forbidden(message: str = "This session belongs to another agent.") -> str:
        return _dump({"status": 403, "error": "forbidden", "message": message})

    def G():
        return get_gw()

    def ME() -> auth.Caller:
        return get_me()

    def run(session_id: str | None, name: str, args: dict) -> str:
        me = ME()
        if (wait := limit.check(me.agent_id)) is not None:
            return _dump({"status": 429, "error": "rate_limited", "retryAfter": wait, "fix": {"retryAfterSeconds": wait}})
        try:
            if session_id:
                authz.own_session(G(), me, session_id)
            return _dump(G().engine.call(session_id, name, args, actor=me.label if name == "start_session" else None))
        except (PlaybookError, auth.AuthError) as e:
            if not getattr(e, "audited", False):  # the engine already audits its own refusals
                audit_rejection(G(), me.label, me.buyer_id, name, e.status, e.body(),
                                trace_id=session_id if session_id in G().engine.sessions else None)
            return _dump({"status": e.status, **e.body()})

    def run_insight(session_id, name, args):
        try:
            if session_id:
                s = G().insights.sessions.get(session_id)
                if s and not authz.can_read_analysis(ME(), s):
                    return forbidden("This analysis belongs to another customer.")
            return _dump(G().insights.call(session_id, name, args))
        except PlaybookError as e:
            return _dump({"status": e.status, **e.body()})

    fns["_run"], fns["_run_insight"] = run, run_insight

    @tool
    def get_playbook() -> str:
        """The versioned order playbook: steps 0-8, tools per step, input and output schemas and guards. Read this first."""
        return _dump(public_playbook())

    @tool
    def start_session(buyerId: str | None = None, idempotencyKey: str | None = None) -> str:
        """Step 0 · Receive. Start a playbook session for this agent's buyer. Returns sessionId and next_allowed_tools.
        idempotencyKey: a retried start returns the same session."""
        me = ME()
        if buyerId and buyerId != me.buyer_id:
            return forbidden(f"This agent acts only for {me.buyer_id}.")
        args = {"buyerId": me.buyer_id, "agentId": me.agent_id, "channel": "mcp"}
        try:  # the engine's dict is what is stored, so a failed start is never replayed
            return _dump(G().engine.idempotent(f"{me.agent_id}|start_session", idempotencyKey, args,
                                               lambda: G().engine.call(None, "start_session", args, actor=me.label)))
        except PlaybookError as e:
            return _dump({"status": e.status, **e.body()})

    @tool
    def whoami() -> str:
        """The customer account and agent this MCP connection acts for, and the signed authority (mandate) it works under."""
        me = ME()
        signed = G().mandates[me.buyer_id]
        return _dump({"buyerId": me.buyer_id, "agentId": me.agent_id, "mandate": signed["mandate"], "jws": signed["jws"],
                      "buyerJwks": G().buyer_jwks(me.buyer_id)})

    @tool
    def discover_gateway() -> str:
        """The gateway's UCP-style profile: services, capabilities, trust keys, rules and playbook links."""
        return _dump(discovery.ucp_profile(base_url))

    @tool
    def get_rules() -> str:
        """Published guardrails: what the agent may decide alone, what needs a named human, what is never allowed."""
        return _dump(published_rules(G()))

    @tool
    def lookup_products(query: str, qty: float | None = None, needBy: str | None = None,
                        excludeAllergens: list[str] | None = None, limit: int = 8) -> str:
        """Search Valio Aimo products with price (per sales unit and per kg/L) and availability for a need-by date (YYYY-MM-DD).
        Read-only; ranked good-better-best. To buy, start a session."""
        return _dump(lookup.search(G(), query, qty, needBy, excludeAllergens, None, limit))

    @tool
    def get_price_availability(productIds: list[str], needBy: str | None = None, qty: float | None = None) -> str:
        """Price and availability for known Valio Aimo product ids (max 20)."""
        return _dump(lookup.price_availability(G(), productIds, needBy, qty))

    def my_offer(offerId: str):
        of = G().store.get("offer", offerId)
        return of if authz.can_read_offer(ME(), of) else None

    @tool
    def get_offer(offerId: str) -> str:
        """A signed, time-limited offer (W3C VC as vc+jwt, ES256). Verify with the gateway JWKS."""
        return _dump(my_offer(offerId) or {"status": 404, "error": "not_found"})

    @tool
    def verify_offer(offerId: str) -> str:
        """Six trust checks on an offer: signature, validity window, stock freshness, binding, revocation, live re-check."""
        of = my_offer(offerId)
        return _dump(trust.verify_offer(G(), of) if of else {"status": 404, "error": "not_found"})

    @tool
    def get_order(orderId: str) -> str:
        """An order with its signed confirmation (order+jwt) and whether the signature verifies."""
        o = G().orders.get(orderId)
        if not authz.can_read_order(G(), ME(), o):
            return _dump({"status": 404, "error": "not_found", "fix": {"call": "get_audit_log", "why": "find your own orders"}})
        ok, payload, _ = verify_jws(o["confirmation"]["jws"], G().jwks()["keys"])
        return _dump({**o, "confirmationVerified": ok, "confirmationPayload": payload})

    @tool
    def get_audit_log(sessionId: str | None = None) -> str:
        """This buyer's hash-chained audit log (optionally one session) and whether the chain verifies."""
        return _dump({"verify": G().audit.verify(), "events": G().audit.events_for(ME(), trace_id=sessionId)})

    @tool
    def get_suggestions() -> str:
        """Promotional suggestions from Valio Aimo's seller agent for this buyer (at most 3, signed as suggestion+jwt,
        issuer 'Valio Aimo seller agent'). Never added to an order: to use one, plan_basket(acceptSuggestion=...)."""
        return _dump(seller.for_buyer(G(), ME().buyer_id))

    @tool
    def suggestion_feedback(suggestionId: str, decision: str, reason: str | None = None, idempotencyKey: str | None = None) -> str:
        """Tell the seller agent what you did with a suggestion: decision 'accepted' or 'dismissed' (not suggested again
        for 30 days), with an optional reason. Audited."""
        me = ME()
        s = seller.get(G(), suggestionId)
        if not s or s["buyerId"] != me.buyer_id:
            return _dump({"status": 404, "error": "not_found", "fix": {"call": "get_suggestions"}})
        args = {"decision": decision, **({"reason": reason} if reason else {})}
        try:
            validate_input(seller.FEEDBACK_SCHEMA, "suggestion_feedback", args)
            out = G().engine.idempotent(f"{suggestionId}|feedback", idempotencyKey, args, lambda: seller.feedback(
                G(), me.buyer_id, suggestionId, decision, reason, actor=me.label))
        except PlaybookError as e:
            return _dump({"status": e.status, **e.body()})
        return _dump(out)

    @tool
    def wait_for_update(sessionId: str, after: int = 0, timeoutSeconds: float = 20) -> str:
        """Push updates: wait (up to 25 s) for this session's next events after cursor `after`, e.g. approval.decided
        after request_approval. Returns {events, next, next_allowed_tools}; call again with after=next."""
        me = ME()
        try:
            s = authz.own_session(G(), me, sessionId)
        except (PlaybookError, auth.AuthError) as e:
            return _dump({"status": e.status, **e.body()})
        try:
            evs = G().events.wait(sessionId, after, timeoutSeconds)
        except Busy:
            return _dump({"status": 503, "error": "busy", "retryAfter": 2, "fix": {"retryAfterSeconds": 2}})
        return _dump({"sessionId": sessionId, "events": evs, "next": evs[-1]["seq"] if evs else after,
                      "next_allowed_tools": G().engine.allowed(s)})

    @tool
    def call_tool(sessionId: str, tool: str, args_json: str = "{}", idempotencyKey: str | None = None) -> str:
        """Generic fallback: run any playbook tool for a session with its input as a JSON string. Prefer the typed tools.
        idempotencyKey: retry-safe place_order / request_approval / record_usage (same key + same args = same result)."""
        try:
            args = json.loads(args_json or "{}")
            if not isinstance(args, dict):
                raise ValueError("args_json must be a JSON object")
        except ValueError as e:
            return _dump({"status": 422, "error": "guard_failed", "guard": "bad_input", "message": f"args_json is not a JSON object: {e}",
                          "fix": {"example": '{"text": "I need 1,000 litres of lactose-free milk by Monday."}'}})
        if idempotencyKey:
            args["idempotencyKey"] = idempotencyKey
        return run(sessionId, tool, args)

    @tool
    def list_tools() -> str:
        """Every tool for the whole journey (order + insight playbooks), in order, with how to call them."""
        return _dump(manifest.tools())

    @tool
    def get_insight_playbook() -> str:
        """The insight playbook: steps, inputs and worked examples for answering questions with charts."""
        return _dump(insight_public())

    @tool
    def start_analysis(buyerId: str | None = None, siteId: str | None = None) -> str:
        """Insight step 0 'start': open an analysis for this agent's buyer (optionally one kitchen). Data never crosses buyers."""
        me = ME()
        if buyerId and buyerId != me.buyer_id:
            return forbidden(f"This agent acts only for {me.buyer_id}.")
        return run_insight(None, "start_analysis", {"buyerId": me.buyer_id, "siteId": siteId, "agent": "mcp"})

    # (an MCP tool list narrowed to next_allowed_tools would need list_changed notifications; this server is stateless
    #  HTTP, so every result carries next_allowed_tools instead — see docs/ASSUMPTIONS.md)

    # one typed tool per order and insight tool, generated from the playbooks' input schemas (1.1.0)
    fns.update(mcp_tools.register(mcp, playbook(), insight_playbook(), run, run_insight,
                                  skip={"start_session", "start_analysis", "get_playbook"}))

    @tool
    def ask_insight(buyerId: str, prompt: str, filters_json: str = "{}") -> str:
        """Shortcut: answer a question with a chart using the gateway's own analyst (runs the insight rails)."""
        if buyerId != ME().buyer_id:
            return forbidden(f"This agent acts only for {ME().buyer_id}.")
        try:
            filters = json.loads(filters_json or "{}")
            if not isinstance(filters, dict):
                raise ValueError("filters_json must be a JSON object")
        except ValueError as e:
            return _dump({"status": 422, "error": "guard_failed", "guard": "bad_input", "message": str(e),
                          "fix": {"example": json.dumps(ASK_FILTERS["examples"][0])}})
        try:
            validate_input(ASK_FILTERS, "ask_insight", filters)
            return _dump(get_analyst().ask(prompt, filters, buyerId))
        except PlaybookError as e:
            return _dump({"status": e.status, **e.body()})

    return server, fns


def build_ops(get_gw: Callable):
    """MCP tools for Valio Aimo operations (AIMO_AGENT_TOKEN=demo-ops): cross-customer views, k >= 3, read-only."""
    from . import ops
    server = FastMCP("aimo-gateway-operations")
    mcp = _Registrar(server)
    fns: dict[str, Callable] = {}

    def tool(fn):
        mcp.tool()(fn)
        fns[fn.__name__] = fn
        return fn

    def safe(fn, *a):
        try:
            return _dump(fn(get_gw(), *a))
        except PlaybookError as e:
            return _dump({"status": e.status, **e.body()})

    @tool
    def ops_metrics() -> str:
        """Agent-channel metrics across customers (k >= 3): autonomous rate, approval rate and wait, re-quote rate,
        blocked rate, fill rate, time to order, refused calls, seller-suggestion acceptance; plus raw counters."""
        return safe(ops.metrics)

    @tool
    def ops_demand(from_: str | None = None, to: str | None = None, by: str = "day") -> str:
        """Forward demand from agents' plans and orders, by need-by day, category or product (k >= 3 customers per group)."""
        return safe(ops.demand, from_, to, by)

    @tool
    def ops_lost_sales(from_: str | None = None, to: str | None = None) -> str:
        """Needs agents could not get from Valio Aimo, by reason (k >= 3 customers per group)."""
        return safe(ops.lost_sales, from_, to)

    return server, fns


def http_app(get_gw: Callable, get_analyst: Callable, base_url: str = "http://127.0.0.1:8000"):
    """MCP over Streamable HTTP for the REST app: identity from each request's Bearer header (agents only).
    Returns (asgi app to mount at /mcp, the MCP server whose session_manager must run in the app lifespan)."""
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import JSONResponse

    def me() -> auth.Caller:
        c = CALLER.get()
        if c is None:
            raise RuntimeError("no MCP caller bound")
        return c

    server, _ = build(get_gw, get_analyst, me, base_url)
    inner = server.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]))

    async def asgi(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        try:
            c = auth.require(get_gw(), headers.get("authorization"), "agent")
        except auth.AuthError as e:
            return await JSONResponse(e.body(), status_code=e.status)(scope, receive, send)
        tok = CALLER.set(c)
        try:
            if scope.get("path", "") in ("", "/mcp"):
                scope = dict(scope, path="/")
            await inner(scope, receive, send)
        finally:
            CALLER.reset(tok)

    return asgi, server
