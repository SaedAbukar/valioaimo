"""Query spec -> SQL over the `line` table. Callers never send SQL.

Spec (all keys optional except measures):
  measures:   ["spend", "waste_pct", ...]                       names from store.SCHEMA["measures"]
  dimensions: ["category", {"field": "date", "grain": "month"}] names from store.SCHEMA["dimensions"]
  filters:    [{"field": "site", "op": "eq|neq|in|not_in|contains|gte|lte|between", "value": ...}]
  period:     {"from": "2026-01-01", "to": "2026-06-30"} or "last_month" | "last_3_months" |
              "last_6_months" | "last_30_days" | "this_year"
  compare:    "previous_period" | "previous_year"   (adds <m>_prev and <m>_change_pct; no date dimension)
  calc:       [{"type": "share|running_total|rank|change_pct|moving_avg", "of": "spend", "window": 3}]
  sort:       [{"by": "spend", "dir": "desc"}]
  limit:      int (1-500);  other: true folds the rest into one "Other" row
  dataset:    "orders" (default, the order history) | "agent_activity" | "demand" (live, analytics/datasets.py)
Every bad input raises GuardFailed with a `fix` that names what is valid.
Cross-buyer queries (Valio Aimo operations, buyer_id None) pass k_anon=3: groups with fewer than 3 buyers are
dropped (reported as `suppressed`), and grouping by a buyer-identifying field is refused.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from ..playbook.engine import GuardFailed
from .store import END, SCHEMA, START

DIMS, MEAS = SCHEMA["dimensions"], SCHEMA["measures"]
GRAINS = {"day": "date", "week": "strftime('%Y-W%W', date)", "month": "substr(date,1,7)",
          "quarter": "substr(date,1,4) || '-Q' || ((CAST(substr(date,6,2) AS INTEGER)+2)/3)"}
OPS = {"eq": "=", "neq": "!=", "gte": ">=", "lte": "<=", "contains": "LIKE", "in": "IN", "not_in": "NOT IN", "between": "BETWEEN"}
ADDITIVE = {"spend", "waste", "co2e", "kg", "quantity", "lines"}
RELATIVE = ["last_month", "last_3_months", "last_6_months", "last_30_days", "this_year"]
CALCS = ["share", "running_total", "rank", "change_pct", "moving_avg", "forecast", "anomaly"]
TIME_CALCS = {"forecast", "anomaly"}  # need exactly one dimension, the date


def _fail(msg: str, fix: str):
    raise GuardFailed(msg, fix=fix)


ORDERS = {"name": "orders", "table": "line", "schema": SCHEMA, "period": (START, END), "buyerCol": "buyer_id"}


def dataset(name: str | None) -> dict:
    from .datasets import DATASETS
    if name in (None, "orders"):
        return ORDERS
    if name not in DATASETS:
        _fail(f"Unknown dataset '{name}'.", f"Use one of: orders, {', '.join(DATASETS)}.")
    return {"name": name, **DATASETS[name]}


def _month_start(d: date, back: int) -> date:
    m = d.month - back
    y = d.year + (m - 1) // 12
    return date(y, (m - 1) % 12 + 1, 1)


def resolve_period(p, ds: dict | None = None) -> tuple[date, date]:
    START, END = (ds or ORDERS)["period"]  # noqa: N806 - the dataset's own bounds
    if p is None:
        return START, END
    if isinstance(p, str):
        if p == "last_month":
            return _month_start(END, 0), END
        if p in ("last_3_months", "last_6_months"):
            return _month_start(END, 2 if p == "last_3_months" else 5), END
        if p == "last_30_days":
            return END - timedelta(days=29), END
        if p == "this_year":
            return START, END
        _fail(f"Unknown period '{p}'.", f"Use one of {RELATIVE} or {{'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}}.")
    try:
        a, b = date.fromisoformat(p.get("from", START.isoformat())), date.fromisoformat(p.get("to", END.isoformat()))
    except (ValueError, AttributeError):
        _fail("Period dates must be YYYY-MM-DD.", "Example: {'from': '2026-01-01', 'to': '2026-03-31'}.")
    if a > b:
        _fail("Period 'from' is after 'to'.", "Swap the dates.")
    return a, b


def normalise(spec: dict, ds: dict | None = None) -> dict:
    DIMS, MEAS = (ds or ORDERS)["schema"]["dimensions"], (ds or ORDERS)["schema"]["measures"]  # noqa: N806
    if not isinstance(spec, dict):
        _fail("The query must be an object.", "Send {'measures': ['spend'], 'dimensions': ['category']}.")
    ms = spec.get("measures") or []
    if isinstance(ms, str):
        ms = [ms]
    if not ms:
        _fail("At least one measure is needed.", f"Pick from: {', '.join(MEAS)}.")
    ms = [m["field"] if isinstance(m, dict) else m for m in ms]
    for m in ms:
        if m not in MEAS:
            _fail(f"Unknown measure '{m}'.", f"Use one of: {', '.join(MEAS)}.")
    dims = []
    for d in spec.get("dimensions") or []:
        f, g = (d, None) if isinstance(d, str) else (d.get("field"), d.get("grain"))
        if f not in DIMS:
            _fail(f"Unknown dimension '{f}'.", f"Use one of: {', '.join(DIMS)}.")
        if DIMS[f]["type"] == "time":
            g = g or "month"
            if g not in GRAINS:
                _fail(f"Unknown time grain '{g}'.", f"Use one of: {', '.join(GRAINS)}.")
        dims.append({"field": f, "grain": g})
    if len(dims) > 3:
        _fail("Too many dimensions.", "Use at most 3 dimensions.")
    calc = spec.get("calc") or []
    for c in calc:
        if c.get("type") not in CALCS:
            _fail(f"Unknown calc '{c.get('type')}'.", f"Use one of: {', '.join(CALCS)}.")
        if c["type"] in TIME_CALCS and not (len(dims) == 1 and DIMS[dims[0]["field"]]["type"] == "time"):
            _fail(f"calc '{c['type']}' works on one series over time.",
                  "Use exactly one dimension: {'field': 'date', 'grain': 'month'} (or week, day, quarter).")
        if c["type"] == "forecast":
            h = c.setdefault("horizon", 3)
            if not (isinstance(h, int) and 1 <= h <= 6):
                _fail("forecast horizon must be 1 to 6 periods.", "Example: {'type': 'forecast', 'of': 'spend', 'horizon': 3}.")
        c.setdefault("of", ms[0])
        if c["of"] not in ms:
            _fail(f"calc '{c['type']}' refers to '{c['of']}', which is not a measure in this query.", f"Use one of: {', '.join(ms)}.")
    limit = spec.get("limit")
    if limit is not None and not (isinstance(limit, int) and 1 <= limit <= 500):
        _fail("limit must be a whole number from 1 to 500.", "Example: 'limit': 10.")
    if spec.get("compare") not in (None, "previous_period", "previous_year"):
        _fail(f"Unknown compare '{spec.get('compare')}'.", "Use 'previous_period' or 'previous_year'.")
    if spec.get("compare") and any(DIMS[d["field"]]["type"] == "time" for d in dims):
        _fail("compare cannot be combined with a date dimension.", "Remove the date dimension, or use calc 'change_pct' for change over time.")
    return {"measures": ms, "dimensions": dims, "filters": spec.get("filters") or [], "period": spec.get("period"),
            "compare": spec.get("compare"), "calc": calc, "sort": spec.get("sort") or [], "limit": limit,
            "other": bool(spec.get("other"))}


def _where(filters: list, buyer_id: str | None, a: date, b: date, ds: dict | None = None) -> tuple[str, list]:
    ds = ds or ORDERS
    DIMS = ds["schema"]["dimensions"]  # noqa: N806
    parts, args = ["date BETWEEN ? AND ?"], [a.isoformat(), b.isoformat()]
    if buyer_id is not None:  # a buyer sees only its own rows
        parts.insert(0, f"{ds['buyerCol']} = ?")
        args.insert(0, buyer_id)
    for f in filters:
        field, op, val = f.get("field"), f.get("op", "eq"), f.get("value")
        if field not in DIMS:
            _fail(f"Cannot filter on '{field}'.", f"Filter on one of: {', '.join(DIMS)}.")
        if op not in OPS:
            _fail(f"Unknown filter operator '{op}'.", f"Use one of: {', '.join(OPS)}.")
        col = DIMS[field]["sql"]
        if op in ("in", "not_in"):
            vals = val if isinstance(val, list) else [val]
            if not vals:
                _fail("'in' needs a list of values.", "Example: {'op': 'in', 'value': ['Dairy', 'Fish']}.")
            parts.append(f"{col} {OPS[op]} ({', '.join('?' * len(vals))})")
            args += vals
        elif op == "between":
            if not (isinstance(val, list) and len(val) == 2):
                _fail("'between' needs [low, high].", "Example: {'op': 'between', 'value': ['2026-01-01', '2026-03-31']}.")
            parts.append(f"{col} BETWEEN ? AND ?")
            args += val
        elif op == "contains":
            parts.append(f"LOWER({col}) LIKE ?")
            args.append(f"%{str(val).lower()}%")
        else:
            parts.append(f"{col} {OPS[op]} ?")
            args.append(val)
    return " AND ".join(parts), args


def _select(conn, s: dict, buyer_id: str | None, a: date, b: date, ds: dict | None = None, k_anon: int = 0) -> list[dict]:
    ds = ds or ORDERS
    DIMS, MEAS = ds["schema"]["dimensions"], ds["schema"]["measures"]  # noqa: N806
    dcols = [(d["field"], GRAINS[d["grain"]] if d["grain"] else DIMS[d["field"]]["sql"]) for d in s["dimensions"]]
    # internal aliases (d_x / m_x): an alias equal to a column name (e.g. "date") would make SQLite group by the raw column
    sel = [f"{expr} AS d_{name}" for name, expr in dcols] + [f"{MEAS[m]['sql']} AS m_{m}" for m in s["measures"]]
    if k_anon:
        sel.append(f"COUNT(DISTINCT {ds['buyerCol']}) AS k_buyers")
    where, args = _where(s["filters"], buyer_id, a, b, ds)
    sql = f"SELECT {', '.join(sel)} FROM {ds['table']} WHERE {where}"
    if dcols:
        sql += f" GROUP BY {', '.join('d_' + n for n, _ in dcols)} HAVING COUNT(*) > 0"
    cur = conn.execute(sql, args)
    names = [c[0][2:] for c in cur.description]
    rows = [dict(zip(names, r)) for r in cur.fetchall()]
    if k_anon:
        kept = [r for r in rows if (r.get("buyers") or 0) >= k_anon]
        s["_suppressed"] = s.get("_suppressed", 0) + len(rows) - len(kept)
        rows = [{k: v for k, v in r.items() if k != "buyers"} for r in kept]
    if dcols:
        rows = [r for r in rows if all(r[n] is not None for n, _ in dcols)]
    elif rows and all(rows[0][m] is None for m in s["measures"]):
        rows = []
    return rows


def run(conn, spec: dict, buyer_id: str | None, k_anon: int = 0) -> dict:
    ds = dataset((spec or {}).get("dataset") if isinstance(spec, dict) else None)
    DIMS, MEAS = ds["schema"]["dimensions"], ds["schema"]["measures"]  # noqa: N806
    s = normalise(spec, ds)
    s["dataset"] = ds["name"]
    if buyer_id is None and not k_anon:
        _fail("A cross-buyer query needs k-anonymity.", "Ask as one buyer, or as Valio Aimo operations through /v1/ops/*.")
    if k_anon and any(DIMS[d["field"]].get("identifying") for d in s["dimensions"]):
        _fail("Cross-buyer data cannot be grouped by customer, kitchen, agent or approver.",
              "Group by category, product, date, channel or decision instead.")
    a, b = resolve_period(s["period"], ds)
    rows = _select(conn, s, buyer_id, a, b, ds, k_anon)
    time_dim = next((d["field"] for d in s["dimensions"] if DIMS[d["field"]]["type"] == "time"), None)
    keys = [d["field"] for d in s["dimensions"]]
    # sort: explicit, else time ascending, else first measure descending
    order = s["sort"] or ([{"by": time_dim, "dir": "asc"}] if time_dim else [{"by": s["measures"][0], "dir": "desc"}] if keys else [])
    for o in reversed(order):
        by = o.get("by")
        if rows and by not in rows[0]:
            _fail(f"Cannot sort by '{by}'.", f"Sort by one of: {', '.join(rows[0])}.")
        rows.sort(key=lambda r: (r[by] is None, r[by]), reverse=o.get("dir", "asc") == "desc")
    if s["limit"] and len(rows) > s["limit"]:
        head, tail = rows[:s["limit"]], rows[s["limit"]:]
        if s["other"] and len(keys) == 1:
            other = {keys[0]: "Other"}
            for m in s["measures"]:
                other[m] = sum(r[m] or 0 for r in tail) if m in ADDITIVE else None
            head.append(other)
        rows = head
    if s["compare"]:
        span = (b - a).days + 1
        pa, pb = (a - timedelta(days=span), a - timedelta(days=1)) if s["compare"] == "previous_period" else \
                 (a.replace(year=a.year - 1), b.replace(year=b.year - 1))
        prev = {tuple(r[k] for k in keys): r for r in _select(conn, s, buyer_id, pa, pb, ds, k_anon)}
        for r in rows:
            p = prev.get(tuple(r[k] for k in keys), {})
            for m in s["measures"]:
                r[f"{m}_prev"] = p.get(m)
                r[f"{m}_change_pct"] = round((r[m] - p[m]) / p[m] * 100, 1) if p.get(m) and r[m] is not None else None
    _calcs(rows, s["calc"])
    if time_dim and any(c["type"] in TIME_CALCS for c in s["calc"]):
        partial = _partial_last(rows, time_dim, s, b, ds)
        for c in s["calc"]:
            if c["type"] == "anomaly":
                _anomaly(rows, time_dim, c["of"], partial)
            elif c["type"] == "forecast":
                rows = _forecast(rows, time_dim, c["of"], c["horizon"], next(d["grain"] for d in s["dimensions"]), partial)
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float):
                r[k] = round(v, 2)
    cols = [{"name": k, "label": DIMS[k]["label"], "type": DIMS[k]["type"], "role": "dimension"} for k in keys] + \
           [{"name": m, "label": MEAS[m]["label"], "unit": MEAS[m]["unit"], "role": "measure"} for m in s["measures"]]
    extra = [k for k in (rows[0] if rows else {}) if k not in keys and k not in s["measures"]]
    cols += [{"name": k, "label": _extra_label(k, MEAS), "unit": "%" if k.endswith(("_pct", "_share")) else MEAS[k.split("_")[0]]["unit"]
              if k.split("_")[0] in MEAS else None, "role": "derived"} for k in extra]
    suppressed = s.pop("_suppressed", 0)
    return {"spec": s, "columns": cols, "rows": rows, "period": {"from": a.isoformat(), "to": b.isoformat()},
            "dataset": ds["name"], **({"suppressed": suppressed, "kAnonymity": k_anon} if k_anon else {}),
            "shape": {"dims": keys, "measures": s["measures"], "timeDim": time_dim, "n": len(rows),
                      "grain": next((d["grain"] for d in s["dimensions"] if d["grain"]), None)}}


def _extra_label(k: str, meas: dict | None = None) -> str:
    base, _, kind = k.partition("_")
    m = (meas or MEAS).get(base, {}).get("label", base)
    return {"prev": f"{m}, before", "change_pct": f"{m}, change %", "share": f"{m}, share %", "running_total": f"{m}, running total",
            "rank": f"{m}, rank", "moving_avg": f"{m}, moving average", "lo": f"{m}, low estimate", "hi": f"{m}, high estimate",
            "z": f"{m}, how unusual (z)", "forecast": "Forecast", "anomaly": "Unusual", "anchor": "Last actual"}.get(kind, k)


# ---------------------------------------------------------------- forecast and anomaly (no ML: deterministic, explainable)
def _partial_last(rows, key, s, b: date, ds) -> bool:
    """The last period is still running (e.g. the month to the 12th): leave it out of fits and flags."""
    if not rows:
        return False
    grain = next((d["grain"] for d in s["dimensions"] if d["field"] == key), None)
    if grain == "month":
        nxt = date(b.year + (b.month == 12), b.month % 12 + 1, 1)
        return str(rows[-1][key]) == b.isoformat()[:7] and (nxt - b).days > 1
    if grain == "quarter":
        return str(rows[-1][key]) == f"{b.year}-Q{(b.month + 2) // 3}" and not (b.month % 3 == 0 and b.day >= 28)
    if grain == "week":
        return b.weekday() != 6 and str(rows[-1][key]) == b.strftime("%Y-W%W")
    return False


def _shift(label: str, grain: str, n: int) -> str:
    """The label n periods later (n may be negative)."""
    if grain == "month":
        y, m = map(int, label.split("-"))
        t = y * 12 + (m - 1) + n
        return f"{t // 12}-{t % 12 + 1:02d}"
    if grain == "quarter":
        y, q = label.split("-Q")
        t = int(y) * 4 + int(q) - 1 + n
        return f"{t // 4}-Q{t % 4 + 1}"
    if grain == "week":
        y, w = label.split("-W")
        d = date.fromisocalendar(int(y), max(1, int(w)), 1) + timedelta(weeks=n)
        return d.strftime("%Y-W%W")
    return (date.fromisoformat(label) + timedelta(days=n)).isoformat()


SEASON = {"month": 12, "quarter": 4, "week": 52, "day": 364}


def _forecast(rows, key, m, horizon, grain, partial):
    """Seasonal-naive (same period last year) blended 50/50 with a linear trend over the last 6 full periods.
    Bounds: +-1.28 sigma of the trend residuals (about an 80% band). Future rows carry is_forecast: true."""
    hist = rows[:-1] if partial else rows
    pts = [(i, r[m]) for i, r in enumerate(hist) if r.get(m) is not None][-6:]
    if len(pts) < 3:
        _fail("A forecast needs at least 3 full periods of history.", "Widen the period or use a coarser grain.")
    n = len(pts)
    mx, my = sum(i for i, _ in pts) / n, sum(v for _, v in pts) / n
    sxx = sum((i - mx) ** 2 for i, _ in pts) or 1
    slope = sum((i - mx) * (v - my) for i, v in pts) / sxx
    trend = lambda i: my + slope * (i - mx)  # noqa: E731
    sigma = (sum((v - trend(i)) ** 2 for i, v in pts) / max(1, n - 2)) ** 0.5
    by_label = {str(r[key]): r[m] for r in hist}
    last_i, last_label = len(hist) - 1, str(hist[-1][key])
    out = [dict(r, is_forecast=False) for r in rows]
    for r in out:
        if str(r[key]) == last_label:
            r["forecast_anchor"] = True
            r[f"{m}_lo"] = r[f"{m}_hi"] = r[m]
    nonneg = all(v >= 0 for _, v in pts)
    if partial:
        out[-1]["is_partial"] = True  # still running: shown, but not fitted and not forecast over
    for k in range(1, horizon + 1 + (1 if partial else 0)):
        label = _shift(last_label, grain, k)
        t = trend(last_i + k)
        seas = by_label.get(_shift(label, grain, -SEASON[grain]))
        f = 0.5 * seas + 0.5 * t if seas is not None else t
        lo, hi = f - 1.28 * sigma, f + 1.28 * sigma
        if nonneg:
            f, lo = max(0.0, f), max(0.0, lo)
        if partial and label == str(rows[-1][key]):
            continue
        out.append({key: label, m: f, f"{m}_lo": lo, f"{m}_hi": hi, "is_forecast": True,
                    "forecast_basis": "same period last year + trend" if seas is not None else "trend of the last 6 periods"})
    return out


def _anomaly(rows, key, m, partial):
    """Robust z-score against the moving median of the previous 6 periods (MAD, floored at 5% of the median);
    |z| > 3 is unusual."""
    vals = [r.get(m) for r in rows]
    for i, r in enumerate(rows):
        r["is_anomaly"] = False
        win = [v for v in vals[max(0, i - 6):i] if v is not None]
        if len(win) < 3 or vals[i] is None or (partial and i == len(rows) - 1):
            r[f"{m}_z"] = None
            continue
        med = statistics.median(win)
        # floor at 5% of the median: ordinary +-15% swings in a kitchen's month are not "unusual"
        mad = max(statistics.median(abs(v - med) for v in win), 0.05 * abs(med))
        if mad == 0:
            r[f"{m}_z"] = None
            continue
        z = 0.6745 * (vals[i] - med) / mad
        r[f"{m}_z"] = round(z, 2)
        r["is_anomaly"] = abs(z) > 3


def _calcs(rows: list[dict], calcs: list[dict]):
    for c in calcs:
        m, t = c["of"], c["type"]
        vals = [r[m] or 0 for r in rows]
        if t == "share":
            tot = sum(vals) or 1
            for r, v in zip(rows, vals):
                r[f"{m}_share"] = v / tot * 100
        elif t == "running_total":
            run_ = 0.0
            for r, v in zip(rows, vals):
                run_ += v
                r[f"{m}_running_total"] = run_
        elif t == "rank":
            order = sorted(range(len(rows)), key=lambda i: -vals[i])
            for rank, i in enumerate(order, 1):
                rows[i][f"{m}_rank"] = rank
        elif t == "change_pct":
            for i, r in enumerate(rows):
                r[f"{m}_change_pct"] = None if i == 0 or not vals[i - 1] else (vals[i] - vals[i - 1]) / vals[i - 1] * 100
        elif t == "moving_avg":
            w = max(2, int(c.get("window", 3)))
            for i, r in enumerate(rows):
                win = vals[max(0, i - w + 1): i + 1]
                r[f"{m}_moving_avg"] = sum(win) / len(win)
