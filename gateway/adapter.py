"""Backend adapter: the ONLY place that talks to Valio Aimo systems.

FixtureBackend  – synthetic stock / price for the curated demo assortment
                  (repeatable golden scenarios), plus bridged real products.
AimoApiClient   – the organisers' mock API (junction26.valioaimo.fi):
                  POST /api/price and POST /api/availability with X-API-Key,
                  1–1000 product codes per call. Used only for real Valio Aimo
                  product codes, only for products already narrowed down by
                  the playbook (never "all products"), cached for 5 minutes.
                  Any failure falls back to deterministic fixture values so the
                  demo never breaks. See docs/MOCK_API_NOTES.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import date, timedelta

from . import catalog
from .util import d2s, delivery_day


class FixtureBackend:
    name = "fixtures"

    def __init__(self, clock):
        self.clock = clock
        self.reset()

    def reset(self):
        self.stock = {p["gtin"]: p["stock"] for p in catalog.products()}
        self.base_stock = dict(self.stock)  # weekly restock level (demo assumption, docs/ASSUMPTIONS.md)
        self.inbound = {p["gtin"]: [dict(x) for x in p["inbound"]] for p in catalog.products()}
        self.prices = {p["gtin"]: p["unitPrice"] for p in catalog.products()}
        self.earliest_override: dict[str, date] = {}
        self.orders: list[dict] = []
        self.live: dict[str, dict] = {}  # curated products priced from the mock API (live mode)

    # --- real products bridged in by Discover --------------------------------
    def register(self, gtin: str, price: float, stock: float, earliest: date | None = None):
        self.prices[gtin] = price
        self.stock[gtin] = stock
        self.inbound.setdefault(gtin, [])
        if earliest:
            self.earliest_override[gtin] = earliest

    # --- reads ---------------------------------------------------------------
    def product(self, gtin: str) -> dict | None:
        return catalog.by_gtin(gtin)

    def price(self, gtin: str) -> float:
        return self.prices[gtin]

    def earliest(self, gtin: str) -> date:
        if gtin in self.earliest_override:
            return max(self.earliest_override[gtin], self.clock.today() + timedelta(days=1))
        p = catalog.by_gtin(gtin)
        return delivery_day(self.clock.today() + timedelta(days=p["leadTimeDays"]))

    def schedule(self, gtin: str) -> list[dict]:
        """Deliverable quantities by date: [{date, qty}] (stock from earliest date, then inbound)."""
        today = self.clock.today()
        out = []
        if self.stock.get(gtin, 0) > 0:
            out.append({"date": d2s(self.earliest(gtin)), "qty": self.stock[gtin]})
        for ib in self.inbound.get(gtin, []):
            d = max(delivery_day(today + timedelta(days=ib["inDays"])), self.earliest(gtin))
            out.append({"date": d2s(d), "qty": ib["qty"]})
        for week in range(1, 7):  # regular weekly restock for planning further ahead
            if self.base_stock.get(gtin):
                out.append({"date": d2s(delivery_day(today + timedelta(days=7 * week))), "qty": self.base_stock[gtin], "restock": True})
        return sorted(out, key=lambda x: x["date"])

    def available_by(self, gtin: str, by: date) -> float:
        return sum(s["qty"] for s in self.schedule(gtin) if s["date"] <= d2s(by))

    # --- writes --------------------------------------------------------------
    def place_order(self, order: dict) -> dict:
        for ln in order["lines"]:
            g, q = ln["gtin"], ln["qty"]
            take = min(self.stock.get(g, 0), q)
            self.stock[g] = self.stock.get(g, 0) - take
            rest = q - take
            for ib in self.inbound.get(g, []):
                if rest <= 0:
                    break
                t = min(ib["qty"], rest)
                ib["qty"] -= t
                rest -= t
        self.orders.append(order)
        return {"backendOrderRef": f"AIMO-SO-{len(self.orders) + 880000}", "status": "confirmed"}

    def release(self, order: dict):
        """Give back the stock of an order that is being replaced (e.g. guest count changed)."""
        for ln in order["lines"]:
            self.stock[ln["gtin"]] = self.stock.get(ln["gtin"], 0) + ln["qty"]
        self.orders = [o for o in self.orders if o.get("orderId") != order.get("orderId")]

    # --- demo controls -------------------------------------------------------
    def set_stock(self, gtin: str, qty: float):
        self.stock[gtin] = qty

    def set_price(self, gtin: str, price: float):
        self.prices[gtin] = price


def demo_value(product_id: str, lo: float, hi: float) -> float:
    """Deterministic stand-in value when the live API is not configured."""
    h = int(hashlib.sha256(product_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(lo + (hi - lo) * h, 2)


class AimoApiClient:
    """Thin client for the Valio Aimo mock API (OpenAPI: data_raw/aimo_openapi.json)."""

    TTL = 300
    # The API sits behind Cloudflare, which answers 403 to Python's default "Python-urllib" agent.
    UA = "aimo-agent-gateway/0.2"

    def __init__(self, base_url: str, api_key: str, customer: str = "junction-demo"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.customer = customer
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self.calls = 0
        self.last_error: str | None = None

    def _post(self, path: str, body: dict) -> dict | None:
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"X-API-Key": self.api_key, "Content-Type": "application/json",
                                              "Accept": "application/json", "User-Agent": self.UA})
        try:
            self.calls += 1
            with urllib.request.urlopen(req, timeout=8) as r:
                self.last_error = None
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001 - fall back to fixtures
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def ping(self) -> bool:
        req = urllib.request.Request(self.base_url + "/api/ping", headers={"X-API-Key": self.api_key, "User-Agent": self.UA})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    def _batch(self, path: str, ids: list[str], requested: str) -> dict[str, dict]:
        out, todo = {}, []
        now = time.time()
        for i in dict.fromkeys(ids):
            hit = self._cache.get((path, i, requested))
            if hit and now - hit[0] < self.TTL:
                out[i] = hit[1]
            else:
                todo.append(i)
        for k in range(0, len(todo), 1000):
            chunk = todo[k:k + 1000]
            data = self._post(path, {"customer": self.customer, "requestedDate": requested, "products": chunk})
            for row in (data or {}).get("products", []):
                pid = str(row.get("productId"))
                self._cache[(path, pid, requested)] = (now, row)
                out[pid] = row
        return out

    def prices(self, ids: list[str], requested: str) -> dict[str, dict]:
        return self._batch("/api/price", ids, requested)

    def availability(self, ids: list[str], requested: str) -> dict[str, dict]:
        return self._batch("/api/availability", ids, requested)


def make_client() -> AimoApiClient | None:
    base, key = os.environ.get("AIMO_BASE_URL"), os.environ.get("AIMO_API_KEY")
    return AimoApiClient(base, key) if base and key else None


def load_dotenv(path) -> None:
    """Minimal .env reader (no extra dependency). Never overrides real env vars."""
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass
