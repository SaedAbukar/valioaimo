"""Core reference tests: planner worked example, policy rules, trust protocol, audit chain, preferences."""
import copy

import pytest

from gateway import catalog, policy
from gateway.core import Gateway
from gateway.trust import issue_offer, verify_offer

MILK = [{"lineId": "L1", "text": "lactose-free milk", "qty": 1000, "unit": "L"}]
A, B, C = (catalog.by_key(k)["gtin"] for k in ("milk_lf_semi_kaarna", "milk_lf_semi_maitokaari", "milk_lf_whole_tunturi"))


@pytest.fixture
def gw():
    return Gateway()


# ---------------- planner: the worked example ---------------------------------
def test_worked_example_ranking_and_filters(gw):
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    line = r["lines"][0]
    assert [i["gtin"] for i in line["ranked"][:3]] == [A, B, C]
    assert [i["tier"] for i in line["ranked"][:3]] == ["BEST", "BETTER", "GOOD"]
    reasons = {e["name"]: e["reason"] for e in line["excluded"]}
    assert reasons["Semi-skimmed milk 1.5% 1 L"] == "Not lactose-free"
    assert reasons["Barista oat drink 1 L"].startswith("Not milk")


def test_worked_example_plans(gw):
    plans = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")["plans"]
    p1, p2, p3 = plans
    assert [(l["gtin"], l["qty"]) for l in p1["lines"]] == [(A, 640), (B, 360)]
    assert p1["total"] == pytest.approx(1304.40)
    assert p1["policy"]["outcome"] == "NOTIFY" and {"R4", "R6"} <= set(p1["policy"]["ruleIds"])
    assert p2["lines"][0]["gtin"] == C and p2["total"] == pytest.approx(1410.0) and p2["policy"]["outcome"] == "APPROVE"
    assert "R5" in p2["policy"]["ruleIds"]
    assert p3["total"] == pytest.approx(1290.0) and p3["policy"]["outcome"] == "APPROVE" and "R7" in p3["policy"]["ruleIds"]
    assert p1["lines"][1]["roundingNote"].startswith("40 cases × 9 L")


def test_happy_path_auto(gw):
    gw.backend.set_stock(A, 1200)
    p = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")["plans"][0]
    assert p["strategy"] == "single" and p["policy"]["outcome"] == "AUTO"


def test_case_rounding_overage(gw):
    r = gw.plan("BUY-POHJOLA", [{"lineId": "L1", "text": "whipping cream", "qty": 40, "unit": "L"}], "2026-11-14")
    ln = r["plans"][0]["lines"][0]
    assert ln["cases"] == 4 and ln["qty"] == 48 and ln["overage"] == 8


def test_hospital_allergen_safe_substitution(gw):
    r = gw.plan("BUY-KAARI", [{"lineId": "L1", "text": "oat drink", "qty": 240, "unit": "L"}], "2026-11-17")
    line = r["lines"][0]
    codes = {e["name"]: e["code"] for e in line["excluded"]}
    assert codes["Almond drink, unsweetened 1 L"] == "allergen"
    assert codes["Barista oat drink 1 L"] == "allergen"  # may contain nuts
    p1 = r["plans"][0]
    assert p1["lines"][0]["name"].startswith("Soy drink") and p1["policy"]["outcome"] == "APPROVE"
    assert "R5" in p1["policy"]["ruleIds"]


# ---------------- policy: table-driven -----------------------------------------
def _line(gtin, qty, **kw):
    p = catalog.by_gtin(gtin)
    d = {"lineId": "x1", "requestLineId": "L1", "gtin": gtin, "name": p["name"], "unit": p["unit"], "category": p["category"],
         "qty": qty, "lineTotal": round(qty * p["unitPrice"], 2), "deliveryDate": "2026-11-16", "role": "primary"}
    d.update(kw)
    return d


@pytest.mark.parametrize("case,expect_rule,expect_outcome", [
    ("ok", None, "AUTO"),
    ("over_per_order", "R2", "APPROVE"),
    ("over_month", "R3", "APPROVE"),
    ("late", "R7", "APPROVE"),
    ("partial", "R6", "APPROVE"),
    ("first_time", "R8", "NOTIFY"),
    ("allergen", "R1", "BLOCK"),
    ("no_mandate", "R0", "BLOCK"),
    ("drift", "R10", "APPROVE"),
    ("kill", "V3", "BLOCK"),
])
def test_policy_rules(gw, case, expect_rule, expect_outcome):
    bid, qty, gtin = "BUY-POHJOLA", 1000, A
    extra, rl_qty = {}, 1000
    lines = [_line(A, 1000)]
    if case == "over_per_order":
        lines = [_line(A, 1600)]; rl_qty = 1600
    if case == "over_month":
        gw.buyers[bid]["monthToDateEUR"] = 44500
    if case == "late":
        lines = [_line(A, 1000, deliveryDate="2026-11-18")]
    if case == "partial":
        lines = [_line(A, 640)]
    if case == "first_time":
        lines = [_line(C, 1000)]
    if case == "allergen":
        bid = "BUY-KAARI"; lines = [_line(catalog.by_key("almond_drink_pahkinapuu")["gtin"], 240)]; rl_qty = 240
    if case == "no_mandate":
        gw.mandates.pop(bid)
    if case == "drift":
        extra["standingOrder"] = {"id": "SO-1001", "qty": 610, "median": 500, "unit": "L"}
    if case == "kill":
        extra["killSwitch"] = {"on": True, "by": "ops"}
    res = gw.evaluate(bid, lines, [{"lineId": "L1", "qty": rl_qty, "needBy": "2026-11-16"}], **extra)
    assert res["outcome"] == expect_outcome, res["decisions"]
    if expect_rule:
        assert expect_rule in res["ruleIds"]
        assert all(d["reason"] and "{" not in d["reason"] for d in res["decisions"])


