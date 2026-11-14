"""Chart intent -> Vega-Lite v5 spec. Models pick a type (and optionally fields); the gateway
writes the spec, so even a small model never has to know Vega-Lite.

intent = {"type": one of TYPES, "x"?: field, "y"?: field, "color"?: field, "size"?: field, "title"?: str}
Specs carry no colours; the page applies its light/dark theme as Vega-Lite config.
"""
from __future__ import annotations

from ..playbook.engine import GuardFailed
from .explain import label_of
from .store import SCHEMA

SCHEMA_URL = "https://vega.github.io/schema/vega-lite/v5.json"
TYPES = {
    "line": "Trend over time", "area": "Trend with volume", "column": "Compare a few values, vertical",
    "bar": "Rank categories, horizontal", "stacked": "Totals split into parts", "grouped": "Side-by-side parts",
    "percent": "Mix of parts (100%)", "heatmap": "Two categories at once", "donut": "Share of a whole (few parts)",
    "scatter": "Two measures against each other", "bubble": "Three measures at once", "histogram": "How values spread",
    "boxplot": "Spread per category", "waterfall": "What drove the change", "kpi": "One big number",
    "sparkline": "Tiny trend", "table": "All the numbers",
}


def _cols(result):
    sh = result["shape"]
    dims = sh["dims"]
    time = sh["timeDim"]
    cats = [d for d in dims if d != time]
    return dims, time, cats, sh["measures"], len(result["rows"])


def fits(result) -> list[str]:
    dims, time, cats, meas, n = _cols(result)
    out = []
    if not dims:
        return ["kpi", "table"]
    if time and len(dims) == 1:
        out += ["line", "area", "column", "waterfall", "sparkline"]
    if time and len(dims) == 2:
        out += ["line", "area", "stacked", "grouped", "percent", "heatmap", "boxplot"]
    if not time and len(dims) == 1:
        out += ["bar", "column", "waterfall"] + (["donut"] if n <= 10 else [])
    if not time and len(dims) == 2:
        out += ["heatmap", "stacked", "grouped", "percent", "boxplot"]
    if len(meas) >= 2 and dims:
        out += ["scatter"] + (["bubble"] if len(meas) >= 2 else [])
    if n >= 8 and dims:
        out.append("histogram")
    out.append("table")
    return list(dict.fromkeys(out))


def suggest(result) -> list[dict]:
    dims, time, cats, meas, n = _cols(result)
    order: list[str] = []
    if not dims:
        order = ["kpi"]
    elif len(meas) >= 2 and not time:
        order = ["scatter", "bubble"]
    elif time and len(dims) == 1:
        order = ["line", "area", "column"]
    elif time:
        order = ["line", "stacked", "heatmap"]
    elif len(dims) == 2:
        order = ["heatmap", "stacked", "grouped"]
    else:
        share = any(c["name"].endswith("_share") for c in result["columns"])
        order = (["donut", "bar"] if share and n <= 8 else ["bar", "donut" if n <= 8 else "column"])
    ok = fits(result)
    out = [t for t in order if t in ok] + [t for t in ok if t not in order]
    return [{"type": t, "why": TYPES[t]} for t in out[:5]]


def _field(result, name):
    c = next((c for c in result["columns"] if c["name"] == name), None)
    if not c:
        raise GuardFailed(f"'{name}' is not in the result.", fix=f"Use one of: {', '.join(x['name'] for x in result['columns'])}.")
    return c


def _enc(result, name, axis_type=None, **extra):
    c = _field(result, name)
    title = c["label"] + (f" ({'€' if c.get('unit') == 'EUR' else c['unit']})" if c.get("unit") and c["unit"] not in ("count", "units") else "")
    if axis_type is None:
        if c["role"] != "dimension":
            axis_type = "quantitative"
        elif c.get("type") == "time" and result["shape"]["grain"] in ("month", "day"):
            axis_type = "temporal"
        else:
            axis_type = "nominal"
    e = {"field": name, "type": axis_type, "title": title}
    if axis_type == "temporal":
        e["timeUnit"] = "yearmonth" if result["shape"]["grain"] == "month" else "yearmonthdate"
        e["axis"] = {"format": "%b %y" if result["shape"]["grain"] == "month" else "%d %b"}
    e.update(extra)
    return e


def _tooltip(result):
    return [_enc(result, c["name"]) | ({"format": ",.1f"} if c["role"] != "dimension" else {}) for c in result["columns"][:6]]


