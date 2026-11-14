"""Thin reference wiring of the gateway core (no HTTP). See docs/ARCHITECTURE.md.

Gateway = Discovery + Planner + Offer signer + Policy engine + Audit ledger over
one backend adapter. The REST/MCP facades in the target architecture call these
same methods; this skeleton keeps them in-process for tests and the CLI.
"""
from __future__ import annotations

import copy
from datetime import timedelta

from . import catalog, planner, policy, preferences, signals as sig, trust
from .adapter import FixtureBackend
from .audit import AuditLedger
from .clock import Clock
from .crypto import load_or_create, verify_jws
from .store import Store
from .util import iso, new_id, s2d


class Gateway:
    def __init__(self, db: str = ":memory:", clock: Clock | None = None):
        self.clock = clock or Clock(frozen=True)
        self.store = Store(db)
        self.backend = FixtureBackend(self.clock)
        self.audit = AuditLedger(self.store, self.clock)
        self.gateway_key = load_or_create(None, "gw-2026-11")
        self.buyer_keys = {}
        self.buyers = {b["id"]: copy.deepcopy(b) for b in catalog.load_buyers()["buyers"]}
        self.profiles = {bid: preferences.default_profile(bid) for bid in self.buyers}
        self.mandates = {}
        for bid, b in self.buyers.items():
            self.buyer_keys[bid] = load_or_create(None, f"buyer-{bid.lower()}")
            self.register_mandate(bid, self.sign_mandate(bid, b["mandate"]))
        self.records: list[dict] = []

    # --- discovery ---------------------------------------------------------
    def jwks(self) -> dict:
        return {"keys": [self.gateway_key.public_jwk]}

    def buyer_jwks(self, bid) -> dict:
        return {"keys": [self.buyer_keys[bid].public_jwk]}

    # --- mandates (AP2-style Intent Mandate, signed by a named human) --------
    def sign_mandate(self, bid: str, body: dict) -> dict:
        b = self.buyers[bid]
        now = self.clock.now()
        m = copy.deepcopy(body)
        m.update({"type": "IntentMandate", "buyerId": bid, "issuedBy": {"id": b["admin"]["id"], "name": b["admin"]["name"],
                  "role": b["admin"]["role"]}, "validFrom": iso(now),
                  "validUntil": iso(now + timedelta(days=body.get("validDays", 90))),
                  "preferenceProfile": {"id": self.profiles[bid]["profileId"], "version": self.profiles[bid]["version"]}})
        jws = self.buyer_keys[bid].sign(m, typ="mandate+jwt")
        return {"mandate": m, "jws": jws}

    def register_mandate(self, bid: str, signed: dict) -> dict:
        ok, payload, detail = verify_jws(signed["jws"], self.buyer_jwks(bid)["keys"])
        if not ok or payload != signed["mandate"]:
            return {"ok": False, "detail": detail if not ok else "mandate body differs from signed payload"}
        self.mandates[bid] = signed
        self.audit.append(trace_id=None, actor=f"human:{payload['issuedBy']['name']}", action="mandate_registered",
                          buyer_id=bid, refs={"mandateId": payload["mandateId"]}, reason=f"v{payload['version']}")
        return {"ok": True, "detail": detail}

    def mandate_check(self, bid: str) -> tuple[dict | None, dict]:
        s = self.mandates.get(bid)
        if not s:
            return None, {"ok": False, "detail": "missing"}
        ok, payload, detail = verify_jws(s["jws"], self.buyer_jwks(bid)["keys"])
        if not ok:
            return None, {"ok": False, "detail": "unsigned or signature invalid"}
        if iso(self.clock.now()) > payload["validUntil"]:
            return payload, {"ok": False, "detail": f"expired {payload['validUntil']}"}
        return payload, {"ok": True, "detail": detail}

    # --- planning --------------------------------------------------------------
    def plan(self, bid: str, lines: list[dict], need_by: str, choices: dict | None = None, trace_id: str | None = None,
             usage: dict | None = None) -> dict:
        trace_id = trace_id or new_id("TR")
        buyer = self.buyers[bid]
        mandate, mcheck = self.mandate_check(bid)
        signals = sig.compute(buyer, self.records)
        ctx = {"buyer": buyer, "mandate": mandate, "profile": self.profiles[bid], "signals": signals,
               "backend": self.backend, "today": self.clock.today(), "leftovers": []}
        nb = s2d(need_by)
        out_lines = [planner.plan_line(ctx, l, nb, (choices or {}).get(l["lineId"]), usage) for l in lines]
        for l in out_lines:
            offers = {it["gtin"]: trust.issue_offer(self, it["gtin"], nb, bid) for it in l["ranked"][:6]}
            for it in l["ranked"]:
                it["offerId"] = offers[it["gtin"]]["offerId"] if it["gtin"] in offers else None
            for p in l["plans"]:
                for pl in p["lines"]:
                    pl["offerId"] = offers.get(pl["gtin"], {}).get("offerId")
        plans = planner.combine(out_lines, nb)
        for p in plans:
            p["planId"] = new_id("PL")
            p["policy"] = self.evaluate(bid, p["lines"], [{"lineId": l["lineId"], "qty": l["qtyAfterLeftovers"], "needBy": need_by} for l in out_lines],
                                        mandate, mcheck, signals)
        self.audit.append(trace_id=trace_id, actor=f"agent:{buyer['agents'][0]['id'].split(':')[1]}", action="plan",
                          buyer_id=bid, inputs={"lines": lines, "needBy": need_by},
                          refs={"planIds": [p["planId"] for p in plans]}, reason=f"{len(plans)} plans")
        return {"traceId": trace_id, "needBy": need_by, "lines": out_lines, "plans": plans}

    def evaluate(self, bid, lines, request_lines, mandate=None, mcheck=None, signals=None, **extra) -> dict:
        buyer = self.buyers[bid]
        if mcheck is None:
            mandate, mcheck = self.mandate_check(bid)
        ctx = {"buyer": buyer, "mandate": mandate, "mandateCheck": mcheck, "lines": lines, "requestLines": request_lines,
               "total": round(sum(l["lineTotal"] for l in lines), 2), "mtd": buyer["monthToDateEUR"],
               "profile": self.profiles[bid], "signals": signals if signals is not None else sig.compute(buyer, self.records),
               "agentId": buyer["agents"][0]["id"]}
        ctx.update(extra)
        return policy.evaluate(ctx)
