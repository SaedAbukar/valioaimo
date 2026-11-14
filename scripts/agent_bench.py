"""Multi-agent benchmark for the Aimo Agent Gateway (REST only, like any external agent).

    make run                                    # the gateway on :8000
    make bench                                  # 10 scripted agents, all scenarios -> docs/BENCH.md
    python scripts/agent_bench.py --agents 20 --model claude-haiku-5-5   # + Claude agents (needs ANTHROPIC_API_KEY)

Scenarios: milk (the brief's sentence), over_limit (3,000 L -> a named human approves), allergen (Kaarela's
oat drink in a nut-free kitchen), stale_offer (the demo clock moves past 15 min -> re-quote), retry
(place_order twice with one Idempotency-Key), race (many agents on the same stock at once), out_of_order
(an agent skips steps first).

Invariants come from the gateway's own records (ops credential: /v1/ops/orders, /v1/ops/inventory,
/v1/audit?full=1) — not from what the agents say: no oversell, one order per idempotency key, every order
cites offers whose signatures verify, no order without auto/tell-me or a human OK, every OK by a named human,
and the audit chain verifies.
Scores: completion rate, 409/422/429 per run, latency p50/p95, determinism (reset, run each scenario
twice, same outcome and total).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.agent_demo import Gateway as HttpGateway, verify_es256  # noqa: E402

OPS = "demo-ops"
SCENARIOS = {
    "milk": {"token": "demo-key-pohjola", "text": "I need 1,000 litres of lactose-free milk by Monday. "
             "Find an option that meets our requirements based on price and availability.",
             "approver": "demo-human-usr-lvirtanen", "expect": {"ordered", "approved_ordered", "cant_do"}},
    "over_limit": {"token": "demo-key-pohjola", "text": "I need 3,000 litres of lactose-free milk by Monday.",
                   "approver": "demo-human-usr-lvirtanen", "expect": {"approved_ordered", "cant_do"}},
    "allergen": {"token": "demo-key-kaarela", "text": "60 L oat drink by Monday", "approver": "demo-human-usr-skoskinen",
                 "expect": {"ordered", "approved_ordered", "cant_do"}},
    "retry": {"token": "demo-key-kaari", "text": "40 L soy drink by Monday", "idem": True,
              "approver": "demo-human-usr-akorhonen", "expect": {"ordered", "approved_ordered"}},
    "race": {"token": "demo-key-pohjola", "text": "I need 600 litres of lactose-free milk by Monday.",
             "approver": "demo-human-usr-lvirtanen", "expect": {"ordered", "approved_ordered", "cant_do"}},  # sold out is a correct end
    "out_of_order": {"token": "demo-key-uusi", "text": "100 L milk by Wednesday", "skip": True,
                     "approver": "demo-human-usr-mnieminen", "expect": {"ordered", "approved_ordered"}},
    "stale_offer": {"token": "demo-key-pohjola", "text": "20 kg butter by Monday", "stale": True,
                    "approver": "demo-human-usr-lvirtanen", "expect": {"ordered", "approved_ordered"}},
}
ORDER = ["parse_request", "recall", "request_offers", "plan_basket", "check_basket", "render_cards", "place_order", "request_approval"]


# ------------------------------------------------------------------ transports
def http_transport(base: str):
    gw = HttpGateway(base, "")

    def call(method, path, body=None, token=None, headers=None):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(base.rstrip("/") + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), dict(e.headers)
    call.base = gw.base
    return call


def local_transport(client):
    """In-process transport over a starlette TestClient (tests)."""
    def call(method, path, body=None, token=None, headers=None):
        r = client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}", **(headers or {})})
        return r.status_code, (r.json() if r.content else {}), dict(r.headers)
    return call


# ------------------------------------------------------------------ one scripted agent
class Agent:
    def __init__(self, call, name: str, spec: dict):
        self.call, self.name, self.spec = call, name, spec
        self.lat: list[float] = []
        self.counts = {"409": 0, "422": 0, "429": 0}
        self.requotes = 0
        self.idem: dict[str, list[str]] = {}

    def req(self, method, path, body=None, token=None, headers=None):
        for _ in range(20):
            t0 = time.perf_counter()
            st, out, h = self.call(method, path, body, token or self.spec["token"], headers)
            self.lat.append((time.perf_counter() - t0) * 1000)
            if st == 429:  # honour Retry-After, as a well-behaved agent does
                self.counts["429"] += 1
                time.sleep(float(out.get("retryAfter") or h.get("retry-after") or 1))
                continue
            if str(st) in self.counts:
                self.counts[str(st)] += 1
            return st, out
        return st, out

    def tool(self, sid, tool, args=None, headers=None):
        return self.req("POST", f"/v1/sessions/{sid}/tools/{tool}", args or {}, headers=headers)

    def requote(self, sid):
        self.requotes += 1
        time.sleep(random.uniform(0.02, 0.15) * self.requotes)  # back off with jitter: others are buying the same stock
        out = None
        for t in ("plan_basket", "check_basket", "render_cards"):
            st, r = self.tool(sid, t)
            if t == "plan_basket" and st == 200:
                out = r["output"]
        return out

    def run(self) -> dict:
        t0 = time.perf_counter()
        sp = self.spec
        st, r = self.req("POST", "/v1/sessions", {})
        sid = r["sessionId"]
        if sp.get("skip"):  # deliberately out of order: the gateway must refuse and say what is next
            self.tool(sid, "place_order", {"offerIds": ["OF-GUESS"]})
        nxt, plan, done, outcome, order, decision = ["parse_request"], None, set(), None, None, None
        while True:
            tool = next((t for t in ORDER if t in nxt and t not in done), None)
            if tool is None:
                break
            args = {"text": sp["text"]} if tool == "parse_request" else {}
            if tool == "plan_basket" and plan and plan.get("pendingChoices"):
                pc = plan["pendingChoices"][0]
                args = {"choices": {pc["lineId"]: pc["options"][0]["productId"]}}
            if tool == "place_order":
                if sp.get("stale") and not self.requotes:
                    self.req("POST", "/v1/demo/clock", {"advanceMinutes": 16}, token=OPS)
                args = {"offerIds": [o["offerId"] for o in plan["offers"]]}
            hdr = {"Idempotency-Key": f"{self.name}-order"} if tool == "place_order" and sp.get("idem") else None
            st, r = self.tool(sid, tool, args, headers=hdr)
            if tool in ("place_order", "request_approval") and st == 409 and r.get("guard") in ("price_locked", "stock_changed") \
                    and self.requotes < 8:  # someone else got the stock, or the offer expired: re-quote and go again
                plan = self.requote(sid) or plan
                st2, s = self.req("GET", f"/v1/sessions/{sid}")
                nxt, done = s["next_allowed_tools"], {"parse_request", "recall", "request_offers", "plan_basket", "check_basket", "render_cards"}
                decision = (s["outputs"].get("check") or {}).get("decision")
                if decision == "blocked" or (plan and plan.get("cantDo") and not plan.get("lines")):
                    outcome = "cant_do"  # sold out meanwhile: the gateway says so instead of overselling
                    break
                continue
            if st != 200:
                outcome = f"error_{st}_{r.get('guard') or r.get('error')}"
                break
            done.add(tool)
            out, nxt = r["output"], r["next_allowed_tools"]
            if tool == "plan_basket":
                plan = out
                if out.get("pendingChoices"):
                    done.discard("plan_basket")
                if out.get("cantDo") and not out.get("lines"):
                    outcome = "cant_do"
                    break
            if tool == "check_basket":
                decision = out["decision"]
                if decision == "blocked":
                    outcome = "cant_do" if plan and plan.get("cantDo") else "blocked"
                    break
            if tool == "place_order":
                order, outcome = out, ("approved_ordered" if out.get("approvedBy") else "ordered")
                if sp.get("idem"):
                    st2, again = self.tool(sid, "place_order", args, headers=hdr)
                    self.idem.setdefault(hdr["Idempotency-Key"], []).extend([out["orderId"], (again.get("output") or {}).get("orderId")])
                break
            if tool == "request_approval":
                aid = out["approval"]["approvalId"]
                st, ev = self.req("GET", f"/v1/sessions/{sid}/events?after=0", None)
                st, d = self.req("POST", f"/v1/approvals/{aid}", {"ok": True, "note": "bench"}, token=sp.get("approver"))
                if st != 200:
                    outcome = f"approval_{st}"
                    break
                done.discard("place_order")
                st, s = self.req("GET", f"/v1/sessions/{sid}")
                nxt = s["next_allowed_tools"]
        return {"agent": self.name, "scenario": None, "sessionId": sid, "outcome": outcome or "stuck", "decision": decision,
                "orderId": (order or {}).get("orderId"), "total": (order or {}).get("total"), "seconds": round(time.perf_counter() - t0, 3),
                "c409": self.counts["409"], "c422": self.counts["422"], "c429": self.counts["429"], "requotes": self.requotes,
                "latencies": self.lat, "idem": self.idem, "engine": "scripted"}


# ------------------------------------------------------------------ optional Claude agents (manual tool-use loop)
def llm_agent(call, model: str, name: str, spec: dict) -> dict:
    """Drive the same REST tools with Claude: the typed input schemas from GET /v1/tools are the tool definitions.
    The gateway still decides every outcome; the model only chooses which tool to call next."""
    import anthropic
    client = anthropic.Anthropic()
    agent = Agent(call, name, spec)
    st, man = agent.req("GET", "/v1/tools")
    order_tools = [t for t in man["tools"] if t["playbook"] == "order" and t["name"] not in ("start_session", "get_playbook")]
    tools = [{"name": t["name"], "description": t["description"][:900],
              "input_schema": {**{k: v for k, v in t["inputSchema"].items() if k not in ("examples", "oneOf")}, "additionalProperties": True}}
             for t in order_tools]
    st, r = agent.req("POST", "/v1/sessions", {})
    sid = r["sessionId"]
    system = ("You are a purchasing agent for a professional kitchen, connected to Valio Aimo's agent gateway. Follow the "
              "playbook: call only tools listed in next_allowed_tools. Cite the offer ids from plan_basket when you call place_order. "
              "If an OK from a human is needed, call request_approval and stop. Never invent prices.")
    messages = [{"role": "user", "content": f"Request from the chef: {spec['text']}\nSession {sid} is open; next_allowed_tools: {r['next_allowed_tools']}"}]
    order = None
    for _ in range(25):
        resp = client.messages.create(model=model, max_tokens=4000, system=system, tools=tools, messages=messages)
        if resp.stop_reason == "refusal":
            break
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            break
        results = []
        for u in uses:
            st, out = agent.tool(sid, u.name, u.input)
            if u.name == "place_order" and st == 200:
                order = out["output"]
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out)[:6000], "is_error": st >= 400})
        messages.append({"role": "user", "content": results})
        if order:
            break
    st, s = agent.req("GET", f"/v1/sessions/{sid}")
    waiting = (s["outputs"].get("act") or {}).get("status") == "waiting_for_ok"
    return {"agent": name, "scenario": None, "sessionId": sid, "outcome": "ordered" if order else "waiting_for_ok" if waiting else "stuck",
            "decision": (s["outputs"].get("check") or {}).get("decision"), "orderId": (order or {}).get("orderId"),
            "total": (order or {}).get("total"), "seconds": 0, "c409": agent.counts["409"], "c422": agent.counts["422"],
            "c429": agent.counts["429"], "requotes": 0, "latencies": agent.lat, "idem": {}, "engine": model}


# ------------------------------------------------------------------ invariants from the gateway's own records
def invariants(call, runs: list[dict], inventory0: dict) -> dict:
    st, od = call("GET", "/v1/ops/orders", None, OPS)[:2]
    mine = {r["sessionId"] for r in runs}
    orders = [o for o in od["orders"] if o["sessionId"] in mine]  # a reset may re-seed demo orders: those are not ours
    st, jwks = call("GET", "/.well-known/jwks.json", None, OPS)[:2]
    out = {}
    # 1 no oversell: per product, cumulative ordered by each delivery date <= deliverable by that date at the start
    over = []
    by_gtin: dict[str, list] = {}
    for o in orders:
        for ln in o["lines"]:
            by_gtin.setdefault(ln["gtin"], []).append(ln)
    for g, lines in by_gtin.items():
        sched = (inventory0.get(g) or {}).get("schedule")
        if sched is None:
            continue  # bridged during the run (real products): deliverable set when first quoted
        need = 0.0
        for ln in sorted(lines, key=lambda x: x["deliveryDate"]):
            need += ln["qty"]
            have = sum(x["qty"] for x in sched if x["date"] <= ln["deliveryDate"])
            if need > have + 1e-6:
                over.append({"gtin": g, "ordered": need, "available": have, "by": ln["deliveryDate"]})
    out["no_oversell"] = {"ok": not over, "detail": over or f"{len(by_gtin)} products, {len(orders)} orders"}
    # 2 one order per idempotency key
    dup = {k: v for r in runs for k, v in r["idem"].items() if len(set(v)) != 1}
    ids = [o["orderId"] for o in orders]
    out["one_order_per_idempotency_key"] = {"ok": not dup and len(ids) == len(set(ids)) == len({r["orderId"] for r in runs if r["orderId"]}),
                                            "detail": dup or f"{sum(len(r['idem']) for r in runs)} keys, {len(ids)} orders"}
    # 3 every order cites offers whose signatures verify, and its confirmation verifies
    bad = []
    for o in orders:
        if not verify_es256(o["confirmationJws"], jwks):
            bad.append(o["orderId"])
        for oid in {ln["offerId"] for ln in o["lines"]}:
            st, of = call("GET", f"/v1/offers/{oid}", None, OPS)[:2]
            if st != 200 or not verify_es256(of["proof"]["jws"], jwks):
                bad.append(oid)
    out["orders_cite_verified_offers"] = {"ok": not bad, "detail": bad or f"{len(orders)} confirmations and their offers verify"}
    # 4 no order without auto / tell me or a human OK
    rogue = [o["orderId"] for o in orders if o["decision"] not in ("auto", "tell_me") and not o.get("approvedBy")]
    out["no_order_without_authority"] = {"ok": not rogue, "detail": rogue or "every order was auto, tell-me or approved"}
    # 5 + 6 from the audit chain
    st, au = call("GET", "/v1/audit?full=1", None, OPS)[:2]
    approvals = [e for e in au["events"] if e["action"] in ("approved", "rejected")]
    unnamed = [e["eventId"] for e in approvals if not e["actor"].startswith("human:") or not e["refs"].get("personId")]
    out["approvals_by_named_humans"] = {"ok": not unnamed, "detail": unnamed or f"{len(approvals)} decisions, all by named approvers"}
    out["audit_chain_verifies"] = {"ok": au["verify"]["ok"], "detail": au["verify"]["detail"]}
    return out


def _pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1)))], 1) if xs else None


def bench(call, agents: int = 10, scenarios: list[str] | None = None, model: str | None = None) -> dict:
    names = scenarios or list(SCENARIOS)
    call("POST", "/v1/demo/reset", {}, OPS)
    inv0 = call("GET", "/v1/ops/inventory", None, OPS)[1]["inventory"]
    concurrent = [n for n in names if n != "stale_offer"]
    runs: list[dict] = [None] * agents  # type: ignore[list-item]

    def go(i):
        sc = concurrent[i % len(concurrent)]
        r = Agent(call, f"agent-{i:02d}", SCENARIOS[sc]).run()
        r["scenario"] = sc
        runs[i] = r

    t0 = time.perf_counter()
    ts = [threading.Thread(target=go, args=(i,)) for i in range(agents)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    if "stale_offer" in names:  # moves the shared demo clock, so it runs alone after the concurrent phase
        r = Agent(call, "agent-stale", SCENARIOS["stale_offer"]).run()
        r["scenario"] = "stale_offer"
        runs.append(r)
    wall = time.perf_counter() - t0
    llm, llm_note = [], None
    if model:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            llm_note = f"skipped: no ANTHROPIC_API_KEY for {model}"
        else:
            for sc in ("milk", "over_limit", "out_of_order"):
                try:
                    r = llm_agent(call, model, f"llm-{sc}", SCENARIOS[sc])
                except Exception as e:  # noqa: BLE001 - a failing LLM run is a row, not a crash
                    r = {"agent": f"llm-{sc}", "outcome": f"error {type(e).__name__}", "orderId": None, "total": None, "c409": 0,
                         "c422": 0, "c429": 0, "requotes": 0, "latencies": [], "idem": {}, "engine": model, "decision": None, "seconds": 0}
                r["scenario"] = sc
                r["completed"] = r["outcome"] in ("ordered", "waiting_for_ok")
                llm.append(r)
    inv = invariants(call, runs + llm, inv0)
    for r in runs:
        r["completed"] = r["outcome"] in SCENARIOS[r["scenario"]]["expect"]
    # determinism: reset, each scenario once, twice; same outcome and total
    reps = []
    for _ in range(2):
        call("POST", "/v1/demo/reset", {}, OPS)
        one = {}
        for sc in names:
            r = Agent(call, f"det-{sc}", SCENARIOS[sc]).run()
            one[sc] = (r["outcome"], r["total"])
        reps.append(one)
    same = sum(reps[0][k] == reps[1][k] for k in names) / len(names)
    lat = [x for r in runs for x in r["latencies"]]
    return {"agents": agents, "scenarios": names, "wallSeconds": round(wall, 2), "runs": runs, "llm": llm, "llmNote": llm_note,
            "invariants": inv, "determinismRuns": reps,
            "scores": {"completionRate": round(sum(r["completed"] for r in runs) / len(runs), 3),
                       "per409": round(sum(r["c409"] for r in runs) / len(runs), 2),
                       "per422": round(sum(r["c422"] for r in runs) / len(runs), 2),
                       "per429": round(sum(r["c429"] for r in runs) / len(runs), 2),
                       "callP50ms": _pct(lat, 0.5), "callP95ms": _pct(lat, 0.95),
                       "runP50s": _pct([r["seconds"] for r in runs], 0.5), "runP95s": _pct([r["seconds"] for r in runs], 0.95),
                       "determinism": round(same, 3)}}


def report(res: dict) -> str:
    s = res["scores"]
    lines = ["# Agent benchmark", "", f"{res['agents']} scripted agents at once plus one stale-offer agent; scenarios: "
             f"{', '.join(res['scenarios'])}. Generated by `make bench` (scripts/agent_bench.py).", "",
             "## Scores", "", "| Score | Value |", "|---|---|",
             f"| Completion rate | {s['completionRate']:.0%} |", f"| 409 per run (refused out of order / re-quote) | {s['per409']} |",
             f"| 422 per run (bad input) | {s['per422']} |", f"| 429 per run (rate limited, honoured Retry-After) | {s['per429']} |",
             f"| Call latency p50 / p95 | {s['callP50ms']} ms / {s['callP95ms']} ms |",
             f"| Run time p50 / p95 | {s['runP50s']} s / {s['runP95s']} s |", f"| Determinism (reset, same outcome and total) | {s['determinism']:.0%} |",
             f"| Wall time, concurrent phase | {res['wallSeconds']} s |", "",
             "## Invariants (from the gateway's own records)", "", "| Invariant | Holds | Detail |", "|---|---|---|"]
    label = {"no_oversell": "No oversell", "one_order_per_idempotency_key": "One order per idempotency key",
             "orders_cite_verified_offers": "Orders cite offers that verify", "no_order_without_authority": "No order without authority",
             "approvals_by_named_humans": "Approvals by named humans", "audit_chain_verifies": "Audit chain verifies"}
    for k, v in res["invariants"].items():
        lines.append(f"| {label[k]} | {'yes' if v['ok'] else '**NO**'} | {str(v['detail'])[:120]} |")
    lines += ["", "## Runs", "", "| Agent | Scenario | Outcome | Decision | Total € | 409 | 422 | 429 | Re-quotes | s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(res["runs"], key=lambda r: (r["scenario"], r["agent"])):
        lines.append(f"| {r['agent']} | {r['scenario']} | {r['outcome']} | {r['decision'] or ''} | {r['total'] or ''} | {r['c409']} | {r['c422']} | {r['c429']} | {r['requotes']} | {r['seconds']} |")
    lines += ["", "## LLM agents", ""]
    if res["llm"]:
        lines += ["| Model | Scenario | Outcome | 409 | 422 |", "|---|---|---|---|---|"]
        lines += [f"| {r['engine']} | {r['scenario']} | {r['outcome']} | {r['c409']} | {r['c422']} |" for r in res["llm"]]
    else:
        lines.append(res["llmNote"] or "Not run. Pass `--model claude-haiku-5-5` (or `claude-sonnet-5-5`) with ANTHROPIC_API_KEY set.")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--agents", type=int, default=10)
    ap.add_argument("--model", help="also run Claude agents, e.g. claude-haiku-5-5 or claude-sonnet-5-5")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docs" / "BENCH.md"))
    a = ap.parse_args()
    res = bench(http_transport(a.base), agents=a.agents, model=a.model)
    Path(a.out).write_text(report(res))
    print(report(res))
    ok = all(v["ok"] for v in res["invariants"].values())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
