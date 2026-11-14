"""Gateway server: `python -m gateway` (or `make run`) -> http://127.0.0.1:8000

Serves the chat-first app (ui/dist/index.html) and the agent-facing API:
  GET  /v1/playbook                          the versioned playbook (steps, tools, schemas, guards)
  POST /v1/sessions                          start_session  -> sessionId + next_allowed_tools
  GET  /v1/sessions/{id}                     session state, outputs per step, next_allowed_tools
  POST /v1/sessions/{id}/tools/{tool}        run one playbook tool; 409 step_not_allowed if out of order
  POST /v1/approvals/{sessionId}             human approver decision {ok, by}
  POST /v1/chat, /v1/chat/{id}/actions       the built-in chef assistant (cards)
  GET  /v1/board, /v1/chats, /v1/insights    data for the app
The same tools are exposed over MCP: `python -m gateway.mcp_server`.
"""
from __future__ import annotations

import contextlib
import functools
import os
from pathlib import Path

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

from . import aimo_products, catalog, trust
from .adapter import load_dotenv
from .policy import published_rules

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from .core import Gateway  # noqa: E402  (after .env is loaded)
from .playbook import insights  # noqa: E402
from .playbook.agent import ChefAssistant  # noqa: E402
from .playbook.engine import PlaybookError, public_playbook  # noqa: E402
from . import manifest, discovery, lookup, auth, authz  # noqa: E402
from .playbook.approvals import inbox_for  # noqa: E402
from .ratelimit import RateLimiter  # noqa: E402
from .observability import RequestLog, audit_rejection  # noqa: E402
from .events import Busy  # noqa: E402
from . import ops, seller  # noqa: E402
from .playbook.engine import GuardFailed, NotFound, validate_input  # noqa: E402
from .crypto import verify_jws  # noqa: E402
from .playbook.tools import decide_approval  # noqa: E402
from .analytics import engine as insight_engine, views  # noqa: E402
from .analytics.analyst import ASK_FILTERS, Analyst  # noqa: E402


DEMO_GALA = ("Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. "
             "12 vegan, 8 gluten-free, 1 nut allergy.")


