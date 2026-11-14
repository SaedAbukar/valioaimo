"""How an agent finds and trusts the gateway: /.well-known documents and OpenAPI 3.1.

  /.well-known/ucp              UCP-style business profile: services, capabilities, endpoints
  /.well-known/agent-card.json  A2A agent card (signed with the gateway key)
  /.well-known/jwks.json        keys that sign offers, order confirmations and the card
  /openapi.json                 OpenAPI 3.1 contract of the agent-facing REST API
"""
from __future__ import annotations

from .playbook.engine import playbook, public_playbook

VERSION = "0.4.0"
NAME = "Valio Aimo agent gateway (Junction 2026 prototype)"


def ucp_profile(base: str) -> dict:
    return {
        "ucp": {
            "version": "2026-01",
            "services": {"dev.ucp.shopping": {
                "version": "2026-01",
                "rest": {"schema": f"{base}/openapi.json", "endpoint": f"{base}/v1"},
                "mcp": {"transport": "stdio", "command": "python -m gateway.mcp_server",
                        "auth": "AIMO_AGENT_TOKEN (the agent's bearer token)"},
                "a2a": {"agentCard": f"{base}/.well-known/agent-card.json"}}},
            "capabilities": [
                {"name": "dev.ucp.shopping.catalog", "spec": "POST /v1/products/search, POST /v1/products/price-availability"},
                {"name": "dev.ucp.shopping.checkout", "spec": "playbook session: plan_basket -> check_basket -> place_order (cites signed offers)"},
                {"name": "dev.ucp.shopping.order", "spec": "GET /v1/orders/{orderId}: signed order confirmation"},
                {"name": "com.valioaimo.approval", "spec": "request_approval -> named human -> POST /v1/approvals/{approvalId}"},
                {"name": "com.valioaimo.playbook", "spec": "GET /v1/playbook (enforced order of steps)"},
            ]},
        "business": {"name": "Valio Aimo", "country": "FI", "currency": "EUR", "pricing": "fixed list and customer prices, no negotiation",
                     "payment": "invoice on the customer account (no card or crypto payment)"},
        "trust": {"jwks_uri": f"{base}/.well-known/jwks.json", "offerFormat": "W3C VC 2.0 as vc+jwt (ES256), valid 15 min",
                  "orderConfirmation": "order+jwt (ES256)", "buyerAuthority": "IntentMandate signed by a named buyer admin (GET /v1/mandate)"},
        "auth": {"type": "http", "scheme": "bearer", "bindsTo": "one customer account (buyerId) and one registered agent"},
        "rules": f"{base}/v1/rules",
        "playbook": {"url": f"{base}/v1/playbook", "version": public_playbook()["version"]},
        "exposure": "docs/EXPOSURE.md: what an agent may and may not see",
    }


def agent_card(base: str) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": NAME,
        "description": "Look up Valio Aimo products with price and availability, get signed fixed-price offers, "
                       "order within the buyer's signed authority or route to a named human for approval.",
        "url": f"{base}/v1", "preferredTransport": "HTTP+JSON", "version": VERSION,
        "provider": {"organization": "Valio Aimo (prototype)", "url": base},
        "documentationUrl": f"{base}/openapi.json",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["application/json", "text/plain"], "defaultOutputModes": ["application/json"],
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}, "security": [{"bearer": []}],
        "skills": [
            {"id": "product-lookup", "name": "Product, price and availability lookup", "tags": ["catalog", "price", "availability"],
             "description": "Search the assortment; price per sales unit and per kg/L, delivery status for a need-by date.",
             "examples": ["lactose-free milk, 1000 L by 2026-11-16"]},
            {"id": "order", "name": "Order through the playbook", "tags": ["checkout", "order"],
             "description": "Understand -> Recall -> Discover -> Plan -> Check -> Present -> Act -> Learn, enforced.",
             "examples": ["I need 1,000 litres of lactose-free milk by Monday."]},
            {"id": "approval", "name": "Human approval", "tags": ["approval", "guardrails"],
             "description": "Orders outside the agent's authority go to a named approver; the decision is signed into the log."},
        ],
    }


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _json(schema: dict, desc: str = "OK") -> dict:
    return {"description": desc, "content": {"application/json": {"schema": schema}}}


