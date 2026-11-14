"""Small shared helpers: canonical JSON, ids, templating, dates, text normalisation."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta


def canonical(obj) -> str:
    """Deterministic JSON used for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


_TPL = re.compile(r"\{(\w+)\}")


def render(template: str, values: dict) -> str:
    """Tiny templating ({name}) shared 1:1 with the JS port; unknown keys stay visible."""
    return _TPL.sub(lambda m: str(values.get(m.group(1), "{" + m.group(1) + "}")), template)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def d2s(d: date) -> str:
    return d.isoformat()


def s2d(s: str) -> date:
    return date.fromisoformat(s[:10])


def delivery_day(d: date) -> date:
    """No deliveries on Sundays: roll forward to Monday."""
    return d + timedelta(days=1) if d.weekday() == 6 else d


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_label(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()][:3]} {d.day}.{d.month}."


def norm_token(t: str) -> str:
    t = t.lower()
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("oes"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokens(text: str) -> list[str]:
    return [norm_token(t) for t in re.findall(r"[a-zåäö0-9]+", text.lower())]


def money(x: float) -> str:
    return f"€{x:,.2f}"


def r2(x: float) -> float:
    return round(x + 1e-9, 2)