class _Asgi:
    """Wrap an ASGI callable so Starlette's Route serves it as an app (exact path, no 307 to a trailing slash)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


# other customers' agents ordered for Monday too, so Valio Aimo's operations view has >= 3 customers to show (k-anonymity)
DEMO_OTHERS = [("BUY-KAARI", "40 L soy drink by Monday"), ("BUY-KOULU", "60 L oat drink by Monday"),
               ("BUY-UUSI", "100 L milk by Monday")]


def seed_demo(agent):
    """The app opens on the gala example, already ordered; three other kitchens have one request each."""
    for bid, text in DEMO_OTHERS:
        r = agent.message(None, text, bid)
        cid = r["conversation"]["id"]
        try:
            choice = next((k for k in r.get("cards", []) if k.get("type") == "choice"), None)
            if choice:  # the chef picks the first option offered
                agent.action(cid, "pick", choice["options"][0]["payload"])
            agent.action(cid, "order")
        except PlaybookError:
            pass  # can't do, or a choice is open: it stays as the chef left it
    r = agent.message(None, DEMO_GALA, "BUY-POHJOLA")
    agent.action(r["conversation"]["id"], "order")


def make_app(live: bool = True) -> Starlette:
    state = {}

    def boot(fresh: bool = False):
        # AIMO_DB=data/gateway.db (make run) keeps sessions, orders, approvals and keys across restarts; default :memory:
        db = os.environ.get("AIMO_DB", ":memory:")
        keys = Path(db).parent / "keys" if db != ":memory:" else None
        if fresh and db != ":memory:":
            from .store import Store
            Store(db).wipe()
        state["gw"] = Gateway(db=db, live=live, keys_dir=keys)
        state["agent"] = ChefAssistant(state["gw"])
        state["analyst"] = Analyst(state["gw"])
        if os.environ.get("AIMO_SEED_DEMO", "1") == "1" and not state["gw"].restored:  # the app opens on the gala example, already ordered
            seed_demo(state["agent"])

    boot()
    gw = lambda: state["gw"]  # noqa: E731
    agent = lambda: state["agent"]  # noqa: E731

    async def body(req: Request) -> dict:
        try:
            return await req.json()
        except Exception:  # noqa: BLE001
            return {}

    async def index(_):
        return FileResponse(ROOT / "ui" / "dist" / "index.html")

    async def health(_):
        g = gw()
        live_ok = await anyio.to_thread.run_sync(g.aimo.ping) if g.aimo else False
        err_class = (g.aimo.last_error or "").split(":")[0] or None if g.aimo else "not_configured"
        return JSONResponse({"ok": True, "playbookVersion": public_playbook()["version"], "products": aimo_products.count(),
                             "liveApi": {"configured": bool(g.aimo), "reachable": live_ok, "error": err_class,
                                         "breaker": g.aimo.breaker_state() if g.aimo and hasattr(g.aimo, "breaker_state") else None}})

    async def playbook_ep(_):
        return JSONResponse(public_playbook())

    # ---------------------------------------------------------------- who is calling
    def caller(req: Request, *kinds: str) -> auth.Caller:
        return auth.require(gw(), req.headers.get("authorization"), *kinds)

    limiter = RateLimiter.from_env()

    async def off_loop(fn, *a, **k):
        """Run gateway work (engine, lookup, adapter I/O) in a worker thread so one slow call never blocks the event loop."""
        return await anyio.to_thread.run_sync(functools.partial(fn, *a, **k))

    def guarded(fn):
        async def wrap(req: Request):
            h = req.headers.get("authorization") or ""
            token = h.split(None, 1)[1].strip() if h.lower().startswith("bearer ") and " " in h else None
            if token and token != auth.OPS_TOKEN and (wait := limiter.check(token)) is not None:
                return JSONResponse({"error": "rate_limited", "message": f"Too many calls from this credential. Retry in {wait:g} s.",
                                     "retryAfter": wait, "fix": {"retryAfterSeconds": wait,
                                                                 "hint": "wait_for_update / ?wait= long-poll instead of polling"}},
                                    status_code=429, headers={"Retry-After": str(max(1, int(-(-wait // 1))))})
            try:
                return await fn(req)
            except (auth.AuthError, PlaybookError) as e:
                if not getattr(e, "audited", False):  # the engine already audits its own refusals
                    rejected(req, fn.__name__, e.status, e.body())
                return JSONResponse(e.body(), status_code=e.status)
        return wrap

    def rejected(req: Request, route: str, status: int, body_: dict):
        """Audit a refused call (403/409/422) with who tried, what, and which guard stopped it."""
        g = gw()
        c = auth.resolve(g, req.headers.get("authorization"))
        key = req.path_params.get("sid")
        sid = g.approvals.get(key, key) if key else None
        audit_rejection(g, c.label if c else "anonymous", c.buyer_id if c else None, req.path_params.get("tool") or route,
                        status, body_, trace_id=sid if sid in g.engine.sessions else None)

    def own_session(req: Request, *kinds: str) -> tuple[auth.Caller, dict]:
        c = caller(req, *(kinds or ("agent", "ops")))  # operations may read a session; only its agent drives it
        return c, authz.own_session(gw(), c, req.path_params["sid"])

    @guarded
    async def sessions(req: Request):
        c = caller(req, "agent")
        b = await body(req)
        bid = b.get("buyerId") or c.buyer_id
        auth.same_buyer(c, bid)
        args = {"buyerId": bid, "agentId": c.agent_id, "channel": "api"}
        key = req.headers.get("idempotency-key") or b.get("idempotencyKey")
        out = await off_loop(gw().engine.idempotent, f"{c.agent_id}|start_session", key, args,
                             lambda: gw().engine.call(None, "start_session", args, actor=c.label))
        return replay(out, status=200 if out.get("idempotentReplay") else 201)

    @guarded
    async def session_get(req: Request):
        _, s = own_session(req)
        return JSONResponse(gw().engine.view(s))

    def replay(out: dict, status: int = 200) -> JSONResponse:
        return JSONResponse(out, status_code=status, headers={"Idempotent-Replay": "true"} if out.get("idempotentReplay") else None)

    @guarded
    async def tool(req: Request):
        c, s = own_session(req, "agent")
        return replay(await off_loop(gw().engine.call, s["sessionId"], req.path_params["tool"], await body(req),
                                     actor=c.label, idempotency_key=req.headers.get("idempotency-key")))

    @guarded
    async def session_events(req: Request):
        _, s = own_session(req)
        try:
            after, wait = int(req.query_params.get("after", 0)), float(req.query_params.get("wait", 0))
            if not 0 <= wait <= 25:
                raise ValueError
        except ValueError:
            return JSONResponse({"error": "guard_failed", "guard": "bad_input", "message": "after is an integer, wait is 0-25 seconds.",
                                 "fix": {"example": "?after=0&wait=20"}}, status_code=422)
        try:
            evs = await off_loop(gw().events.wait, s["sessionId"], after, wait)
        except Busy:
            return JSONResponse({"error": "busy", "message": "All long-poll slots are taken. Retry shortly.",
                                 "fix": {"retryAfterSeconds": 2, "or": "call again with wait=0"}},
                                status_code=503, headers={"Retry-After": "2"})
        return JSONResponse({"sessionId": s["sessionId"], "events": evs, "next": evs[-1]["seq"] if evs else after,
                             "next_allowed_tools": gw().engine.allowed(s)})

    # ---------------------------------------------------------------- proactive seller (Valio Aimo's own agent)
    @guarded
    async def suggestions(req: Request):
        _, bid = buyer_of(req, "agent")
        return JSONResponse(await off_loop(seller.for_buyer, gw(), bid))

    @guarded
    async def suggestion_feedback(req: Request):
        c = caller(req, "agent")
        sid = req.path_params["sgid"]
        s = seller.get(gw(), sid)
        if not s:
            raise NotFound(f"No suggestion {sid}.", fix={"call": "GET /v1/suggestions"})
        auth.same_buyer(c, s["buyerId"])
        b = await body(req)
        key = req.headers.get("idempotency-key") or b.get("idempotencyKey")
        validate_input(seller.FEEDBACK_SCHEMA, "suggestion_feedback", b)
        b.pop("idempotencyKey", None)
        return replay(await off_loop(gw().engine.idempotent, f"{sid}|feedback", key, b, lambda: seller.feedback(
            gw(), c.buyer_id, sid, b["decision"], b.get("reason"), actor=c.label)))

    @guarded
    async def session_log(req: Request):
        _, s = own_session(req)
        return JSONResponse({"sessionId": s["sessionId"], "log": agent().activity(s["sessionId"]),
                             "audit": [{"at": e["ts"], "who": e["actor"], "what": e["action"], "why": e.get("reason")}
                                       for e in gw().audit.events(trace_id=s["sessionId"], limit=300)]})

    # ---------------------------------------------------------------- lookup (read-only, no commitment)
    @guarded
    async def product_search(req: Request):
        caller(req, "agent", "ops")
        b = await body(req)
        validate_input(discovery.SCHEMAS["ProductSearch"], "product_search", b)
        return JSONResponse(await off_loop(lookup.search, gw(), b["query"], b.get("qty"), b.get("needBy"), b.get("excludeAllergens"),
                                          b.get("diet"), b.get("limit", 8)))

    @guarded
    async def price_availability(req: Request):
        caller(req, "agent", "ops")
        b = await body(req)
        validate_input(discovery.SCHEMAS["PriceAvailabilityRequest"], "price_availability", b)
        return JSONResponse(await off_loop(lookup.price_availability, gw(), b["productIds"], b.get("needBy"), b.get("qty")))

    @guarded
    async def product_get(req: Request):
        caller(req, "agent", "ops")
        p = lookup.product(gw(), req.path_params["pid"])
        return JSONResponse(p) if p else JSONResponse({"error": "not_found"}, status_code=404)

    # ---------------------------------------------------------------- trust: mandate, offers, orders
    @guarded
    async def mandate_ep(req: Request):
        c = caller(req, "agent", "human")
        signed = gw().mandates[c.buyer_id]
        _, check = gw().mandate_check(c.buyer_id)
        return JSONResponse({"mandate": signed["mandate"], "jws": signed["jws"], "valid": check["ok"],
                             "buyerJwks": gw().buyer_jwks(c.buyer_id)})

    @guarded
    async def offer_get(req: Request):
        c = caller(req, "agent", "ops")
        of = gw().store.get("offer", req.path_params["oid"])
        if not of:
            return JSONResponse({"error": "not_found"}, status_code=404)
        if not authz.can_read_offer(c, of):
            raise auth.AuthError(403, "forbidden", "This credential belongs to another customer account.")
        return JSONResponse(of)

    @guarded
    async def offer_verify(req: Request):
        c = caller(req, "agent", "ops")
        of = gw().store.get("offer", req.path_params["oid"])
        if not of:
            return JSONResponse({"error": "not_found"}, status_code=404)
        if not authz.can_read_offer(c, of):
            raise auth.AuthError(403, "forbidden", "This credential belongs to another customer account.")
        return JSONResponse(await off_loop(trust.verify_offer, gw(), of))

    @guarded
    async def order_get(req: Request):
        c = caller(req, "agent", "human", "ops")
        o = gw().orders.get(req.path_params["oid"])
        if not o:
            return JSONResponse({"error": "not_found"}, status_code=404)
        if not authz.can_read_order(gw(), c, o):
            raise auth.AuthError(403, "forbidden", "This credential belongs to another customer account.")
        ok, payload, detail = verify_jws(o["confirmation"]["jws"], gw().jwks()["keys"])
        return JSONResponse({**o, "confirmationVerified": ok, "confirmationPayload": payload})

    # ---------------------------------------------------------------- approvals: named humans only
    @guarded
    async def approval_inbox(req: Request):
        c = caller(req, "human")
        return JSONResponse({"for": c.name, "pending": inbox_for(gw(), c.person_id, c.buyer_id)})

    @guarded
    async def audit_ep(req: Request):
        c = caller(req, "agent", "human", "ops")
        ev = gw().audit.events_for(c, trace_id=req.query_params.get("sessionId"))
        full = c.kind == "ops" and req.query_params.get("full") == "1"  # ops: re-hash the whole chain from genesis
        return JSONResponse({"verify": await off_loop(gw().audit.verify, full=full), "events": ev})

    @guarded
    async def ops_metrics(req: Request):
        caller(req, "ops")
        return JSONResponse(await off_loop(ops.metrics, gw()))

    @guarded
    async def ops_demand(req: Request):
        caller(req, "ops")
        q = req.query_params
        return JSONResponse(await off_loop(ops.demand, gw(), q.get("from"), q.get("to"), q.get("by", "day")))

    @guarded
    async def ops_lost_sales(req: Request):
        caller(req, "ops")
        q = req.query_params
        return JSONResponse(await off_loop(ops.lost_sales, gw(), q.get("from"), q.get("to")))

    @guarded
    async def ops_orders(req: Request):
        caller(req, "ops")
        return JSONResponse({"orders": [{k: v for k, v in o.items() if k != "confirmation"} | {"confirmationJws": o["confirmation"]["jws"]}
                                        for o in gw().orders.values()]})

    @guarded
    async def ops_inventory(req: Request):
        caller(req, "ops")
        be = gw().backend
        want = [g for g in (req.query_params.get("gtins") or "").split(",") if g] or list(be.stock)
        return JSONResponse({"asOf": gw().clock.now().isoformat(),
                             "inventory": {g: {"stock": be.stock.get(g, 0), "schedule": be.schedule(g)} for g in want if g in be.stock}})

    @guarded
    async def demo_clock(req: Request):
        c = caller(req, "ops", "user")
        if c.kind != "ops" and not auth.demo_mode():
            raise auth.AuthError(403, "forbidden", "Moving the clock needs the operations credential outside demo mode.")
        b = await body(req)
        mins = float(b.get("advanceMinutes", 0))
        if not 0 <= mins <= 60 * 24 * 40:
            raise PlaybookError("advanceMinutes is 0 to 57600.", fix={"example": {"advanceMinutes": 16}})
        now = gw().clock.advance(mins)
        gw().audit.append(trace_id=None, actor=c.label, action="demo.clock", buyer_id=None, reason=f"clock moved {mins:g} min")
        return JSONResponse({"now": now.isoformat()})

    @guarded
    async def ops_metrics_raw(req: Request):
        caller(req, "ops")
        return JSONResponse(gw().metrics.snapshot(gw()))

    @guarded
    async def ops_pause(req: Request):
        c = caller(req, "ops")
        b = await body(req)
        aid = req.path_params["aid"]
        paused = bool(b.get("paused", True))
        gw().kill_switch[aid] = paused
        gw().save()
        gw().audit.append(trace_id=None, actor=c.label, action="agent.paused" if paused else "agent.resumed", buyer_id=None,
                          refs={"agentId": aid}, reason=b.get("reason") or "operations decision")
        return JSONResponse({"agentId": aid, "paused": paused})

    # ---------------------------------------------------------------- discovery
    def base_of(req: Request) -> str:
        return str(req.base_url).rstrip("/")

    async def ucp(req: Request):
        return JSONResponse(discovery.ucp_profile(base_of(req)))

    async def agent_card(req: Request):
        card = discovery.agent_card(base_of(req))
        card["signatures"] = [{"format": "JWS", "alg": "ES256", "kid": gw().gateway_key.kid,
                               "jws": gw().gateway_key.sign(card, typ="agent-card+jwt")}]
        return JSONResponse(card)

    async def openapi_ep(req: Request):
        return JSONResponse(discovery.openapi(base_of(req)))

    @guarded
    async def approvals(req: Request):
        c = caller(req, "human")
        key = req.path_params["sid"]
        sid = gw().approvals.get(key, key)
        s = gw().engine.session(sid)
        auth.same_buyer(c, s["buyerId"])
        b = await body(req)
        key = req.headers.get("idempotency-key") or b.pop("idempotencyKey", None)
        if not isinstance(b.get("ok"), bool):
            raise GuardFailed("Send the decision as a JSON boolean: ok true to approve, false to decline.", guard="bad_input",
                              fix={"example": {"ok": True, "note": "Big week, fine."}})
        ok = b["ok"]

        def decide() -> dict:
            conv = next((cv for cv in agent().convs.values() if sid in cv["sessionIds"]), None)
            if conv:  # a chat order: the chef assistant places it straight after the OK
                cards = agent().decide(sid, ok, c.person_id)
                agent()._say(conv, cards, sid)
                return {"approval": s["data"]["approval"], "cards": cards, "conversation": agent().public(conv)}
            appr = decide_approval(gw(), s, ok, {"id": c.person_id, "name": c.name}, b.get("note"))
            return {"approval": appr, "next": "The agent may now call place_order." if ok else "The order stays unplaced."}

        return replay(await off_loop(gw().engine.idempotent, f"{sid}|approval|{c.person_id}", key, b, decide))

    # ---------------------------------------------------------------- chef app (a buyer's own staff, signed in)
    def buyer_of(req: Request, *kinds: str, bid: str | None = None) -> tuple[auth.Caller, str]:
        """The chef app's caller (a buyer user or approver) and the buyer it may see: always its own."""
        c = caller(req, *(kinds or ("user", "human")))
        b = bid or req.query_params.get("buyerId") or c.buyer_id
        auth.same_buyer(c, b)
        return c, b

    def own_conv(req: Request, cid: str) -> tuple[auth.Caller, dict]:
        c = caller(req, "user", "human")
        cv = agent().convs.get(cid)
        if not cv:
            raise NotFound(f"No conversation {cid}.", fix={"call": "GET /v1/chats"})
        auth.same_buyer(c, cv["buyerId"])
        return c, cv

    @guarded
    async def chat(req: Request):
        b = await body(req)
        if b.get("conversationId"):
            c, cv = own_conv(req, b["conversationId"])
            bid = cv["buyerId"]
        else:
            c, bid = buyer_of(req, bid=b.get("buyerId"))
        return JSONResponse(await off_loop(agent().message, b.get("conversationId"), b["text"], bid))

    @guarded
    async def chat_action(req: Request):
        b = await body(req)
        c, cv = own_conv(req, req.path_params["cid"])
        if b.get("action") in ("approve", "decline"):  # a named approver's decision: their own credential, never a name in the body
            if c.kind != "human":
                raise auth.AuthError(403, "forbidden", "Only a named approver, with their own credential, can approve or decline.")
            if b["action"] == "decline":
                sid = (b.get("payload") or {}).get("sessionId") or cv["sessionIds"][-1]
                if sid not in cv["sessionIds"]:
                    raise NotFound("That order is not part of this conversation.", fix={"call": "GET /v1/chats/{id}"})
                cards = agent().decide(sid, False, c.person_id)
                agent()._say(cv, cards, sid)
                return JSONResponse({"conversation": agent().public(cv), "cards": cards})
            return JSONResponse(await off_loop(agent().action, cv["id"], "approve", b.get("payload"), c.person_id))
        return JSONResponse(await off_loop(agent().action, cv["id"], b["action"], b.get("payload")))

    @guarded
    async def chats(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse({"chats": agent().list(bid)})

    @guarded
    async def chat_get(req: Request):
        _, cv = own_conv(req, req.path_params["cid"])
        return JSONResponse(agent().public(cv))

    @guarded
    async def board(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse(agent().board(bid))

    @guarded
    async def insights_ep(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse(insights.for_buyer(gw(), bid))

    @guarded
    async def settings_ep(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse(insights.settings(gw(), bid))

    async def search(req: Request):
        b = await body(req)
        if b.get("source") == "valio-aimo":
            return JSONResponse(aimo_products.search(b.get("query", ""), b.get("excludeAllergens"), b.get("diet")))
        return JSONResponse(catalog.search(b.get("query", ""), b.get("category"), b.get("diet"), b.get("excludeAllergens")))

    @guarded
    async def reset(req: Request):
        c = caller(req, "ops", "user", "human")
        if c.kind != "ops" and not auth.demo_mode():
            raise auth.AuthError(403, "forbidden", "Reset needs the operations credential outside demo mode.")
        boot(fresh=True)
        gw().audit.append(trace_id=None, actor=c.label, action="demo.reset", buyer_id=None, reason="demo data reset")
        return JSONResponse({"ok": True})

    async def rules_ep(_):
        return JSONResponse(published_rules(gw()))

    async def jwks(_):
        return JSONResponse(gw().jwks())

    # ---------------------------------------------------------------- insights, history, kitchens
    async def tools_ep(_):
        return JSONResponse(manifest.tools())

    async def insight_playbook_ep(_):
        return JSONResponse(insight_engine.public())

    @guarded
    async def insight_sessions(req: Request):
        c = caller(req, "agent", "user", "human")
        b = await body(req)
        bid = b.get("buyerId") or c.buyer_id
        auth.same_buyer(c, bid)
        args = {**b, "buyerId": bid, "agent": "analyst" if c.kind != "agent" else (c.agent_id or "").split(":")[-1]}
        return JSONResponse(await off_loop(gw().insights.call, None, "start_analysis", args), status_code=201)

    @guarded
    async def insight_tool(req: Request):
        c = caller(req, "agent", "user", "human")
        s = gw().insights.sessions.get(req.path_params["sid"])
        if s and not authz.can_read_analysis(c, s):
            raise auth.AuthError(403, "forbidden", "This analysis belongs to another customer account.")
        return JSONResponse(await off_loop(gw().insights.call, req.path_params["sid"], req.path_params["tool"], await body(req)))

    @guarded
    async def ask(req: Request):
        b = await body(req)
        _, bid = buyer_of(req, bid=b.get("buyerId"))
        validate_input(ASK_FILTERS, "ask", b.get("filters") or {})
        return JSONResponse(await off_loop(state["analyst"].ask, b.get("prompt", ""), b.get("filters") or {}, bid, b.get("siteId")))

    @guarded
    async def wrapped(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse(views.wrapped(gw(), bid, req.query_params.get("siteId")))

    @guarded
    async def history(req: Request):
        _, bid = buyer_of(req)
        qp = req.query_params
        try:
            return JSONResponse(views.order_history(gw(), bid, int(qp.get("page", 1)), min(200, int(qp.get("size", 50))),
                                                    qp.get("q"), qp.get("siteId"), qp.get("type"), qp.get("sort", "date"), qp.get("dir", "desc")))
        except ValueError as e:
            return JSONResponse({"error": "bad_request", "message": str(e), "fix": {"example": "?page=1&size=50"}}, status_code=400)

    @guarded
    async def kitchens_ep(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse(views.kitchens(gw(), bid))

    @guarded
    async def order_detail(req: Request):
        _, bid = buyer_of(req)
        return JSONResponse(views.order_detail(gw(), bid, req.path_params["oid"]))

    @guarded
    async def activity(req: Request):
        c = caller(req, "user", "human", "agent", "ops")
        s = gw().engine.session(req.path_params["sid"])
        auth.same_buyer(c, s["buyerId"])
        return JSONResponse({"activity": state["agent"].activity(s["sessionId"])})

    # MCP over Streamable HTTP on THIS gateway: an MCP agent shares sessions, approvals, stock and audit with REST
    from . import mcp_app
    mcp_asgi, mcp_srv = mcp_app.http_app(gw, lambda: state["analyst"],
                                         os.environ.get("AIMO_PUBLIC_URL", "http://127.0.0.1:" + os.environ.get("PORT", "8000")))

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # worker threads: every long-poll slot plus room for normal calls (engine, lookup, adapter)
        anyio.to_thread.current_default_thread_limiter().total_tokens = gw().events.max_waiters + 64
        async with mcp_srv.session_manager.run():
            yield

    app = Starlette(lifespan=lifespan, routes=[
        Route("/v1/orders/history/{oid}", order_detail), Route("/v1/orders/{sid}/activity", activity),
        Route("/v1/tools", tools_ep), Route("/v1/insights/playbook", insight_playbook_ep),
        Route("/v1/insights/sessions", insight_sessions, methods=["POST"]),
        Route("/v1/insights/sessions/{sid}/tools/{tool}", insight_tool, methods=["POST"]),
        Route("/v1/insights/ask", ask, methods=["POST"]), Route("/v1/insights/wrapped", wrapped),
        Route("/v1/orders/history", history), Route("/v1/kitchens", kitchens_ep),
        Route("/", index), Route("/health", health), Route("/.well-known/jwks.json", jwks),
        Route("/v1/playbook", playbook_ep), Route("/v1/sessions", sessions, methods=["POST"]),
        Route("/v1/sessions/{sid}", session_get), Route("/v1/sessions/{sid}/tools/{tool}", tool, methods=["POST"]),
        Route("/v1/approvals/{sid}", approvals, methods=["POST"]), Route("/v1/audit", audit_ep),
        Route("/v1/chat", chat, methods=["POST"]), Route("/v1/chat/{cid}/actions", chat_action, methods=["POST"]),
        Route("/v1/chats", chats), Route("/v1/chats/{cid}", chat_get), Route("/v1/board", board),
        Route("/v1/insights", insights_ep), Route("/v1/settings", settings_ep),
        Route("/v1/catalog/search", search, methods=["POST"]), Route("/v1/rules", rules_ep),
        Route("/v1/demo/reset", reset, methods=["POST"]),
        Route("/.well-known/ucp", ucp), Route("/.well-known/agent-card.json", agent_card), Route("/openapi.json", openapi_ep),
        Route("/v1/products/search", product_search, methods=["POST"]),
        Route("/v1/products/price-availability", price_availability, methods=["POST"]),
        Route("/v1/products/{pid}", product_get), Route("/v1/mandate", mandate_ep),
        Route("/v1/suggestions", suggestions), Route("/v1/suggestions/{sgid}/feedback", suggestion_feedback, methods=["POST"]),
        Route("/v1/sessions/{sid}/log", session_log), Route("/v1/sessions/{sid}/events", session_events),
        Route("/v1/offers/{oid}", offer_get), Route("/v1/offers/{oid}/verify", offer_verify, methods=["POST"]),
        Route("/v1/orders/{oid}", order_get), Route("/v1/approvals", approval_inbox),
        Route("/v1/ops/agents/{aid}/pause", ops_pause, methods=["POST"]), Route("/v1/ops/metrics-raw", ops_metrics_raw),
        Route("/v1/ops/orders", ops_orders), Route("/v1/ops/metrics", ops_metrics), Route("/v1/ops/demand", ops_demand),
        Route("/v1/ops/lost-sales", ops_lost_sales), Route("/v1/ops/inventory", ops_inventory),
        Route("/v1/demo/clock", demo_clock, methods=["POST"]),
        Route("/mcp", _Asgi(mcp_asgi), methods=["GET", "POST", "DELETE"]), Mount("/mcp", app=mcp_asgi),
    ])
    app.add_middleware(RequestLog, metrics_of=lambda: gw().metrics)
    app.state.gw = gw  # the live Gateway (replaced on /v1/demo/reset); used by tests and tools
    return app


app = make_app(live=os.environ.get("AIMO_LIVE", "1") == "1")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # aimo.gateway emits one JSON line per request
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
