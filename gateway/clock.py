"""Demo clock.

Scenarios must be repeatable, so by default the gateway runs on a *demo clock*
anchored at Friday 2026-11-13 09:00 Europe/Helsinki (07:00Z) that ticks in real
time from process start. `advance()` lets the demo (and tests) jump forward to
show offer expiry. Set AIMO_CLOCK=real to use wall-clock time.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

ANCHOR = datetime(2026, 11, 13, 7, 0, 0, tzinfo=timezone.utc)  # 09:00 EET
HELSINKI = timezone(timedelta(hours=2))


class Clock:
    def __init__(self, mode: str | None = None, frozen: bool = False):
        self.mode = mode or os.environ.get("AIMO_CLOCK", "demo")
        self.frozen = frozen
        self._start = time.monotonic()
        self.skew = timedelta(0)

    def now(self) -> datetime:
        if self.mode == "real":
            base = datetime.now(timezone.utc)
        else:
            elapsed = 0.0 if self.frozen else time.monotonic() - self._start
            base = ANCHOR + timedelta(seconds=elapsed)
        return (base + self.skew).replace(microsecond=0)

    def today(self) -> date:
        return self.now().astimezone(HELSINKI).date()

    def advance(self, minutes: float) -> datetime:
        self.skew += timedelta(minutes=minutes)
        return self.now()

    def reset(self):
        self._start = time.monotonic()
        self.skew = timedelta(0)
