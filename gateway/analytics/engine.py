"""State machine for the insight playbook (insight_playbook.v1.yaml).

Same contract as the order playbook: StepNotAllowed (409) with next_allowed_tools,
GuardFailed (422) with a `fix`, an audit event per call with the playbook version.
"""
from __future__ import annotations

import copy
import time
from functools import lru_cache
from pathlib import Path

import yaml

from ..playbook.engine import GuardFailed, NotFound, StepNotAllowed, validate_input
from ..util import iso, new_id
from . import charts, explain, query, store

FILE = Path(__file__).resolve().parent / "insight_playbook.v1.yaml"


@lru_cache(maxsize=1)
def insight_playbook() -> dict:
    pb = yaml.safe_load(FILE.read_text())
    pb["toolStep"] = {t: s["id"] for s in pb["steps"] for t in s["tools"]}
    return pb


def public() -> dict:
    pb = copy.deepcopy(insight_playbook())
    pb.pop("toolStep")
    return pb


class InsightEngine:
    def __init__(self, gw):
        self.gw = gw
        self.sessions: dict[str, dict] = {}

    @property
    def conn(self):
        return store.conn_for(self.gw)

    def allowed(self, s: dict | None) -> list[str]:
        if s is None:
            return ["start_analysis"]
        step = s["step"]
        if step == "start":
            return ["describe_data"]
        out = ["describe_data", "get_values", "run_query", "explain_change"]
        if s.get("result") is not None:
            out += ["suggest_chart", "build_chart", "explain_result"]
        return out

    def call(self, sid: str | None, tool: str, args: dict | None = None) -> dict:
        args = args or {}
        pb = insight_playbook()
        s = self.sessions.get(sid) if sid else None
        if sid and not s:
            raise NotFound(f"no analysis session {sid}")
        if tool not in pb["toolStep"]:
            raise NotFound(f"unknown tool {tool}", known=sorted(pb["toolStep"]), next_allowed_tools=self.allowed(s),
                           fix={"tools": "GET /v1/insights/playbook lists every tool and its input"})
        allowed = self.allowed(s)
        if tool not in allowed:
            raise StepNotAllowed(f"'{tool}' is not allowed yet.", step=s["step"] if s else None,
                                 next_allowed_tools=allowed, insightPlaybookVersion=pb["version"])
        validate_input(pb["inputs"].get(tool), tool, args)
        t0 = time.perf_counter()
        out = getattr(self, "_" + tool)(s, args)
        if tool == "start_analysis":
            s = self.sessions[out["sessionId"]]
        s["step"] = pb["toolStep"][tool]
        s["calls"] += 1
        ms = round((time.perf_counter() - t0) * 1000, 1)
        self.gw.audit.append(trace_id=s["sessionId"], actor=f"agent:{s['agent']}", action=f"insight.{tool}", buyer_id=s["buyerId"],
                             inputs={k: v for k, v in args.items() if k != "buyerId"},
                             refs={"step": s["step"], "insightPlaybookVersion": pb["version"], "ms": ms},
                             reason=out.get("caption", "") if isinstance(out, dict) else "")
        return {"tool": tool, "step": s["step"], "output": out, "next_allowed_tools": self.allowed(s), "sessionId": s["sessionId"]}

    # ---------------------------------------------------------------- tools
    def _start_analysis(self, s, a):
        bid = a.get("buyerId")
        buyer = self.gw.buyers.get(bid)
        if not buyer:
            raise GuardFailed(f"Unknown buyer {bid}.", fix=f"Use one of: {', '.join(self.gw.buyers)}.")
        site = a.get("siteId")
        if site and site not in {x["id"] for x in buyer["sites"]}:
            raise GuardFailed(f"Kitchen {site} does not belong to {bid}.", fix=f"Use one of: {', '.join(x['id'] for x in buyer['sites'])}.")
        sid = new_id("ANA")
        self.sessions[sid] = {"sessionId": sid, "buyerId": bid, "siteId": site, "step": "start", "calls": 0, "result": None,
                              "agent": a.get("agent", "analyst"), "createdAt": iso(self.gw.clock.now())}
        return {"sessionId": sid, "buyerId": bid, "siteId": site, "insightPlaybookVersion": insight_playbook()["version"]}

    def _site_name(self, s):
        if not s["siteId"]:
            return None
        return next(x["name"] for x in self.gw.buyers[s["buyerId"]]["sites"] if x["id"] == s["siteId"])

    def _conn_for(self, name: str | None):
        if name in (None, "orders"):
            return self.conn
        from . import datasets
        return datasets.connect(self.gw)

    def _describe_data(self, s, a):
        ds = query.dataset(a.get("dataset"))
        sch = ds["schema"]
        b = self.gw.buyers[s["buyerId"]]
        from .datasets import DATASETS
        return {"dataset": ds["name"], "datasets": ["orders", *DATASETS],
                "datasetNote": "orders = a year of order history; agent_activity = one row per agent session; "
                               "demand = planned and ordered lines plus needs that could not be met (and why).",
                "measures": {k: {"label": v["label"], "unit": v["unit"]} for k, v in sch["measures"].items()},
                "dimensions": {k: {"label": v["label"], "type": v["type"]} for k, v in sch["dimensions"].items()},
                "timeGrains": list(query.GRAINS), "period": {"from": ds["period"][0].isoformat(), "to": ds["period"][1].isoformat()},
                "relativePeriods": query.RELATIVE,
                "operators": list(query.OPS), "calcs": query.CALCS, "chartTypes": charts.TYPES,
                "sites": [x["name"] for x in b["sites"]], "scopedToSite": self._site_name(s),
                "recipes": insight_playbook()["recipes"]}

    def _get_values(self, s, a):
        f = a.get("field")
        dims = store.SCHEMA["dimensions"]
        if f not in dims:
            raise GuardFailed(f"Unknown dimension '{f}'.", fix=f"Use one of: {', '.join(dims)}.")
        col = dims[f]["sql"] if f != "date" else "substr(date,1,7)"
        sql, args = f"SELECT DISTINCT {col} FROM line WHERE buyer_id = ? AND {col} IS NOT NULL", [s["buyerId"]]
        if a.get("search"):
            sql += f" AND LOWER({col}) LIKE ?"
            args.append(f"%{str(a['search']).lower()}%")
        vals = [r[0] for r in self.conn.execute(sql + f" ORDER BY 1 LIMIT {int(a.get('limit', 50))}", args)]
        return {"field": f, "values": vals}

    def _run_query(self, s, a):
        spec = dict(a)
        if s["siteId"]:
            spec["filters"] = list(spec.get("filters") or []) + [{"field": "site", "op": "eq", "value": self._site_name(s)}]
        res = query.run(self._conn_for(spec.get("dataset")), spec, s["buyerId"])
        s["result"] = res
        preview = res["rows"][:20]
        return {"columns": res["columns"], "rows": preview, "rowCount": len(res["rows"]), "shape": res["shape"],
                "period": res["period"], "truncated": len(res["rows"]) > 20}

    def _suggest_chart(self, s, a):
        return {"suggestions": charts.suggest(s["result"])}

    def _build_chart(self, s, a):
        spec = charts.build(s["result"], a)
        s["chart"] = spec
        return {"chart": spec}

    def _explain_change(self, s, a):
        """Which values of `by` drove the change of `measure` from period_a to period_b (top 5 + Other)."""
        ds = query.dataset(a.get("dataset"))
        meas = ds["schema"]["measures"]
        m, by = a["measure"], a["by"]
        if m not in meas:
            raise GuardFailed(f"Unknown measure '{m}'.", fix=f"Use one of: {', '.join(meas)}.")
        sql = meas[m]["sql"].upper()
        if not sql.startswith(("SUM(", "COUNT(")) or "/" in sql:
            raise GuardFailed(f"'{m}' is a rate, so its change does not split into parts.",
                              fix="Use a total such as spend, waste, co2e, quantity or orders.")
        conn = self._conn_for(ds["name"])
        base = {"dataset": ds["name"], "measures": [m], "dimensions": [by]}
        if s["siteId"]:
            base["filters"] = [{"field": "site", "op": "eq", "value": self._site_name(s)}]
        ra = query.run(conn, {**base, "period": a["period_a"]}, s["buyerId"])
        rb = query.run(conn, {**base, "period": a["period_b"]}, s["buyerId"])
        va = {r[by]: r[m] or 0 for r in ra["rows"]}
        vb = {r[by]: r[m] or 0 for r in rb["rows"]}
        parts = [{"value": k, "a": va.get(k, 0), "b": vb.get(k, 0), "contribution": round(vb.get(k, 0) - va.get(k, 0), 2)}
                 for k in set(va) | set(vb)]
        parts.sort(key=lambda p: -abs(p["contribution"]))
        total_a, total_b = sum(va.values()), sum(vb.values())
        change = round(total_b - total_a, 2)
        top, rest = parts[:5], parts[5:]
        if rest:
            top.append({"value": "Other", "a": sum(p["a"] for p in rest), "b": sum(p["b"] for p in rest),
                        "contribution": round(sum(p["contribution"] for p in rest), 2)})
        unit, label = meas[m]["unit"], meas[m]["label"].lower()
        word = "rise" if change >= 0 else "fall"

        def signed(v):
            s_ = explain.fmt(abs(v), unit)
            if unit == "EUR" and abs(v) >= 1000:
                s_ = f"€{abs(v) / 1000:.1f}k"
            return ("+" if v >= 0 else "−") + s_
        for p in top:
            p["sharePct"] = round(p["contribution"] / change * 100, 1) if change else None
        sentences = [f"{p['value']} drove {signed(p['contribution'])} of the {signed(change)} {word} in {label}." for p in top[:3]]
        return {"measure": m, "by": by, "dataset": ds["name"], "periodA": ra["period"], "periodB": rb["period"],
                "totalA": round(total_a, 2), "totalB": round(total_b, 2), "change": change, "contributions": top,
                "sentences": sentences, "caption": sentences[0] if sentences else "No change to explain."}

    def _explain_result(self, s, a):
        return explain.run(s["result"])
