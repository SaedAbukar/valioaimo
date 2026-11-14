"""Backend adapter: the ONLY place that talks to Valio Aimo systems.

FixtureBackend  – default; synthetic catalog, price and stock (repeatable demo).
AimoApiBackend  – optional; reads the organisers' mock API when AIMO_API_KEY and
                  AIMO_BASE_URL are set (urllib, no extra deps). Any failure falls
                  back to fixtures so the demo never breaks.
"""
from __future__ import annotations

import json
import os
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
        self.inbound = {p["gtin"]: [dict(x) for x in p["inbound"]] for p in catalog.products()}
        self.prices = {p["gtin"]: p["unitPrice"] for p in catalog.products()}
        self.orders: list[dict] = []

    # --- reads ---------------------------------------------------------------
    def product(self, gtin: str) -> dict | None:
        return catalog.by_gtin(gtin)

    def price(self, gtin: str) -> float:
        return self.prices[gtin]

    def earliest(self, gtin: str) -> date:
        p = catalog.by_gtin(gtin)
        return delivery_day(self.clock.today() + timedelta(days=p["leadTimeDays"]))

    def schedule(self, gtin: str) -> list[dict]:
        """Deliverable quantities by date: [{date, qty}] (stock from earliest date, then inbound)."""
        today = self.clock.today()
        out = []
        if self.stock[gtin] > 0:
            out.append({"date": d2s(self.earliest(gtin)), "qty": self.stock[gtin]})
        for ib in self.inbound[gtin]:
            d = max(delivery_day(today + timedelta(days=ib["inDays"])), self.earliest(gtin))
            out.append({"date": d2s(d), "qty": ib["qty"]})
        return out

    def available_by(self, gtin: str, by: date) -> float:
        return sum(s["qty"] for s in self.schedule(gtin) if s["date"] <= d2s(by))

    # --- writes --------------------------------------------------------------
    def place_order(self, order: dict) -> dict:
        for ln in order["lines"]:
            g, q = ln["gtin"], ln["qty"]
            take = min(self.stock[g], q)
            self.stock[g] -= take
            rest = q - take
            for ib in self.inbound[g]:
                if rest <= 0:
                    break
                t = min(ib["qty"], rest)
                ib["qty"] -= t
                rest -= t
        self.orders.append(order)
        return {"backendOrderRef": f"AIMO-SO-{len(self.orders) + 880000}", "status": "confirmed"}

    # --- demo controls -------------------------------------------------------
    def set_stock(self, gtin: str, qty: float):
        self.stock[gtin] = qty

    def set_price(self, gtin: str, price: float):
        self.prices[gtin] = price


class AimoApiBackend(FixtureBackend):
    """Plug-in point for the organisers' mock API (junction26.valioaimo.fi).

    The mock API's exact paths are configured via env (AIMO_PATH_PRODUCT, AIMO_PATH_STOCK);
    responses are mapped onto the fixture shapes. Not reachable from the build sandbox,
    so it is exercised only when credentials are present.
    """
    name = "aimo-api"

    def __init__(self, clock, base_url: str, api_key: str):
        super().__init__(clock)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.path_stock = os.environ.get("AIMO_PATH_STOCK", "/api/products/{gtin}/availability")
        self.path_price = os.environ.get("AIMO_PATH_PRICE", "/api/products/{gtin}/price")

    def _get(self, path: str) -> dict | None:
        req = urllib.request.Request(self.base_url + path, headers={"Authorization": f"Bearer {self.api_key}",
                                                                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001 - fall back to fixtures
            return None

    def price(self, gtin: str) -> float:
        data = self._get(self.path_price.format(gtin=gtin))
        if data and isinstance(data.get("unitPrice"), (int, float)):
            return float(data["unitPrice"])
        return super().price(gtin)


def make_backend(clock):
    base, key = os.environ.get("AIMO_BASE_URL"), os.environ.get("AIMO_API_KEY")
    if base and key:
        return AimoApiBackend(clock, base, key)
    return FixtureBackend(clock)
