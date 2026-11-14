"""Task 18 (audit H4): the mock API adapter retries with jitter, opens a circuit breaker, falls back to
flagged demo values, and a slow backend never blocks other requests."""
import os
import threading
import time

from starlette.testclient import TestClient

os.environ["AIMO_SEED_DEMO"] = "0"
from gateway.adapter import AimoApiClient  # noqa: E402
from gateway.__main__ import make_app  # noqa: E402
from gateway import lookup  # noqa: E402
from gateway.core import Gateway  # noqa: E402

AGENT = {"Authorization": "Bearer demo-key-pohjola"}


class Failing(AimoApiClient):
    def __init__(self):
        super().__init__("http://mock.invalid", "k")
        self.sent = 0
        self.t = 0.0
        self.now = lambda: self.t
        self.sleep = lambda s: None

    def _send(self, path, body, timeout):
        self.sent += 1
        raise TimeoutError("timed out")


def test_retry_then_breaker_opens_and_stops_calling():
    c = Failing()
    assert c.prices(["1"], "2026-11-16") == {} and c.sent == 2  # one retry with jitter
    c.prices(["2"], "2026-11-16")  # 4 failures in a row -> open
    assert c.breaker_state() == "open"
    n = c.sent
    assert c.prices(["3"], "2026-11-16") == {} and c.sent == n  # open: no network call at all
    assert c.last_error == "TimeoutError" or c.last_error == "circuit_open"
    c.t += 31  # cool-down over: one trial call (half-open)
    c.prices(["4"], "2026-11-16")
    assert c.sent == n + 1 and c.breaker_state() == "open"


def test_breaker_closes_after_a_success():
    c = Failing()
    c.prices(["1"], "d"), c.prices(["2"], "d")
    assert c.breaker_state() == "open"
    c.t += 31
    c._send = lambda path, body, timeout: {"products": [{"productId": "9", "catalogPrice": {"value": 1.0}}]}
    assert "9" in c.prices(["9"], "d") and c.breaker_state() == "closed"


def test_fallback_is_flagged_in_lookup():
    gw = Gateway()
    gw.aimo = Failing()
    for _ in range(2):
        r = lookup.search(gw, "lactose-free milk", qty=10, limit=3)
    assert r["live"] is False and r["fallback"]["reason"] in ("mock API unavailable", "circuit open")
    assert all(p["price"]["source"] == "demo-values" for p in r["products"])


def test_health_shows_error_class_only(monkeypatch):
    c = TestClient(make_app(live=False))
    gw = c.app.state.gw()
    f = Failing()
    f.last_error = "URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known: secret-host.example>"
    gw.aimo = f
    f.ping = lambda: False
    h = c.get("/health").json()
    assert h["liveApi"]["error"] == "URLError" and "secret-host" not in c.get("/health").text
    assert h["liveApi"]["breaker"] in ("closed", "open", "half_open")


def test_slow_backend_does_not_block_other_requests():
    class Slow(Failing):
        def _send(self, path, body, timeout):
            time.sleep(1.5)
            return {"products": []}

    with TestClient(make_app(live=False)) as c:  # one event loop for all requests, as in uvicorn
        c.app.state.gw().aimo = Slow()
        th = threading.Thread(target=lambda: c.post("/v1/products/search", json={"query": "milk"}, headers=AGENT))
        th.start()
        time.sleep(0.2)
        t0 = time.perf_counter()
        assert c.get("/v1/rules").status_code == 200
        assert time.perf_counter() - t0 < 0.5
        th.join()
