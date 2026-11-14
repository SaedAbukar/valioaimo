"""The analyst: turns a typed question (+ page filters) into a chart, through the insight rails.

Two engines, same tools, same order:
  * "claude": Claude Haiku 5.5 drives the insight playbook tools in a manual tool loop
    (when ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN is set). Any error falls back to rules.
  * "rules": a deterministic EN/FI phrase interpreter that builds the query spec itself.
Both return the same answer shape, including the tool steps taken ("How I made this").
"""
from __future__ import annotations

import json
import os
import re

from ..playbook.engine import PlaybookError
from .engine import insight_playbook
from .store import SCHEMA

MODEL = "claude-haiku-5-5"

MEASURE_WORDS = [
    (r"\bco2|carbon|climate|hiili|päästö", "co2e"),
    (r"waste|left ?over|thrown|hävik|jäi yli|ylijä", "waste"),
    (r"on[- ]time|late|delay|myöhä|ajallaan|toimitusvarmuus", "on_time_pct"),
    (r"just right|right[- ]sized|sopiva", "right_sized_pct"),
    (r"\borders?\b|tilauks|tilaukset", "orders"),
    (r"\bevents?\b|tapahtum|juhl", "events"),
    (r"\bguests?\b|vieraat|vierait", "guests"),
    (r"weight|\bkg\b|kilo|paino", "kg"),
    (r"price|hinta|hinnat", "avg_price"),
    (r"quantity|volume|määrä", "quantity"),
    (r"spend|spent|cost|money|euro|€|kulu|kulut|kulutus|ostot|budget", "spend"),
]
DIM_WORDS = [
    (r"by week|weekly|per week|viikoittain|viikko", ("date", "week")),
    (r"by quarter|quarterly|neljännes", ("date", "quarter")),
    (r"by day|daily|per day|päivittäin", ("date", "day")),
    (r"month|monthly|over time|trend|kuukau|kuukausittain|vuoden aikana", ("date", "month")),
    (r"weekday|day of (the )?week|viikonpäiv", ("weekday", None)),
    (r"categor|kategori|tuoteryhm", ("category", None)),
    (r"product|item|tuotte|tuote", ("product", None)),
    (r"kitchen|site|location|hotel|keittiö|toimipai", ("site", None)),
    (r"brand|supplier|merkki|toimittaj", ("brand", None)),
    (r"event type|kind of event|tapahtumatyyp", ("event_type", None)),
    (r"\bevents?\b|tapahtumittain|juhlittain", ("event", None)),
    (r"storage|chilled|frozen|säilytys", ("temperature", None)),
    (r"outcome|how it went|labels?", ("outcome", None)),
]
CHART_WORDS = [(r"heat ?map|lämpökartta", "heatmap"), (r"\bpie\b|donut|piirakka", "donut"), (r"scatter|hajonta", "scatter"),
               (r"bubble", "bubble"), (r"\btable\b|taulukko", "table"), (r"\barea\b", "area"), (r"stacked|pinottu", "stacked"),
               (r"grouped|side by side", "grouped"), (r"\bmix\b|100 ?%|percent(age)? split", "percent"),
               (r"waterfall|vesiputous", "waterfall"), (r"histogram|distribution|jakauma", "histogram"),
               (r"box ?plot|spread", "boxplot"), (r"\bbars?\b|pylväs", "bar"), (r"\bline\b|viiva", "line"),
               (r"\bkpi\b|one number|total|yhteensä", "kpi")]


def _period(text: str) -> str | None:
    t = text.lower()
    if re.search(r"last 3 months|past 3 months|last quarter|3 kk|viimeiset 3|kolme kuukautta", t):
        return "last_3_months"
    if re.search(r"last 6 months|past 6 months|half ?year|puoli vuotta|6 kk", t):
        return "last_6_months"
    if re.search(r"last 30 days|past month|30 päivää", t):
        return "last_30_days"
    if re.search(r"this month|last month|tässä kuussa|viime kuussa", t):
        return "last_month"
    return None


ASK_FILTERS = {  # page filters for ask / ask_insight: always applied, and they win over guesses
    "type": "object", "additionalProperties": False,
    "properties": {
        "site": {"type": "string", "description": "kitchen name, e.g. Pohjola Tampere"},
        "siteId": {"type": ["string", "null"], "description": "kitchen id"},
        "category": {"type": "string", "description": "product category, e.g. dairy"},
        "event_type": {"type": "string", "description": "event type, e.g. gala_dinner"},
        "period": {"description": "{from, to} or last_month | last_3_months | last_6_months | last_30_days | this_year",
                   "anyOf": [{"type": "string"}, {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}}}]}},
    "examples": [{"site": "Pohjola Tampere", "period": "last_3_months"}]}