ERRORS = {"401": _json(_ref("Error"), "No or unknown credential"), "403": _json(_ref("Error"), "Credential not allowed here"),
          "409": _json(_ref("Error"), "step_not_allowed: out of order, see next_allowed_tools"),
          "422": _json(_ref("Error"), "guard_failed: bad input, see fix"),
          "429": {**_json(_ref("Error"), "rate_limited: wait retryAfter seconds (per credential; operations exempt)"),
                  "headers": {"Retry-After": {"schema": {"type": "integer"}, "description": "Seconds (RFC 9110)"}}}}


def _op(summary: str, tag: str, resp: dict, body: dict | None = None, params: list | None = None, auth: bool = True,
        errors: tuple = ("401", "403")) -> dict:
    op = {"summary": summary, "tags": [tag], "responses": {"200": resp, **{k: ERRORS[k] for k in errors + ("429",)}}}
    if body:
        op["requestBody"] = {"required": True, "content": {"application/json": {"schema": body}}}
    if params:
        op["parameters"] = params
    if not auth:
        op["security"] = []
        op["responses"] = {"200": resp}
    return op


def _p(name: str, where: str = "path", desc: str = "") -> dict:
    return {"name": name, "in": where, "required": where == "path", "schema": {"type": "string"}, "description": desc}


IDEMPOTENCY_KEY = _p("Idempotency-Key", "header",
                     "Optional (IETF draft-ietf-httpapi-idempotency-key-header). A retry with the same key and body returns the "
                     "stored response with 'Idempotent-Replay: true'; the same key with another body is 422 idempotency_conflict. "
                     "Applies to place_order, request_approval, record_usage and approval decisions; kept 24 h.")


SCHEMAS = {
    "Error": {"type": "object", "required": ["error"], "properties": {
        "error": {"type": "string"}, "message": {"type": "string"}, "guard": {"type": "string"},
        "next_allowed_tools": {"type": "array", "items": {"type": "string"}}, "fix": {}}},
    "ProductSearch": {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string", "examples": ["lactose-free milk"]}, "qty": {"type": "number", "description": "kg, L or pieces"},
        "needBy": {"type": "string", "format": "date"}, "excludeAllergens": {"type": "array", "items": {"type": "string"}},
        "diet": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}},
    "PriceAvailabilityRequest": {"type": "object", "required": ["productIds"], "properties": {
        "productIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "needBy": {"type": "string", "format": "date"}, "qty": {"type": "number"}}},
    "Product": {"type": "object", "required": ["productId", "name", "price", "availability"], "properties": {
        "productId": {"type": "string"}, "gtin": {"type": ["string", "null"]}, "name": {"type": "string"}, "brand": {"type": ["string", "null"]},
        "content": {"type": "object", "properties": {"perSalesUnit": {"type": "number"}, "unit": {"enum": ["L", "kg", "pcs"]}}},
        "price": {"type": "object", "properties": {"perSalesUnit": {"type": "number"}, "perUnit": {"type": "number"},
                                                    "currency": {"const": "EUR"}, "validTo": {"type": ["string", "null"]},
                                                    "source": {"enum": ["valio-aimo-mock-api", "demo-values"]}}},
        "availability": {"type": "object", "properties": {
            "status": {"enum": ["available", "partial", "not_by_date", "not_deliverable"]},
            "earliestDelivery": {"type": ["string", "null"]}, "canCoverQty": {"type": ["number", "null"]},
            "orderCutoff": {"type": ["string", "null"]}}},
        "deliveryReliability": {"type": ["number", "null"]}, "co2eKgPerKg": {"type": ["number", "null"]},
        "allergens": {"type": "object"}, "diet": {"type": "array", "items": {"type": "string"}},
        "tag": {"enum": ["best_price", "most_reliable", "lowest_co2"]}}},
    "ProductList": {"type": "object", "properties": {"products": {"type": "array", "items": _ref("Product")},
                                                     "needBy": {"type": "string"}, "live": {"type": "boolean"}}},
    "StartSession": {"type": "object", "properties": {"buyerId": {"type": "string", "description": "defaults to the credential's buyer"}}},
    "ToolResult": {"type": "object", "required": ["tool", "output", "next_allowed_tools"], "properties": {
        "tool": {"type": "string"}, "step": {"type": "string"}, "sessionId": {"type": "string"}, "output": {"type": "object"},
        "next_allowed_tools": {"type": "array", "items": {"type": "string"}}, "playbookVersion": {"type": "string"}}},
    "PlaceOrderArgs": {"type": "object", "required": ["offerIds"], "properties": {
        "offerIds": {"type": "array", "items": {"type": "string"}, "description": "exactly the signed offers of the checked basket"}},
        "description": "Body of POST /v1/sessions/{id}/tools/place_order. Price fields are rejected: no negotiation."},
    "Offer": {"type": "object", "required": ["offerId", "unitPrice", "validUntil", "proof"], "properties": {
        "offerId": {"type": "string"}, "gtin": {"type": "string"}, "unitPrice": {"type": "number"}, "unit": {"type": "string"},
        "validUntil": {"type": "string", "format": "date-time"}, "priceSource": {"type": "string"},
        "proof": {"type": "object", "properties": {"format": {"const": "vc+jwt"}, "alg": {"const": "ES256"}, "jws": {"type": "string"}}}}},
    "OfferVerification": {"type": "object", "properties": {"verified": {"type": "boolean"}, "checks": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "ok": {"type": "boolean"}, "detail": {"type": "string"}}}}}},
    "Order": {"type": "object", "properties": {
        "orderId": {"type": "string"}, "status": {"type": "string"}, "total": {"type": "number"},
        "lines": {"type": "array", "items": {"type": "object"}},
        "confirmation": {"type": "object", "properties": {"format": {"const": "order+jwt"}, "jws": {"type": "string"}}}}},
    "ApprovalDecision": {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}}},
    "Rules": {"type": "object", "properties": {"autonomy": {"type": "object"}, "rules": {"type": "array"}}},
}


