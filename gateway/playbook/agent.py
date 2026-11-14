"""Built-in chef assistant: a reference agent that follows the playbook through the
same state machine as any external agent (it gets 409s like everyone else), and
turns each step into cards for the chat. Also keeps conversations and the board.

Board columns: Planning -> Waiting for OK -> Ordered -> Delivered -> Done.
"""
from __future__ import annotations

import re

from ..util import iso, new_id
from . import cards as C
from . import understand as U

STATUS_ORDER = ["planning", "waiting", "ordered", "delivered", "done"]
STATUS_LABEL = {"planning": "Planning", "waiting": "Waiting for OK", "ordered": "Ordered", "delivered": "Delivered", "done": "Done"}


class ChefAssistant:
    def __init__(self, gw):
        self.gw = gw
        self.E = gw.engine
        self.convs: dict[str, dict] = {}

    # ----------------------------------------------------------- conversations
    def new_conversation(self, buyer_id: str = "BUY-POHJOLA", title: str | None = None) -> dict:
        c = {"id": new_id("CHAT"), "buyerId": buyer_id, "title": title or "New chat", "createdAt": iso(self.gw.clock.now()),
             "sessionIds": [], "thread": []}
        self.convs[c["id"]] = c
        return c

    def conv(self, cid: str | None, buyer_id: str = "BUY-POHJOLA") -> dict:
        if cid and cid in self.convs:
            return self.convs[cid]
        return self.new_conversation(buyer_id)

    def _say(self, c: dict, cards: list[dict], sid: str | None = None) -> list[dict]:
        if cards:
            for k in cards:
                k["sessionId"] = sid
            c["thread"].append({"role": "assistant", "cards": cards, "at": iso(self.gw.clock.now())})
        return cards

    def _session(self, c: dict) -> dict | None:
        return self.E.sessions.get(c["sessionIds"][-1]) if c["sessionIds"] else None

    def _order(self, s):
        """Place the order, citing the signed offers the checked basket stands on."""
        from .tools import offer_ids
        return self._call(s, "place_order", {"offerIds": offer_ids(s)})

    def _call(self, s, tool, args=None):
        return self.E.call(s["sessionId"] if s else None, tool, args or {})["output"]

    # ----------------------------------------------------------- messages
    def message(self, cid: str | None, text: str, buyer_id: str = "BUY-POHJOLA") -> dict:
        c = self.conv(cid, buyer_id)
        c["thread"].append({"role": "user", "text": text, "at": iso(self.gw.clock.now())})
        if c["title"] == "New chat":
            c["title"] = _title(text)
        s = self._session(c)
        d = s["data"] if s else {}
        if s and d.get("asked") and not d["brief"]["complete"]:
            cards = self._answer_from_text(s, text)
        elif s and d.get("brief", {}).get("event") and U.parse_change(text) and not U.is_event_new(text):
            self._call(s, "parse_request", {"text": text})
            cards = self._run(s, show={"understood", "tip", "cant_do", "choice", "basket", "needs_ok"})
        else:
            s = self.E.call(None, "start_session", {"buyerId": c["buyerId"], "channel": "chat"})
            s = self.E.sessions[s["sessionId"]]
            c["sessionIds"].append(s["sessionId"])
            brief = self._call(s, "parse_request", {"text": text})
            if not brief["complete"]:
                q = self._call(s, "ask_user")["question"]
                cards = [C.understood(brief), C.question(q)]
                C.lint_all(cards)
            else:
                cards = self._run(s)
        return {"conversation": self.public(c), "cards": self._say(c, cards, s["sessionId"])}

    def _answer_from_text(self, s, text):
        q = s["data"]["asked"]
        if q["field"] == "when":
            pd = U.parse_date(text, self.gw.clock.today())
            if not pd:
                return [C.question(q)]
            val = pd[0]
        else:
            m = re.search(r"\d+", text)
            if not m:
                return [C.question(q)]
            val = int(m.group(0))
        return self._answer(s, q["field"], val)

    def _answer(self, s, field, value):
        brief = self._call(s, "parse_request", {"answer": {"field": field, "value": value}})
        if not brief["complete"]:
            return [C.question(U.question_for(brief, self.gw.clock.today()))]
        return self._run(s)

    def _run(self, s: dict, show: set | None = None) -> list[dict]:
        """Recall -> (Discover gaps) -> Plan -> Check -> Present."""
        if "recall" not in s["data"]:
            rec = self._call(s, "recall")
            if rec["gaps"]:
                for g in rec["gaps"][:3]:
                    self._call(s, "search_products", {"query": g})
                self._call(s, "request_offers")
        self._call(s, "plan_basket")
        return self._present(s, show)

    def _present(self, s, show=None):
        self._call(s, "check_basket")
        cards = self._call(s, "render_cards")["cards"]
        return [k for k in cards if show is None or k["type"] in show]

    # ----------------------------------------------------------- card actions
    def action(self, cid: str, action: str, payload: dict | None = None, by: str | None = None) -> dict:
        c = self.convs[cid]
        payload = payload or {}
        s = self.E.sessions.get(payload.get("sessionId")) or self._session(c)
        replan = {"basket", "needs_ok", "choice", "cant_do", "tip"}
        cards: list[dict] = []
        if action == "answer":
            cards = self._answer(s, payload["field"], payload["value"])
        elif action in ("apply_tip", "ignore_tip"):
            self._call(s, "plan_basket", {"acceptTip" if action == "apply_tip" else "ignoreTip": payload["tipId"]})
            cards = self._present(s, replan) if action == "apply_tip" else []
        elif action == "pick":
            self._call(s, "plan_basket", {"choices": {payload["lineId"]: payload["productId"]}})
            cards = self._present(s, replan)
        elif action == "use_alternative":
            self._call(s, "plan_basket", {"useAlternative": payload["lineId"]})
            cards = self._present(s, replan)
        elif action == "order":
            order = self._order(s)
            cards = [C.delivery(order)]
        elif action == "send_for_ok":
            out = self._call(s, "request_approval")
            cards = [C.waiting(out["approval"])]
        elif action == "approve":
            cards = self.decide(s["sessionId"], True, by or "Laura Virtanen")
        elif action == "delivered":
            o = s["data"]["order"]
            o["status"] = "delivered"
            self.gw.orders[o["orderId"]]["status"] = "delivered"
            cards = [C.how_did_it_go(s)]
        elif action == "save_usage":
            out = self._call(s, "record_usage", {"entries": payload.get("entries", {})})
            cards = [C.thanks(s["data"]["usage"], out["tips"])]
        C.lint_all(cards)
        return {"conversation": self.public(c), "cards": self._say(c, cards, s["sessionId"] if s else None)}

    def decide(self, sid: str, ok: bool, by: str) -> list[dict]:
        """Human approver decision (the chef app acting for the named approver). On OK the agent places the order."""
        from .tools import decide_approval
        s = self.E.session(sid)
        appr = s["data"]["approval"]
        people = self.gw.buyers[s["buyerId"]]["approvers"]
        person = next((p for p in people if by in (p["name"], p["id"])), None) or \
            next(p for p in people if p["id"] == appr["approver"]["id"])
        decide_approval(self.gw, s, ok, person)
        if not ok:
            return [C.card("needs_ok", title="Not approved", text=f"{person['name'].split()[0]} said not now. It stays in Planning.", actions=[])]
        order = self._order(s)
        return [C.delivery(order)]

    # ----------------------------------------------------------- views
    def status(self, s: dict) -> str:
        d = s["data"]
        o = d.get("order")
        if d.get("approval") and d["approval"]["status"] == "pending":
            return "waiting"
        if o:
            return {"ordered": "ordered", "delivered": "delivered", "done": "done"}.get(o["status"], "ordered")
        return "planning"

    def board(self, buyer_id: str | None = None) -> dict:
        items = []
        for c in self.convs.values():
            if buyer_id and c["buyerId"] != buyer_id:
                continue
            for sid in c["sessionIds"]:
                s = self.E.sessions[sid]
                d = s["data"]
                if "plan" not in d and "order" not in d:
                    continue
                b = d["brief"]
                ev = b.get("event")
                st = self.status(s)
                plan = d.get("plan") or {}
                buyer = self.gw.buyers[c["buyerId"]]
                items.append({"id": sid, "key": self._key(sid, c["buyerId"]), "type": "event" if ev else "order",
                              "eventColor": event_color(ev["name"] + ev["date"]) if ev else None,
                              "due": ev["date"] if ev else b["when"]["value"], "site": buyer["sites"][0]["name"],
                              "siteId": buyer["sites"][0]["id"], "eventName": ev["name"] if ev else None,
                              "conversationId": c["id"], "status": st, "statusLabel": STATUS_LABEL[st],
                              "title": (ev["name"] if ev and ev["name"] != ev["typeLabel"] else (ev["typeLabel"] if ev else c["title"])),
                              "subtitle": (f"{ev['guests']} guests · {C.dlabel(ev['date'])}" if ev else
                                           ", ".join(f"{C.qty(l['qty'], l['unit'])} {l['text']}" for l in b["lines"])[:60]),
                              "total": plan.get("total"), "totalLabel": C.eur(plan["total"]) if plan.get("total") else None,
                              "decision": (d.get("decision") or {}).get("decision"),
                              "approval": d.get("approval"), "order": d.get("order"),
                              "deliveries": (d.get("order") or {}).get("deliveries") or [],
                              "items": C.basket(plan, d["decision"], b)["items"] if plan.get("lines") and d.get("decision") else [],
                              "updatedAt": s["log"][-1]["at"] if s["log"] else s["createdAt"]})
        cols = [{"id": k, "label": STATUS_LABEL[k], "items": [i for i in items if i["status"] == k]} for k in STATUS_ORDER]
        return {"columns": cols, "count": len(items)}

    def _key(self, sid: str, bid: str) -> str:
        keys = self.__dict__.setdefault("_keys", {})
        if sid not in keys:
            n = sum(1 for k in keys.values() if k.startswith(bid.split("-")[1][:3])) + 1
            keys[sid] = f"{bid.split('-')[1][:3]}-{900 + n}"  # history uses POH-1…POH-899
        return keys[sid]

    def activity(self, sid: str) -> list[dict]:
        """The order's timeline from the audit log, in plain words (Jira-style activity)."""
        out, understood = [], False
        for e in self.gw.audit.events(trace_id=sid):
            text = ACTIVITY.get(e["action"])
            if e["action"] == "playbook.parse_request":
                text = "Answer saved" if e.get("inputs", {}).get("answer") else "Request changed" if understood else text
                understood = True
            if callable(text):
                text = text(e)
            if text:
                out.append({"at": e["ts"], "text": text, "who": _who(e["actor"])})
        return out

    def public(self, c: dict) -> dict:
        return {k: c[k] for k in ("id", "buyerId", "title", "createdAt", "sessionIds")} | {"thread": c["thread"]}

    def list(self, buyer_id: str | None = None) -> list[dict]:
        return [{"id": c["id"], "title": c["title"], "buyerId": c["buyerId"], "createdAt": c["createdAt"]}
                for c in sorted(self.convs.values(), key=lambda c: c["createdAt"], reverse=True)
                if not buyer_id or c["buyerId"] == buyer_id]