class Analyst:
    def __init__(self, gw):
        self.gw = gw
        self.E = gw.insights
        self.client = None
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            try:
                import anthropic
                self.client = anthropic.Anthropic(max_retries=1, timeout=40.0)
            except Exception:  # noqa: BLE001 - rules still work
                self.client = None

    # ------------------------------------------------------------------ public
    def ask(self, prompt: str, filters: dict | None, buyer_id: str, site_id: str | None = None) -> dict:
        filters = filters or {}
        if self.client:
            try:
                return self._ask_claude(prompt, filters, buyer_id, site_id)
            except Exception as e:  # noqa: BLE001 - never leave the chef without an answer
                ans = self._ask_rules(prompt, filters, buyer_id, site_id)
                ans["note"] = f"Answered with built-in rules ({type(e).__name__})."
                return ans
        return self._ask_rules(prompt, filters, buyer_id, site_id)

    # ------------------------------------------------------------------ rules engine
    def interpret(self, prompt: str, filters: dict, buyer_id: str) -> tuple[dict, str | None, list[str]]:
        t = " " + prompt.lower() + " "
        assumed = []
        measures = []
        for pat, m in MEASURE_WORDS:
            if re.search(pat, t) and m not in measures:
                measures.append(m)
        if "waste" in measures and re.search(r"%|percent|share|rate|osuus|prosent", t):
            measures[measures.index("waste")] = "waste_pct"
        if not measures:
            measures = ["spend"]
            assumed.append("I showed spend because the question did not name a measure.")
        dims = []
        for pat, (f, g) in DIM_WORDS:
            if re.search(pat, t) and f not in [d if isinstance(d, str) else d["field"] for d in dims]:
                dims.append({"field": f, "grain": g} if g else f)
        top = re.search(r"\btop\s*(\d+)|(\d+)\s*(?:most|largest|biggest|eniten|suurinta)", t)
        if not dims and not re.search(r"\btotal|yhteensä|\bkpi\b", t):
            dims = [{"field": "date", "grain": "month"}]
            assumed.append("I split it by month because the question did not say how.")
        names = [d if isinstance(d, str) else d["field"] for d in dims]
        if "site" in names and len(names) > 1:  # "category per kitchen": kitchen first reads better
            dims = [d for d in dims if (d if isinstance(d, str) else d["field"]) == "site"] + \
                   [d for d in dims if (d if isinstance(d, str) else d["field"]) != "site"]
        spec: dict = {"measures": measures[:3], "dimensions": dims[:2], "filters": []}
        b = self.gw.buyers[buyer_id]
        for s in b["sites"]:
            words = [w for w in s["name"].lower().split() if len(w) > 4 and w not in ("kitchen", "pohjola", "school", "production", "central")]
            if any(re.search(r"\b" + re.escape(w[:6]), t) for w in words):
                spec["filters"].append({"field": "site", "op": "eq", "value": s["name"]})
        for cat, words in {"Dairy": "dairy|maito", "Fish": "fish|kala", "Meat": "meat|liha", "Fruit & veg": "veg|fruit|vihannes|hedelm",
                           "Bakery": "bakery|bread|leipä", "Dry goods": "dry goods|kuiva", "Plant-based": "plant|vegan|kasvi"}.items():
            if re.search(r"\b(" + words + r")", t) and "categor" not in t:
                spec["filters"].append({"field": "category", "op": "eq", "value": cat})
        for et in ("Gala", "Wedding", "Conference", "Christmas party", "Birthday", "Lunch"):
            if et.lower() in t and "event_type" not in names:
                spec["filters"].append({"field": "event_type", "op": "eq", "value": et})
        if top:
            n = int(top.group(1) or top.group(2))
            spec["limit"] = max(1, min(50, n))
            spec["sort"] = [{"by": measures[0], "dir": "desc"}]
            if re.search(r"rest|others|other|muut", t):
                spec["other"] = True
            if not any((d if isinstance(d, str) else d["field"]) == "product" for d in spec["dimensions"]) and not spec["dimensions"]:
                spec["dimensions"] = ["product"]
        if re.search(r"compared|versus|\bvs\.?\b|previous|before|edellis|verrattuna", t):
            spec["compare"] = "previous_period"
            spec["dimensions"] = [d for d in spec["dimensions"] if not isinstance(d, dict)] or ["site"]
        period = _period(t)
        if period:
            spec["period"] = period
        if re.search(r"\bshare|osuus|proportion|part of", t):
            spec["calc"] = [{"type": "share", "of": measures[0]}]
        if re.search(r"running|cumulative|kertymä", t):
            spec.setdefault("calc", []).append({"type": "running_total", "of": measures[0]})
        if re.search(r"moving average|rolling|liukuva", t):
            spec.setdefault("calc", []).append({"type": "moving_avg", "of": measures[0], "window": 3})
        one_series = len(spec.get("dimensions") or []) == 1 and isinstance(spec["dimensions"][0], dict)
        if one_series and re.search(r"forecast|predict|next \d* ?months?|coming months|ennuste|ennusta", t):
            spec.setdefault("calc", []).append({"type": "forecast", "of": measures[0], "horizon": 3})
        if one_series and re.search(r"unusual|anomal|spike|odd|outlier|poikkea", t):
            spec.setdefault("calc", []).append({"type": "anomaly", "of": measures[0]})
        # page filters always apply (and win over guesses for the same field)
        for field in ("site", "category", "event_type"):
            if filters.get(field):
                spec["filters"] = [f for f in spec["filters"] if f["field"] != field] + [{"field": field, "op": "eq", "value": filters[field]}]
        if filters.get("period"):
            spec["period"] = filters["period"]
        chart = next((c for pat, c in CHART_WORDS if re.search(pat, t)), None)
        if chart == "kpi" and spec["dimensions"]:
            chart = None
        return spec, chart, assumed

    def _ask_rules(self, prompt, filters, buyer_id, site_id):
        spec, chart_type, assumed = self.interpret(prompt, filters, buyer_id)
        steps = []

        def call(sid, tool, args=None):
            r = self.E.call(sid, tool, args or {})
            steps.append({"tool": tool, "args": args or {}, "next": r["next_allowed_tools"]})
            return r

        sid = call(None, "start_analysis", {"buyerId": buyer_id, "siteId": site_id, "agent": "rules"})["sessionId"]
        call(sid, "describe_data")
        try:
            call(sid, "run_query", spec)
        except PlaybookError as e:  # a guess the rails rejected: fall back to the safest question
            assumed.append(f"I could not ask that exactly ({e.message}), so I showed spend by month.")
            spec = {"measures": ["spend"], "dimensions": [{"field": "date", "grain": "month"}], "filters": spec.get("filters", [])}
            call(sid, "run_query", spec)
        sugg = call(sid, "suggest_chart")["output"]["suggestions"]
        types = [s["type"] for s in sugg]
        ctype = chart_type if chart_type and chart_type in _fits(self.E, sid) else types[0]
        if chart_type and ctype != chart_type:
            assumed.append(f"A {chart_type} does not fit this answer, so I used a {ctype}.")
        call(sid, "build_chart", {"type": ctype})
        ex = call(sid, "explain_result")["output"]
        return self._answer(sid, steps, ex, assumed, "rules", spec)

    # ------------------------------------------------------------------ claude engine
    def _ask_claude(self, prompt, filters, buyer_id, site_id):
        pb = insight_playbook()
        steps = []
        start = self.E.call(None, "start_analysis", {"buyerId": buyer_id, "siteId": site_id, "agent": "claude-haiku"})
        sid = start["sessionId"]
        steps.append({"tool": "start_analysis", "args": {"buyerId": buyer_id}, "next": start["next_allowed_tools"]})
        tools = [{"name": s_tool, "description": f"Step '{st['id']}': {st['does']}",
                  "input_schema": {"type": "object", "additionalProperties": True}}
                 for st in pb["steps"] for s_tool in st["tools"] if s_tool != "start_analysis"]
        system = ("You answer a chef's question about their kitchen data by calling the tools in order: "
                  "describe_data, optionally get_values, run_query (repeat if needed), suggest_chart, build_chart, explain_result. "
                  "Use only names returned by describe_data. If a tool returns an error with a 'fix', follow the fix and retry. "
                  "Apply these page filters in every run_query: " + json.dumps(filters) + ". "
                  "Worked examples:\n" + json.dumps(pb["recipes"]) +
                  "\nFinish after explain_result with one short sentence.")
        messages = [{"role": "user", "content": prompt}]
        for _ in range(10):
            resp = self.client.messages.create(model=MODEL, max_tokens=4000, system=system, tools=tools,
                                               output_config={"effort": "low"}, messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                break
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    r = self.E.call(sid, block.name, dict(block.input or {}))
                    steps.append({"tool": block.name, "args": block.input, "next": r["next_allowed_tools"]})
                    out = r["output"] if block.name != "build_chart" else {"built": True, "type": r["output"]["chart"].get("usermeta", {}).get("chartType")}
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str)[:12000]})
                except PlaybookError as e:
                    steps.append({"tool": block.name, "args": block.input, "error": e.body()})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(e.body()), "is_error": True})
            messages.append({"role": "user", "content": results})
        s = self.E.sessions[sid]
        if not s.get("chart"):
            raise RuntimeError("the model did not build a chart")
        ex = self.E.call(sid, "explain_result")["output"]
        return self._answer(sid, steps, ex, [], "claude", s["result"]["spec"])

    # ------------------------------------------------------------------ shape
    def _answer(self, sid, steps, ex, assumed, engine, spec):
        s = self.E.sessions[sid]
        res = s["result"]
        return {"sessionId": sid, "engine": engine, "spec": spec, "chart": s.get("chart"), "columns": res["columns"],
                "rows": res["rows"][:300], "period": res["period"], "caption": ex["caption"], "facts": ex["facts"],
                "assumed": assumed, "steps": steps}


def _fits(E, sid):
    from .charts import fits
    return fits(E.sessions[sid]["result"])