def test_strictest_wins():
    assert max(["NOTIFY", "BLOCK", "APPROVE"], key=policy.RANK.get) == "BLOCK"


def test_silent_category_suppresses_r4_and_split(gw):
    m = copy.deepcopy(gw.mandates["BUY-POHJOLA"]["mandate"])
    m["substitution"]["silentCategories"] = ["dairy"]
    m["version"] = 2
    gw.register_mandate("BUY-POHJOLA", gw.sign_mandate("BUY-POHJOLA", m))
    p1 = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")["plans"][0]
    assert p1["policy"]["outcome"] == "AUTO"
    assert {s["ruleId"] for s in p1["policy"]["suppressed"]} == {"R4", "R6"}


# ---------------- trust protocol -----------------------------------------------
def test_offer_verifies(gw):
    o = issue_offer(gw, A, None, "BUY-POHJOLA")
    v = verify_offer(gw, o, 100)
    assert v["verified"] and all(c["ok"] for c in v["checks"])


def test_tampered_price_fails_binding(gw):
    o = issue_offer(gw, A, None, "BUY-POHJOLA")
    o["unitPrice"] = 0.99
    v = verify_offer(gw, o, 100)
    assert not v["verified"] and not next(c for c in v["checks"] if c["id"] == "binding")["ok"]


def test_tampered_signature_fails(gw):
    o = issue_offer(gw, A, None, "BUY-POHJOLA")
    h, p, s = o["proof"]["jws"].split(".")
    o["proof"]["jws"] = ".".join([h, p, s[:-4] + ("AAAA" if s[-4:] != "AAAA" else "BBBB")])
    assert not verify_offer(gw, o, 100)["verified"]


def test_expired_offer_and_price_change(gw):
    o = issue_offer(gw, A, None, "BUY-POHJOLA")
    gw.clock.advance(16)
    gw.backend.set_price(A, 1.31)
    v = verify_offer(gw, o, 100)
    ids = {c["id"]: c["ok"] for c in v["checks"]}
    assert not v["verified"] and not ids["validity"] and not ids["reverify"]


def test_mandate_signature_required(gw):
    signed = gw.sign_mandate("BUY-POHJOLA", gw.buyers["BUY-POHJOLA"]["mandate"])
    signed["mandate"]["limits"]["perOrderEUR"] = 999999
    assert not gw.register_mandate("BUY-POHJOLA", signed)["ok"]


# ---------------- audit chain --------------------------------------------------
def test_audit_chain_and_tamper(gw):
    gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    assert gw.audit.verify()["ok"]
    t = gw.audit.tamper(1)
    assert t["ok"]
    v = gw.audit.verify()
    assert not v["ok"] and v["brokenAt"] == 1


# ---------------- preferences ---------------------------------------------------
def test_weights_change_ranking(gw):
    prof = gw.profiles["BUY-POHJOLA"]
    prof["org"] = {"preset": "lowest_price", "weights": {"price": 1.0}, "filters": []}
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    # with price-only weights the cheapest lactose-free milk (A @1.29) still wins; B (1.33) beats C (1.41)
    assert [i["gtin"] for i in r["lines"][0]["ranked"][:3]] == [A, B, C]
    prof["org"] = {"preset": "custom", "weights": {"delivery": 1.0}, "filters": []}
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    assert r["lines"][0]["ranked"][0]["gtin"] == C  # only C covers 1,000 L by Monday


def test_pinned_default_and_fallback(gw):
    prof = gw.profiles["BUY-POHJOLA"]
    group = catalog.need_group_id(catalog.by_gtin(B))
    prof["needGroups"][group] = {"pinned": B, "fallback": []}
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    top = r["lines"][0]["ranked"][0]
    assert top["gtin"] == B and top["rankReason"] == "Pinned default"
    gw.backend.set_stock(B, 0)
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    assert r["lines"][0]["ranked"][0]["gtin"] == A


def test_never_buy_and_required_filter(gw):
    prof = gw.profiles["BUY-POHJOLA"]
    prof["neverBuy"]["brands"] = ["Maitokaari"]
    prof["org"]["filters"] = [{"field": "maxUnitPrice", "value": 1.40, "mode": "required"}]
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    codes = {e["gtin"]: e["code"] for e in r["lines"][0]["excluded"]}
    assert codes[B] == "never_buy" and codes[C] == "filter"


def test_score_breakdown_sums(gw):
    r = gw.plan("BUY-POHJOLA", MILK, "2026-11-16")
    for it in r["lines"][0]["ranked"]:
        s = sum(b["contribution"] for b in it["breakdown"]) + sum(b["value"] for b in it["bonuses"])
        assert s == pytest.approx(it["score"], abs=1e-3)