ACTIVITY = {
    "playbook.start_session": "Request received",
    "playbook.parse_request": "Request understood",  # later ones become "Request changed" / "Answer saved" in activity()
    "playbook.ask_user": "Asked one question",
    "playbook.recall": "Checked favourites and past orders",
    "playbook.request_offers": "Found products for the gaps",
    "playbook.plan_basket": "Basket planned",
    "playbook.check_basket": lambda e: {"auto": "Checked: fits your rules", "tell_me": "Checked: fits your rules",
                                        "needs_ok": "Checked: needs an OK", "blocked": "Checked: cannot be ordered yet"}.get(e.get("decision"), "Checked against your rules"),
    "playbook.request_approval": "Sent for OK",
    "approved": "Approved",
    "rejected": "Not approved",
    "playbook.place_order": "Ordered from Valio Aimo",
    "playbook.record_usage": "How it went saved",
}


def _who(actor: str) -> str:
    kind, _, name = actor.partition(":")
    return name if kind == "human" else "Gateway" if kind == "system" else "Assistant"


def event_color(name: str) -> int:
    """Stable colour slot 1-8 per event (Jira label colour)."""
    return sum(map(ord, name)) % 8 + 1


def _title(text: str) -> str:
    t = re.sub(r"^(i need|we need|please|order|tarvitsen|tarvitaan)\s+", "", text.strip(), flags=re.I)
    t = re.split(r"[:!?]|\.(?=\s|$)", t)[0]
    return (t[:42] + "…") if len(t) > 42 else t[:1].upper() + t[1:]
