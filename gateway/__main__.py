"""Thin reference server: `python -m gateway` → http://127.0.0.1:8000

Serves the clickable MVP (ui/dist/index.html) plus a handful of reference endpoints
over the Python core (discovery, planning with policy preview, policy evaluation,
audit verification). The full contract is sketched in docs/API.md; the MVP page
runs the same logic client-side so it also works with no server at all.
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import catalog
from .core import Gateway
from .policy import rules

ROOT = Path(__file__).resolve().parent.parent
GW = Gateway()


async def index(_):
    return FileResponse(ROOT / "ui" / "dist" / "index.html")


async def jwks(_):
    return JSONResponse(GW.jwks())


async def ucp(_):
    return JSONResponse({
        "name": "Aimo Agent Gateway", "version": "0.1", "protocols": ["rest", "mcp"],
        "capabilities": ["catalog.search", "offers.signed", "plans", "checkout", "approvals", "orders", "mandates",
                         "audit", "events.autopilot", "insights"],
        "openapi": "/openapi.json", "jwks": "/.well-known/jwks.json", "agentCard": "/.well-known/agent-card.json",
        "trust": {"offerFormat": "vc+jwt (W3C VC 2.0, ES256)", "priceValidityMin": 15, "stockFreshnessMin": 5},
    })


async def agent_card(_):
    card = {"name": "Aimo Agent Gateway (seller agent)", "url": "http://127.0.0.1:8000", "skills": [
        {"id": "plan_fulfilment", "description": "Ranked, signed offers and up to three plans with a policy preview"},
        {"id": "plan_event_from_brief", "description": "Event Autopilot: brief → basket → one decision"}]}
    return JSONResponse({"card": card, "jws": GW.gateway_key.sign(card, typ="agent-card+jwt")})


async def search(req: Request):
    body = await req.json()
    return JSONResponse(catalog.search(body.get("query", ""), body.get("category"), body.get("diet"),
                                       body.get("excludeAllergens")))


async def plans(req: Request):
    b = await req.json()
    return JSONResponse(GW.plan(b.get("buyerId", "BUY-POHJOLA"), b["lines"], b["needBy"], b.get("choices")))


async def rules_ep(_):
    return JSONResponse({"precedence": rules()["precedence"], "rules": rules()["rules"]})


async def audit_verify(_):
    return JSONResponse(GW.audit.verify())


async def openapi(_):
    return JSONResponse({
        "openapi": "3.1.0", "info": {"title": "Aimo Agent Gateway (reference sketch)", "version": "0.1"},
        "paths": {
            "/v1/catalog/search": {"post": {"summary": "L0 catalog search (browse-only)"}},
            "/v1/plans": {"post": {"summary": "Signed offers, ranked candidates, up to 3 plans, policy preview"}},
            "/v1/rules": {"get": {"summary": "Guardrail rule table"}},
            "/v1/audit/verify": {"get": {"summary": "Verify the SHA-256 audit hash chain"}},
        },
        "x-full-contract": "docs/API.md"})


app = Starlette(routes=[
    Route("/", index), Route("/.well-known/jwks.json", jwks), Route("/.well-known/ucp", ucp),
    Route("/.well-known/agent-card.json", agent_card), Route("/openapi.json", openapi),
    Route("/v1/catalog/search", search, methods=["POST"]), Route("/v1/plans", plans, methods=["POST"]),
    Route("/v1/rules", rules_ep), Route("/v1/audit/verify", audit_verify),
])

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
