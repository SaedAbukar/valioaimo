"""Rate limits per credential: a token bucket (rate per minute, burst). Over the limit an agent gets
429 rate_limited with retryAfter and the Retry-After header (RFC 9110). Valio Aimo operations are exempt.
AIMO_RATE_PER_MIN and AIMO_RATE_BURST override the defaults (120 per minute, burst 30)."""
from __future__ import annotations

import os
import threading
import time


class RateLimiter:
    def __init__(self, rate_per_min: float = 120, burst: int = 30, now=time.monotonic):
        self.rate = rate_per_min / 60.0
        self.burst = float(burst)
        self.now = now
        self.buckets: dict[str, tuple[float, float]] = {}  # token -> (tokens, last)
        self.lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "RateLimiter":
        return cls(float(os.environ.get("AIMO_RATE_PER_MIN", 120)), int(float(os.environ.get("AIMO_RATE_BURST", 30))))

    def check(self, key: str) -> float | None:
        """Take one token for key. Returns None when allowed, else the seconds to wait."""
        with self.lock:
            t = self.now()
            tokens, last = self.buckets.get(key, (self.burst, t))
            tokens = min(self.burst, tokens + (t - last) * self.rate)
            if tokens >= 1:
                self.buckets[key] = (tokens - 1, t)
                return None
            self.buckets[key] = (tokens, t)
            return round((1 - tokens) / self.rate, 2)
