"""Record real gateway runs for the self-contained demo page (ui/dist/index.html).

    python scripts/record_replays.py   -> ui/src/replays.json

Each script is replayed through the real ChefAssistant on a fresh gateway and
every step's cards and board snapshot are stored. When the page cannot reach a
gateway (e.g. published as a Claude artifact), it plays these recordings, so
what you see is genuine gateway output, not hand-written mock-ups.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gateway.adapter import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # with AIMO_API_KEY set, new-kitchen runs use live Valio Aimo prices

from gateway.core import Gateway  # noqa: E402
from gateway.playbook import insights  # noqa: E402
from gateway.playbook.agent import ChefAssistant  # noqa: E402
from gateway.playbook.engine import public_playbook  # noqa: E402
from gateway.analytics import views  # noqa: E402
from gateway.analytics.analyst import Analyst  # noqa: E402

STARTERS = ["Spend by month", "Top 10 products by spend, rest as other",
            "Waste % by kitchen compared to previous period, last 3 months", "Category mix per kitchen",
            "Carbon footprint by category, share", "Orders by weekday and kitchen as a heatmap", "Spend and waste % by product",
            "Waste by month", "Spend by kitchen", "On time by kitchen"]

GALA = "Gala dinner for 180 on Saturday 21.11.: salmon starter, beef tenderloin, chocolate mousse. 12 vegan, 8 gluten-free, 1 nut allergy."
SCRIPTS = [
    {"id": "gala", "buyer": "BUY-POHJOLA", "steps": [
        ("say", GALA), ("act", "order"), ("say", "now 200 guests"), ("act", "send_for_ok"), ("act", "approve"),
        ("act", "delivered"), ("act", "save_usage", {"entries": {"whipping cream": "some"}})]},
    {"id": "gala-next", "buyer": "BUY-POHJOLA", "after": "gala", "steps": [
        ("say", "Gala dinner for 150 on 12.12.: salmon starter, beef tenderloin, chocolate mousse."),
        ("act", "apply_tip", "tip"), ("act", "order")]},
    {"id": "milk", "buyer": "BUY-POHJOLA", "steps": [("say", "I need 1,000 L lactose-free milk by Monday"), ("act", "order")]},
    {"id": "xmas", "buyer": "BUY-POHJOLA", "steps": [
        ("say", "Pikkujoulut 120 hengelle: kinkku, rosolli, laatikot, riisipuuro. 6 vegaania."),
        ("act", "answer", "answer:0"), ("act", "order")]},
    {"id": "oat", "buyer": "BUY-KOULU", "steps": [
        ("say", "60 L oat drink by Monday"), ("act", "use_alternative", "cant_do"), ("act", "send_for_ok"), ("act", "approve")]},
] + [{"id": f"new-{i}", "buyer": "BUY-UUSI", "steps": [("say", "100 L milk by Wednesday"), ("act", "pick", f"pick:{i}"), ("act", "order")]}
     for i in range(3)]


def payload_for(spec, last_cards):
    if isinstance(spec, dict):
        return spec, None
    if spec is None:
        return {}, None
    if spec == "tip":
        return next(c for c in last_cards if c["type"] == "tip")["actions"][0]["payload"], None
    if spec == "cant_do":
        return next(c for c in last_cards if c["type"] == "cant_do")["actions"][0]["payload"], None
    kind, i = spec.split(":")
    if kind == "pick":
        o = next(c for c in last_cards if c["type"] == "choice")["options"][int(i)]
        return o["payload"], o["payload"]["productId"]
    if kind == "answer":
        o = next(c for c in last_cards if c["type"] == "question")["options"][int(i)]
        return {"field": o["field"], "value": o["value"]}, str(o["value"])
    raise ValueError(spec)


def run(script, gw, A):
    steps, cid, last = [], None, []
    for st in script["steps"]:
        if st[0] == "say":
            r = A.message(cid, st[1], script["buyer"])
            rec = {"kind": "say", "text": st[1]}
        else:
            payload, key = payload_for(st[2] if len(st) > 2 else None, last)
            r = A.action(cid, st[1], payload)
            rec = {"kind": "act", "action": st[1], "key": key}
        cid = r["conversation"]["id"]
        last = r["cards"]
        board = A.board(script["buyer"])
        for col in board["columns"]:
            col["items"] = [i for i in col["items"] if i["conversationId"] == cid]
        rec.update({"cards": r["cards"], "board": board, "title": r["conversation"]["title"]})
        steps.append(rec)
    return {"id": script["id"], "buyerId": script["buyer"], "steps": steps}


def main():
    out = {"scripts": [], "insights": {}, "settings": {}, "playbook": public_playbook()}
    gws = {}
    for sc in SCRIPTS:
        if sc.get("after"):
            gw, A = gws[sc["after"]]
        else:
            gw = Gateway(live=True)
            A = ChefAssistant(gw)
        gws[sc["id"]] = (gw, A)
        out["scripts"].append(run(sc, gw, A))
    gw, _ = gws["gala-next"]
    for bid in gw.buyers:
        out["insights"][bid] = insights.for_buyer(gw, bid)
        out["settings"][bid] = insights.settings(gw, bid)
    # v3 views: history (first 300 per buyer), order details (first 40), Your year per kitchen, kitchens, Explore answers
    extra = {"history": {}, "details": {}, "wrapped": {}, "kitchens": {}, "asks": {}}
    analyst = Analyst(gw)
    analyst.client = None  # recordings come from the rule engine, so they are repeatable
    for bid, b in gw.buyers.items():
        h = views.order_history(gw, bid, size=300)["orders"]
        extra["history"][bid] = h
        extra["details"][bid] = {o["id"]: views.order_detail(gw, bid, o["id"]) for o in h[:40]}
        extra["kitchens"][bid] = views.kitchens(gw, bid)
        for site in [None] + [x["id"] for x in b["sites"]]:
            extra["wrapped"][f"{bid}|{site or ''}"] = views.wrapped(gw, bid, site)
        extra["asks"][bid] = [{"prompt": q, "answer": analyst.ask(q, {}, bid)} for q in STARTERS] if h else []
    out["extra"] = extra
    path = ROOT / "ui" / "src" / "replays.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KiB, {len(out['scripts'])} scripts)")


if __name__ == "__main__":
    main()
