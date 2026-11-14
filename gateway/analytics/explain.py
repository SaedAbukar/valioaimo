"""Plain-language caption and three facts for a query result (no model needed)."""
from __future__ import annotations

from datetime import date

from .store import all_fields

SCHEMA = all_fields()

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt(v, unit: str | None) -> str:
    if v is None:
        return "–"
    if unit == "EUR":
        return f"€{v:,.0f}" if abs(v) >= 100 else f"€{v:,.2f}"
    if unit == "%":
        return f"{v:.1f}%"
    if unit in ("kg", "kg CO2e"):
        return f"{v:,.0f} kg" + (" CO₂e" if unit == "kg CO2e" else "")
    if unit == "EUR/unit":
        return f"€{v:,.2f}"
    return f"{v:,.0f}"


def period_label(p: dict) -> str:
    a, b = date.fromisoformat(p["from"]), date.fromisoformat(p["to"])
    if a.year == b.year and a.month == b.month:
        return f"{MONTHS[a.month - 1]} {a.year}"
    return f"{MONTHS[a.month - 1]} {a.year if a.year != b.year else ''}".strip() + f" – {MONTHS[b.month - 1]} {b.year}"


def label_of(key, value) -> str:
    if key == "date" and isinstance(value, str) and len(value) == 7:
        y, m = value.split("-")
        return f"{MONTHS[int(m) - 1]} {y}"
    return str(value)


def run(result: dict, spec: dict | None = None) -> dict:
    rows, shape = result["rows"], result["shape"]
    meas = SCHEMA["measures"]
    if not rows:
        return {"caption": "No orders match these filters.", "facts": ["Try a longer period.", "Or remove a filter.", "Or pick another kitchen."]}
    m = shape["measures"][0]
    unit = meas[m]["unit"]
    dims = shape["dims"]
    grain = shape.get("grain")
    by = " by " + " and ".join((grain if d == "date" and grain else SCHEMA["dimensions"][d]["label"].lower()) for d in dims) if dims else ""
    caption = f"{meas[m]['label']}{by}, {period_label(result['period'])}."
    facts: list[str] = []
    if not dims:
        facts.append(f"{meas[m]['label']}: {fmt(rows[0][m], unit)}.")
        for extra in shape["measures"][1:3]:
            facts.append(f"{meas[extra]['label']}: {fmt(rows[0][extra], meas[extra]['unit'])}.")
    else:
        key = dims[0]
        vals = [r for r in rows if r.get(m) is not None and r[key] != "Other"]
        # a month that is still running would look like the lowest month / a drop for totals
        partial = bool(vals) and shape["timeDim"] == key and grain == "month" and str(vals[-1][key]) == result["period"]["to"][:7] \
            and int(result["period"]["to"][8:]) < 28 and unit in ("EUR", "kg", "kg CO2e", "count", "units") and len(vals) > 2
        full = vals[:-1] if partial else vals
        if vals:
            hi = max(full, key=lambda r: r[m])
            lo = min(full, key=lambda r: r[m])
            facts.append(f"Highest: {label_of(key, hi[key])} ({fmt(hi[m], unit)}).")
            facts.append(f"Lowest: {label_of(key, lo[key])} ({fmt(lo[m], unit)}).")
            if shape["timeDim"] == key and len(vals) > 1 and vals[0][m]:
                end = full[-1]
                ch = (end[m] - vals[0][m]) / vals[0][m] * 100
                facts.append(f"{'Up' if ch >= 0 else 'Down'} {abs(ch):.0f}% from {label_of(key, vals[0][key])} to {label_of(key, end[key])}"
                             + (f"; {label_of(key, vals[-1][key]).split()[0]} is still running." if partial else "."))
            elif unit in ("EUR", "kg", "kg CO2e", "count", "units"):
                tot = sum(r[m] or 0 for r in rows)
                facts.append(f"The top one is {hi[m] / tot * 100:.0f}% of the total {fmt(tot, unit)}." if tot else f"Total {fmt(tot, unit)}.")
            else:
                avg = sum(r[m] for r in vals) / len(vals)
                facts.append(f"Average: {fmt(avg, unit)}.")
    if shape.get("timeDim") and dims:
        key = dims[0]
        odd = [r for r in rows if r.get("is_anomaly")]
        fut = [r for r in rows if r.get("is_forecast")]
        if odd:  # unusual periods first: they are why someone asked
            r = max(odd, key=lambda x: abs(x.get(f"{m}_z") or 0))
            facts.insert(0, f"Unusual: {label_of(key, r[key])} ({fmt(r[m], unit)}), far from the months before it.")
        if fut:
            a_, b_ = fut[0], fut[-1]
            facts.insert(0, f"Forecast: about {fmt(b_[m], unit)} by {label_of(key, b_[key])} (likely {fmt(b_[m + '_lo'], unit)}–"
                            f"{fmt(b_[m + '_hi'], unit)}), from the same months last year and the recent trend.")
    while len(facts) < 3:
        facts.append(f"{len(rows)} rows from {period_label(result['period'])}.")
    return {"caption": caption, "facts": facts[:3]}