def build(result, intent: dict) -> dict:
    t = (intent or {}).get("type")
    if t not in TYPES:
        raise GuardFailed(f"Unknown chart type '{t}'.", fix=f"Use one of: {', '.join(TYPES)}.")
    ok = fits(result)
    if t not in ok:
        raise GuardFailed(f"A {t} chart does not fit this result.", fix=f"These fit: {', '.join(ok)}. Or change the query.")
    if not result["rows"]:
        raise GuardFailed("The result is empty.", fix="Widen the period or remove a filter, then run_query again.")
    dims, time, cats, meas, n = _cols(result)
    if t == "table":
        return {"type": "table", "columns": result["columns"], "rows": result["rows"], "title": intent.get("title")}
    m = intent.get("y") or meas[0]
    x = intent.get("x") or (time or (dims[0] if dims else None))
    color = intent.get("color") or next((d for d in dims if d != x), None)
    spec = {"$schema": SCHEMA_URL, "data": {"values": result["rows"]}, "width": "container",
            "height": 260 if t not in ("sparkline", "kpi") else 60, "usermeta": {"chartType": t}}
    if intent.get("title"):
        spec["title"] = intent["title"]
    tip = _tooltip(result)
    if t in ("line", "area", "sparkline"):
        spec["mark"] = {"type": "line" if t != "area" else "area", "point": t == "line" and n <= 24, "interpolate": "monotone",
                        "strokeWidth": 2.5, **({"line": True, "opacity": 0.25} if t == "area" else {})}
        spec["encoding"] = {"x": _enc(result, x), "y": _enc(result, m), "tooltip": tip}
        if color and color != x:
            spec["encoding"]["color"] = _enc(result, color)
        if t == "sparkline":
            spec["encoding"]["x"]["axis"] = None
            spec["encoding"]["y"]["axis"] = None
            spec["config"] = {"view": {"stroke": None}}
    elif t in ("column", "bar"):
        cat = x if t == "column" else (intent.get("x") or dims[0])
        val = _enc(result, m)
        key = _enc(result, cat, sort="-x" if t == "bar" and cat != time else None)
        if key.get("sort") is None:
            key.pop("sort", None)
        spec["mark"] = {"type": "bar", "cornerRadiusEnd": 4}
        spec["encoding"] = {"x": key, "y": val, "tooltip": tip} if t == "column" else {"y": key, "x": val, "tooltip": tip}
        if t == "column" and key["type"] == "temporal":
            key["type"] = "ordinal"
            key.pop("axis")
            key.pop("timeUnit")
    elif t in ("stacked", "grouped", "percent"):
        spec["mark"] = {"type": "bar", "cornerRadiusEnd": 2}
        xe = _enc(result, x)
        if xe["type"] == "temporal":
            xe.update({"type": "ordinal"}), xe.pop("axis"), xe.pop("timeUnit")
        ye = _enc(result, m, stack="normalize" if t == "percent" else (None if t == "grouped" else "zero"))
        if t == "percent":
            ye["axis"] = {"format": "%"}
            ye["title"] = "Share"
        spec["encoding"] = {"x": xe, "y": ye, "color": _enc(result, color), "tooltip": tip}
        if t == "grouped":
            spec["encoding"]["xOffset"] = {"field": color}
    elif t == "heatmap":
        a, b = (x, color) if color else dims[:2]
        ae = _enc(result, a, "ordinal")
        be = _enc(result, b, "ordinal")
        spec["mark"] = {"type": "rect", "cornerRadius": 3}
        spec["encoding"] = {"x": ae, "y": be, "color": _enc(result, m), "tooltip": tip}
        spec["height"] = max(160, 28 * len({r[b] for r in result["rows"]}))
    elif t == "donut":
        spec["mark"] = {"type": "arc", "innerRadius": 70, "padAngle": 0.01}
        spec["encoding"] = {"theta": _enc(result, m, stack=True), "color": _enc(result, dims[0], sort={"field": m, "order": "descending"}),
                            "tooltip": tip}
        spec["view"] = {"stroke": None}
    elif t in ("scatter", "bubble"):
        m2 = intent.get("x") if intent.get("x") in meas else meas[0]
        m1 = next(mm for mm in meas if mm != m2) if len(meas) > 1 else meas[0]
        spec["mark"] = {"type": "circle", "opacity": 0.75}
        spec["encoding"] = {"x": _enc(result, m2), "y": _enc(result, m1), "tooltip": tip}
        if t == "bubble":
            spec["encoding"]["size"] = _enc(result, intent.get("size") or (meas[2] if len(meas) > 2 else m2))
        if len(dims) > 1:
            spec["encoding"]["color"] = _enc(result, dims[1])
    elif t == "histogram":
        spec["mark"] = {"type": "bar", "cornerRadiusEnd": 2}
        spec["encoding"] = {"x": _enc(result, m, bin={"maxbins": 12}), "y": {"aggregate": "count", "title": f"Number of {SCHEMA['dimensions'][dims[0]]['label'].lower()}s"}}
    elif t == "boxplot":
        cat = next((d for d in dims if d != time), dims[0])
        spec["mark"] = {"type": "boxplot", "extent": "min-max"}
        spec["encoding"] = {"x": _enc(result, cat, "nominal"), "y": _enc(result, m)}
    elif t == "waterfall":
        key = dims[0]
        rows = result["rows"]
        data, prev = [], 0.0
        first = rows[0][m] or 0
        data.append({"step": label_of(key, rows[0][key]), "start": 0, "end": first, "delta": first, "kind": "start"})
        prev = first
        for r in rows[1:]:
            v = r[m] or 0
            data.append({"step": label_of(key, r[key]), "start": prev, "end": v, "delta": v - prev, "kind": "up" if v >= prev else "down"})
            prev = v
        spec["data"] = {"values": data}
        spec["mark"] = {"type": "bar", "cornerRadius": 2}
        spec["encoding"] = {"x": {"field": "step", "type": "ordinal", "sort": None, "title": SCHEMA["dimensions"][key]["label"]},
                            "y": {"field": "start", "type": "quantitative", "title": _enc(result, m)["title"]}, "y2": {"field": "end"},
                            "color": {"field": "kind", "type": "nominal", "title": None, "legend": None},
                            "tooltip": [{"field": "step", "type": "ordinal"}, {"field": "delta", "type": "quantitative", "format": ",.0f", "title": "Change"}]}
    elif t == "kpi":
        row = result["rows"][0]
        c = _field(result, m)
        spec["data"] = {"values": [{"value": row[m], "label": c["label"], "unit": c.get("unit")}]}
        spec["mark"] = {"type": "text", "fontSize": 44, "fontWeight": 700}
        spec["encoding"] = {"text": {"field": "value", "type": "quantitative", "format": ",.0f"}}
        spec["height"] = 80
    return spec
