"""v5 hardening: no oversell, idempotency, typed inputs, push events, restart, rate limits."""
import os
import threading

import pytest
from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
os.environ.setdefault("AIMO_RATE_PER_MIN", "100000")
from gateway.__main__ import make_app  # noqa: E402
from gateway.core import Gateway  # noqa: E402
from gateway.playbook.engine import StepNotAllowed  # noqa: E402
from gateway.playbook.tools import offer_ids  # noqa: E402
from gateway.util import s2d  # noqa: E402

BRIEF = ("I need 1,000 litres of lactose-free milk by Monday. "
         "Find an option that meets our requirements based on price and availability.")
AGENT = {"Authorization": "Bearer demo-key-pohjola"}
LAURA = {"Authorization": "Bearer demo-human-usr-lvirtanen"}
TO_PRESENT = ("parse_request", "recall", "plan_basket", "check_basket", "render_cards")


@pytest.fixture()
def c():
    return TestClient(make_app(live=False))


def in_process_to_present(gw, text=BRIEF):
    sid = gw.engine.call(None, "start_session", {"buyerId": "BUY-POHJOLA"})["sessionId"]
    for t in TO_PRESENT:
        gw.engine.call(sid, t, {"text": text} if t == "parse_request" else {})
    return sid, gw.engine.sessions[sid]


def http_to_present(c, text=BRIEF, headers=AGENT):
    sid = c.post("/v1/sessions", json={}, headers=headers).json()["sessionId"]
    out = {}
    for t in TO_PRESENT:
        r = c.post(f"/v1/sessions/{sid}/tools/{t}", json={"text": text} if t == "parse_request" else {}, headers=headers)
        assert r.status_code == 200, (t, r.json())
        out[t] = r.json()["output"]
    return sid, out


# ---------------------------------------------------------------- Task 1: no overselling
def test_place_order_rechecks_stock():
    gw = Gateway()
    sid, s = in_process_to_present(gw)
    gtin = s["data"]["plan"]["lines"][0]["gtin"]
    gw.backend.set_stock(gtin, 100)
    gw.backend.inbound[gtin] = []
    gw.backend.base_stock[gtin] = 0
    with pytest.raises(StepNotAllowed) as e:
        gw.engine.call(sid, "place_order", {"offerIds": offer_ids(s)})
    assert e.value.extra["guard"] == "stock_changed"
    assert e.value.extra["next_allowed_tools"] == ["plan_basket"] and e.value.extra["shortfall"]
    assert not gw.backend.orders


def test_concurrent_orders_never_oversell(c):
    n = 8
    g = c.app.state.gw()
    plans = [http_to_present(c) for _ in range(n)]
    start = {}
    for _, out in plans:
        for l in out["plan_basket"]["lines"]:
            start.setdefault(l["gtin"], g.backend.available_by(l["gtin"], s2d(l["deliveryDate"])))
    results = [None] * n
    barrier = threading.Barrier(n)

    def go(i):
        sid, out = plans[i]
        barrier.wait()
        results[i] = c.post(f"/v1/sessions/{sid}/tools/place_order",
                            json={"offerIds": [o["offerId"] for o in out["plan_basket"]["offers"]]}, headers=AGENT)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ordered: dict[str, float] = {}
    for o in g.backend.orders:
        for ln in o["lines"]:
            ordered[ln["gtin"]] = ordered.get(ln["gtin"], 0) + ln["qty"]
    for gtin, q in ordered.items():
        assert q <= start[gtin] + 1e-9, (gtin, q, start[gtin])
    losers = [r for r in results if r.status_code != 200]
    assert losers, "8 x 1,000 L must exceed the stock of the planned product"
    assert all(r.status_code == 409 and r.json()["guard"] == "stock_changed" for r in losers)
    assert len(g.backend.orders) == n - len(losers)
