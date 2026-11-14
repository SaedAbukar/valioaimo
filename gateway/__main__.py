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

import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import aimo_products, catalog
from .adapter import load_dotenv
from .policy import rules

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from .core import Gateway  # noqa: E402  (after .env is loaded)
from .playbook import insights  # noqa: E402
from .playbook.agent import ChefAssistant  # noqa: E402
from .playbook.engine import PlaybookError, public_playbook  # noqa: E402
from . import manifest  # noqa: E402
from .analytics import engine as insight_engine, views  # noqa: E402
from .analytics.analyst import Analyst  # noqa: E402


DEMO_GALA = ("Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. "
             "12 vegan, 8 gluten-free, 1 nut allergy.")


def make_app(live: bool = True) -> Starlette:
    state = {}

    def boot():
        state["gw"] = Gateway(live=live)
        state["agent"] = ChefAssistant(state["gw"])
        state["analyst"] = Analyst(state["gw"])
        if os.environ.get("AIMO_SEED_DEMO", "1") == "1":  # the app opens on the gala example, already ordered
            r = state["agent"].message(None, DEMO_GALA, "BUY-POHJOLA")
            state["agent"].action(r["conversation"]["id"], "order")

    boot()
    gw = lambda: state["gw"]  # noqa: E731
    agent = lambda: state["agent"]  # noqa: E731

    def err(e: PlaybookError):
        return JSONResponse(e.body(), status_code=e.status)

    async def body(req: Request) -> dict:
        try:
            return await req.json()
        except Exception:  # noqa: BLE001
            return {}

    async def index(_):
        return FileResponse(ROOT / "ui" / "dist" / "index.html")

    async def health(_):
        g = gw()
        live_ok = g.aimo.ping() if g.aimo else False
        return JSONResponse({"ok": True, "playbookVersion": public_playbook()["version"], "products": aimo_products.count(),
                             "liveApi": {"configured": bool(g.aimo), "reachable": live_ok,
                                         "error": g.aimo.last_error if g.aimo else "AIMO_API_KEY not set"}})

    async def playbook_ep(_):
        return JSONResponse(public_playbook())

    async def sessions(req: Request):
        try:
            return JSONResponse(gw().engine.call(None, "start_session", await body(req)), status_code=201)
        except PlaybookError as e:
            return err(e)

    async def session_get(req: Request):
        try:
            E = gw().engine
            return JSONResponse(E.view(E.session(req.path_params["sid"])))
        except PlaybookError as e:
            return err(e)

    async def tool(req: Request):
        try:
            return JSONResponse(gw().engine.call(req.path_params["sid"], req.path_params["tool"], await body(req)))
        except PlaybookError as e:
            return err(e)

    async def audit_ep(req: Request):
        sid = req.query_params.get("sessionId")
        return JSONResponse({"verify": gw().audit.verify(), "events": gw().audit.events(trace_id=sid, limit=300)})

    async def approvals(req: Request):
        b = await body(req)
        try:
            cards = agent().decide(req.path_params["sid"], bool(b.get("ok", True)), b.get("by", "Laura Virtanen"))
        except PlaybookError as e:
            return err(e)
        conv = next((c for c in agent().convs.values() if req.path_params["sid"] in c["sessionIds"]), None)
        if conv:
            agent()._say(conv, cards, req.path_params["sid"])
        return JSONResponse({"cards": cards, "conversation": agent().public(conv) if conv else None})

    async def chat(req: Request):
        b = await body(req)
        try:
            return JSONResponse(agent().message(b.get("conversationId"), b["text"], b.get("buyerId", "BUY-POHJOLA")))
        except PlaybookError as e:
            return err(e)

    async def chat_action(req: Request):
        b = await body(req)
        try:
            return JSONResponse(agent().action(req.path_params["cid"], b["action"], b.get("payload"), b.get("by")))
        except PlaybookError as e:
            return err(e)

    async def chats(req: Request):
        return JSONResponse({"chats": agent().list(req.query_params.get("buyerId"))})

    async def chat_get(req: Request):
        c = agent().convs.get(req.path_params["cid"])
        return JSONResponse(agent().public(c)) if c else JSONResponse({"error": "not_found"}, status_code=404)

    async def board(req: Request):
        return JSONResponse(agent().board(req.query_params.get("buyerId")))

    async def insights_ep(req: Request):
        return JSONResponse(insights.for_buyer(gw(), req.query_params.get("buyerId", "BUY-POHJOLA")))

    async def settings_ep(req: Request):
        return JSONResponse(insights.settings(gw(), req.query_params.get("buyerId", "BUY-POHJOLA")))

    async def search(req: Request):
        b = await body(req)
        if b.get("source") == "valio-aimo":
            return JSONResponse(aimo_products.search(b.get("query", ""), b.get("excludeAllergens"), b.get("diet")))
        return JSONResponse(catalog.search(b.get("query", ""), b.get("category"), b.get("diet"), b.get("excludeAllergens")))

    async def reset(_):
        boot()
        return JSONResponse({"ok": True})

    async def rules_ep(_):
        return JSONResponse({"precedence": rules()["precedence"], "rules": rules()["rules"]})

    async def jwks(_):
        return JSONResponse(gw().jwks())

    # ---------------------------------------------------------------- insights, history, kitchens
    def bid_of(req):
        b = req.query_params.get("buyerId", "BUY-POHJOLA")
        if b not in gw().buyers:
            raise PlaybookError(f"Unknown buyer {b}.")
        return b

    async def tools_ep(_):
        return JSONResponse(manifest.tools())

    async def insight_playbook_ep(_):
        return JSONResponse(insight_engine.public())

    async def insight_sessions(req: Request):
        try:
            return JSONResponse(gw().insights.call(None, "start_analysis", await body(req)), status_code=201)
        except PlaybookError as e:
            return err(e)

    async def insight_tool(req: Request):
        try:
            return JSONResponse(gw().insights.call(req.path_params["sid"], req.path_params["tool"], await body(req)))
        except PlaybookError as e:
            return err(e)

    async def ask(req: Request):
        b = await body(req)
        try:
            return JSONResponse(state["analyst"].ask(b.get("prompt", ""), b.get("filters") or {}, b.get("buyerId", "BUY-POHJOLA"), b.get("siteId")))
        except PlaybookError as e:
            return err(e)

    async def wrapped(req: Request):
        try:
            return JSONResponse(views.wrapped(gw(), bid_of(req), req.query_params.get("siteId")))
        except PlaybookError as e:
            return err(e)

    async def history(req: Request):
        qp = req.query_params
        try:
            return JSONResponse(views.order_history(gw(), bid_of(req), int(qp.get("page", 1)), min(200, int(qp.get("size", 50))),
                                                    qp.get("q"), qp.get("siteId"), qp.get("type"), qp.get("sort", "date"), qp.get("dir", "desc")))
        except (PlaybookError, ValueError) as e:
            return JSONResponse({"error": "bad_request", "message": str(e)}, status_code=400)

    async def kitchens_ep(req: Request):
        try:
            return JSONResponse(views.kitchens(gw(), bid_of(req)))
        except PlaybookError as e:
            return err(e)

    async def order_detail(req: Request):
        return JSONResponse(views.order_detail(gw(), bid_of(req), req.path_params["oid"]))

    async def activity(req: Request):
        return JSONResponse({"activity": state["agent"].activity(req.path_params["sid"])})

    return Starlette(routes=[
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
    ])


app = make_app(live=os.environ.get("AIMO_LIVE", "1") == "1")

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