def _tool_inputs() -> dict:
    """Component schemas Input_<tool> from the playbook (1.1.0), one per order tool."""
    out = {}
    for t, sch in playbook()["inputs"].items():
        x = {k: v for k, v in sch.items() if k != "examples"}
        x["examples"] = sch.get("examples", [])
        out[f"Input_{t}"] = x
    return out


def openapi(base: str = "") -> dict:
    T = "Discovery"
    inputs = _tool_inputs()
    tool_body = {"anyOf": [_ref(k) for k in inputs],
                 "description": "The input of the tool named in the path: Input_<tool>. Validated before the tool runs "
                                "(422 bad_input with fix.expected and fix.example). anyOf, not oneOf: several tools take {}."}
    tool_params = [_p("sessionId"), {"name": "tool", "in": "path", "required": True,
                                     "schema": {"enum": sorted(playbook()["toolStep"])}}]
    paths = {
        "/.well-known/ucp": {"get": _op("UCP-style business profile", T, _json({"type": "object"}), auth=False)},
        "/.well-known/agent-card.json": {"get": _op("A2A agent card (signed)", T, _json({"type": "object"}), auth=False)},
        "/.well-known/jwks.json": {"get": _op("Gateway signing keys (ES256)", T, _json({"type": "object"}), auth=False)},
        "/openapi.json": {"get": _op("This contract", T, _json({"type": "object"}), auth=False)},
        "/health": {"get": _op("Liveness and whether the Valio Aimo mock API is reachable", T, _json({"type": "object"}), auth=False)},
        "/v1/rules": {"get": _op("Published guardrails: what the agent decides alone and what needs a human", "Rules", _json(_ref("Rules")), auth=False)},
        "/v1/playbook": {"get": _op("The order playbook every agent follows (enforced)", "Playbook", _json({"type": "object"}), auth=False)},
        "/v1/tools": {"get": _op("Every tool in order, REST and MCP names", "Playbook", _json({"type": "object"}), auth=False)},
        "/v1/products/search": {"post": _op("Search products with price and availability", "Lookup", _json(_ref("ProductList")), _ref("ProductSearch"))},
        "/v1/products/price-availability": {"post": _op("Price and availability for known product ids", "Lookup", _json(_ref("ProductList")), _ref("PriceAvailabilityRequest"))},
        "/v1/products/{productId}": {"get": _op("Product master data", "Lookup", _json({"type": "object"}), params=[_p("productId")])},
        "/v1/mandate": {"get": _op("The buyer's signed mandate (agent authority) and the buyer key to verify it", "Trust", _json({"type": "object"}))},
        "/v1/sessions": {"post": _op("Step 0: start a playbook session", "Playbook", _json(_ref("ToolResult")), _ref("StartSession"), errors=("401", "403", "422"))},
        "/v1/sessions/{sessionId}": {"get": _op("Session state, outputs per step, next_allowed_tools", "Playbook", _json({"type": "object"}), params=[_p("sessionId")])},
        "/v1/sessions/{sessionId}/tools/{tool}": {"post": _op("Run one playbook tool (place_order needs PlaceOrderArgs)", "Playbook",
                                                               _json(_ref("ToolResult")), tool_body, tool_params + [IDEMPOTENCY_KEY], errors=("401", "403", "409", "422"))},
        "/v1/sessions/{sessionId}/events": {"get": _op("Push updates: long-poll the session's events (step.completed, decision.made, "
                                                       "approval.requested, approval.decided, order.placed, offer.expiring, suggestion.created)",
                                                       "Playbook", _json({"type": "object", "properties": {
                                                           "events": {"type": "array", "items": {"type": "object"}}, "next": {"type": "integer"},
                                                           "next_allowed_tools": {"type": "array", "items": {"type": "string"}}}}),
                                                       params=[_p("sessionId"), _p("after", "query", "last seq seen (cursor); default 0"),
                                                               _p("wait", "query", "seconds to wait for a new event, 0-25")], errors=("401", "403", "422"))},
        "/v1/sessions/{sessionId}/log": {"get": _op("Plain-language log of what the agent did and why", "Audit", _json({"type": "object"}), params=[_p("sessionId")])},
        "/v1/offers/{offerId}": {"get": _op("A signed offer (vc+jwt)", "Offers", _json(_ref("Offer")), params=[_p("offerId")])},
        "/v1/offers/{offerId}/verify": {"post": _op("Six trust checks on an offer: signature, validity, freshness, binding, status, live re-check",
                                                    "Offers", _json(_ref("OfferVerification")), params=[_p("offerId")])},
        "/v1/orders/{orderId}": {"get": _op("Order with its signed confirmation (order+jwt)", "Orders", _json(_ref("Order")), params=[_p("orderId")])},
        "/v1/approvals": {"get": _op("Approver inbox (human credential)", "Approvals", _json({"type": "object"}))},
        "/v1/approvals/{approvalId}": {"post": _op("Approve or decline (human credential; agents get 403)", "Approvals",
                                                   _json({"type": "object"}), _ref("ApprovalDecision"), [_p("approvalId"), IDEMPOTENCY_KEY], errors=("401", "403", "422"))},
        "/v1/audit": {"get": _op("Hash-chained audit log (own buyer; operations see all) and its verification", "Audit",
                                 _json({"type": "object"}), params=[_p("sessionId", "query")])},
        "/v1/ops/agents/{agentId}/pause": {"post": _op("Valio Aimo operations: pause or resume an agent (kill switch)", "Operations",
                                                       _json({"type": "object"}), {"type": "object", "properties": {"paused": {"type": "boolean"}}}, [_p("agentId")])},
    }
    return {
        "openapi": "3.1.0",
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "info": {"title": NAME, "version": VERSION,
                 "description": "Agent-facing interface to Valio Aimo: lookup, fixed-price signed offers, orders within a signed "
                                "mandate, human approval, audit. The playbook decides the order of calls; the gateway decides outcomes."},
        "servers": [{"url": base or "/"}],
        "security": [{"bearer": []}],
        "tags": [{"name": n} for n in ("Discovery", "Lookup", "Playbook", "Offers", "Orders", "Approvals", "Rules", "Trust", "Audit", "Operations")],
        "paths": paths,
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer",
                                                      "description": "Agent, approver or operations credential, bound to one customer account"}},
                       "schemas": {**SCHEMAS, **inputs}},
    }
