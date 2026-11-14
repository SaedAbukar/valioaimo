"""Act, part 2: the OK request to a named human and that human's decision (never an agent's).

request_approval is a playbook tool (the agent asks); decide_approval is NOT a tool: only a named approver's
own credential reaches it (REST /v1/approvals, the chef app's approver). inbox_for lists what waits for a person.
"""
from __future__ import annotations

from ..util import iso, new_id
from .engine import GuardFailed


def _approver(gw, bid):
    b = gw.buyers[bid]
    a = b["approvers"][0]
    return {"id": a["id"], "name": a["name"], "role": a["role"]}


def request_approval(gw, s: dict, args: dict) -> dict:
    from .tools import _lock_prices  # prices and stock still hold before a human is asked
    d = s["data"]
    _lock_prices(gw, s)
    ap = _approver(gw, s["buyerId"])
    d["approval"] = {"approvalId": new_id("APR"), "status": "pending", "approver": ap, "requestedAt": iso(gw.clock.now()),
                     "reasons": d["decision"]["reasons"], "total": d["plan"]["total"]}
    gw.approvals[d["approval"]["approvalId"]] = s["sessionId"]
    # the request reaches a named human: their inbox (GET /v1/approvals with their credential)
    gw.inbox.append({"to": ap["id"], "name": ap["name"], "buyerId": s["buyerId"], "approvalId": d["approval"]["approvalId"],
                     "sessionId": s["sessionId"], "at": d["approval"]["requestedAt"]})
    gw.audit.append(trace_id=s["sessionId"], actor="system:gateway", action="approval.notified", buyer_id=s["buyerId"],
                    refs={"approvalId": d["approval"]["approvalId"], "to": ap["id"]},
                    reason=f"Asked {ap['name']} ({ap['role']}) for an OK: {'; '.join(d['decision']['reasons'])}")
    return {"status": "waiting_for_ok", "approval": d["approval"]}


def decide_approval(gw, s: dict, ok: bool, person: dict, note: str | None = None) -> dict:
    """A named approver's decision. Not a playbook tool: agents cannot call it (auth + MCP have no such tool)."""
    appr = (s["data"].get("approval") or {})
    if appr.get("status") != "pending":
        raise GuardFailed("There is no pending approval for this order.", guard="pending_approval")
    if person["id"] not in {a["id"] for a in gw.buyers[s["buyerId"]]["approvers"]}:
        raise GuardFailed(f"{person.get('name', person['id'])} is not an approver for this customer.", guard="named_approver")
    appr.update({"status": "approved" if ok else "rejected", "decidedBy": person["name"], "decidedById": person["id"],
                 "decidedAt": iso(gw.clock.now()), "note": note})
    gw.inbox[:] = [m for m in gw.inbox if m["approvalId"] != appr["approvalId"]]
    gw.audit.append(trace_id=s["sessionId"], actor=f"human:{person['name']}", action="approved" if ok else "rejected",
                    buyer_id=s["buyerId"], refs={"approvalId": appr["approvalId"], "step": "act", "personId": person["id"]},
                    decision="APPROVE" if ok else "REJECT",
                    reason=f"{person['name']} {'approved' if ok else 'declined'} the order" + (f": {note}" if note else ""))
    gw.events.emit(s["sessionId"], "approval.decided", {"approvalId": appr["approvalId"], "status": appr["status"],
                                                         "decidedBy": person["name"], "next_allowed_tools": gw.engine.allowed(s)})
    gw.save()
    return appr


def inbox_for(gw, person_id: str, buyer_id: str) -> list[dict]:
    """Approval requests waiting for this person (addressed to them, or to their buyer if they are an approver)."""
    is_approver = any(a["id"] == person_id for a in gw.buyers[buyer_id]["approvers"])
    out = []
    for m in gw.inbox:
        if m["to"] == person_id or (m["buyerId"] == buyer_id and is_approver):
            s = gw.engine.session(m["sessionId"])
            out.append({**m, "approval": s["data"]["approval"],
                        "lines": [{k: l[k] for k in ("name", "qty", "unit", "lineTotal", "deliveryDate")} for l in s["data"]["plan"]["lines"]]})
    return out
