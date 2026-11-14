"""Replay the golden scenarios (golden.yaml) through the playbook on a fresh gateway."""
from pathlib import Path

import pytest
import yaml

from gateway.core import Gateway
from gateway.playbook.agent import ChefAssistant

SCEN = yaml.safe_load((Path(__file__).parent / "golden.yaml").read_text())["scenarios"]


def _types(cards):
    return [c["type"] for c in cards]


@pytest.mark.parametrize("sc", SCEN, ids=[s["id"] for s in SCEN])
def test_golden(sc):
    gw = Gateway()
    A = ChefAssistant(gw)
    cid = None
    last_cards = []
    cream_before = None
    for st in sc["steps"]:
        if "say" in st:
            r = A.message(cid, st["say"], sc["buyer"])
        else:
            payload = {}
            if st["action"] == "pick":
                ch = next(c for c in last_cards if c["type"] == "choice")
                payload = ch["options"][st["option"]]["payload"]
            elif st["action"] == "use_alternative":
                payload = next(c for c in last_cards if c["type"] == "cant_do")["actions"][0]["payload"]
            elif st["action"] == "save_usage":
                payload = {"entries": st["entries"]}
            elif st["action"] == "apply_tip":
                payload = next(c for c in last_cards if c["type"] == "tip")["actions"][0]["payload"]
            r = A.action(cid, st["action"], payload)
        cid = r["conversation"]["id"]
        cards = r["cards"]
        last_cards = cards
        s = gw.engine.sessions[r["conversation"]["sessionIds"][-1]]
        d = s["data"]
        if d.get("plan"):
            cream = sum(l["qty"] for l in d["plan"]["lines"] if l["need"] == "whipping cream")
        ex = st.get("expect") or {}
        if "cards" in ex:
            assert _types(cards) == ex["cards"], (_types(cards), [c["text"] for c in cards])
        for t in ex.get("no_card", []):
            assert t not in _types(cards)
        if "decision" in ex:
            assert d["decision"]["decision"] == ex["decision"], d["decision"]
        if "total" in ex:
            assert d["plan"]["total"] == pytest.approx(ex["total"])
        if "max_total" in ex:
            assert d["plan"]["total"] <= ex["max_total"]
        if "min_total" in ex:
            assert d["plan"]["total"] > ex["min_total"]
        if "lines" in ex:
            got = [(l["name"], l["qty"]) + ((l["source"],) if "source" in e else ()) for l, e in zip(d["plan"]["lines"], ex["lines"])]
            want = [(e["name"], e["qty"]) + ((e["source"],) if "source" in e else ()) for e in ex["lines"]]
            assert got == want
        if "recall" in ex:
            assert d["recall"]["gaps"] == ex["recall"]["gaps"]
            for need, src in ex["recall"].get("sources", {}).items():
                assert any(m["need"] == need and m["source"] == src for m in d["recall"]["matched"])
        for tool in ex.get("tools_skipped", []):
            assert tool not in [x["tool"] for x in s["log"]]
        for tool in ex.get("no_tool", []):
            assert tool not in gw.engine.allowed(s)
        if "status" in ex:
            assert A.status(s) == ex["status"]
        if "board" in ex:
            col = next(c for c in A.board()["columns"] if any(i["id"] == s["sessionId"] for i in c["items"]))
            assert col["id"] == ex["board"]
        if "options" in ex:
            ch = next(c for c in cards if c["type"] == "choice")
            assert len(ch["options"]) == ex["options"]
        if ex.get("real_products"):
            assert all(o["id"].startswith("aimo:") for o in next(c for c in cards if c["type"] == "choice")["options"])
        if "leftovers_used" in ex:
            assert [x["need"] for x in d["plan"]["leftoversUsed"]] == ex["leftovers_used"]
        if "adjusted" in ex:
            assert set(ex["adjusted"]) <= {a["need"] for a in d["plan"]["adjustments"]}
        if "safe_for" in ex:
            needs = {l["need"] for l in d["plan"]["lines"]}
            assert set(ex["safe_for"].values()) <= needs
            from gateway import catalog
            safe = [l for l in d["plan"]["lines"] if l["need"] == "nut-free dark chocolate"]
            assert all("nuts" not in catalog.by_gtin(l["gtin"])["allergens"] + catalog.by_gtin(l["gtin"])["mayContain"] for l in safe)
        for key in ("favourites", "cant_do", "needs_ok", "tip"):
            if f"{key}_text_contains" in ex:
                assert ex[f"{key}_text_contains"] in next(c for c in cards if c["type"] == key)["text"]
        if "alternative_contains" in ex:
            cd = next(c for c in cards if c["type"] == "cant_do")
            assert ex["alternative_contains"] in cd["chips"][0]["label"]
        if "labels" in ex:
            assert set(ex["labels"]) <= set(d["usage"]["labels"])
        if ex.get("cream_less"):
            assert cream < cream_before
        if d.get("plan"):
            cream_before = cream
    assert gw.audit.verify()["ok"]
