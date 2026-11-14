"""Build the self-contained demo page: ui/dist/index.html (one file, inline CSS/JS/data).

    python ui/build.py
"""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "src"
DATA = ROOT / "gateway" / "data"


def parse_schema(sql: str) -> dict:
    """Read the labelled DDL (docs/data-model/schema.sql) into a browsable structure."""
    tables, views = [], []
    for m in re.finditer(r"((?:--[^\n]*\n)*)CREATE (TABLE|VIEW) (\w+)\s*(?:\((.*?)\n\);|AS(.*?);)", sql, re.S):
        head, kind, name, body, vbody = m.groups()
        labels = {}
        for k in ("domain", "feeds", "grain", "pii"):
            mm = re.search(r"@" + k + r"\s+(.+?)(?=\s@|\n|$)", head)
            if mm:
                labels[k] = mm.group(1).strip()
        if "domain" in labels:
            labels["domain"] = re.match(r"\w+", labels["domain"]).group(0)
        desc = " ".join(l.strip("- ").strip() for l in head.splitlines() if l.strip().startswith("--") and "@" not in l and "====" not in l).strip()
        cols = []
        if body:
            for line in body.splitlines():
                line = line.strip()
                cm = re.match(r"(\w+)\s+(TEXT|INTEGER|NUMERIC|REAL|BLOB)([^-]*?)(?:,)?\s*(?:--\s*(.*))?$", line)
                if cm and cm.group(1).upper() not in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK"):
                    rest = cm.group(3)
                    ref = re.search(r"REFERENCES (\w+)", rest)
                    cols.append({"name": cm.group(1), "type": cm.group(2), "pk": "PRIMARY KEY" in rest,
                                 "ref": ref.group(1) if ref else None, "note": (cm.group(4) or "").strip()})
        entry = {"name": name, "kind": kind.lower(), "labels": labels, "desc": desc[-220:], "columns": cols}
        (views if kind == "VIEW" else tables).append(entry)
    # tables without explicit @domain inherit the section domain from the nearest heading
    current = None
    order = {t["name"]: t for t in tables}
    for line in sql.splitlines():
        mm = re.search(r"\(@domain (\w+)\)", line)
        if mm:
            current = mm.group(1)
        mt = re.match(r"CREATE TABLE (\w+)", line)
        if mt and mt.group(1) in order and "domain" not in order[mt.group(1)]["labels"] and current:
            order[mt.group(1)]["labels"]["domain"] = current
    for v in views:
        v["labels"].setdefault("domain", "DER")
    return {"tables": tables, "views": views}


def build_icons(sources: str) -> dict:
    """Inline Material Design icons (Apache-2.0, via react-icons' md set) as SVG paths: works offline."""
    md = Path("/opt/npm-tools/node_modules/react-icons/md/index.js")
    cache = ROOT / "ui" / "src" / "icons.json"
    names = set(re.findall(r"'([a-z][a-z0-9_]+)'", sources)) | set(re.findall(r"ic\(\s*'([a-z0-9_]+)'", sources))
    if not md.exists():
        return json.loads(cache.read_text()) if cache.exists() else {}
    src = md.read_text()
    defs = dict(re.findall(r"module\.exports\.(Md\w+) = function \w+ \(props\) \{\n  return GenIcon\((\{.*?\})\)\(props\);", src))
    def inner(tree):
        out = []
        for ch in tree.get("child", []):
            a = ch["attr"]
            if a.get("fill") == "none":
                continue
            attrs = " ".join(f'{k}="{v}"' for k, v in a.items() if k in ("d", "cx", "cy", "r", "x", "y", "width", "height", "points", "opacity", "transform", "rx"))
            out.append(f"<{ch['tag']} {attrs}/>" if not ch.get("child") else f"<{ch['tag']} {attrs}>{inner(ch)}</{ch['tag']}>")
        return "".join(out)
    icons = {}
    for n in sorted(names):
        pas = "".join(w.capitalize() for w in n.split("_"))
        fill, outl = defs.get("Md" + pas), defs.get("MdOutline" + pas) or defs.get("Md" + pas)
        if fill:
            icons[n] = [inner(json.loads(outl)), inner(json.loads(fill))]
    cache.write_text(json.dumps(icons, separators=(",", ":")))
    return icons


def parse_seed(sql: str) -> dict:
    """label_definition + metric_definition rows from docs/data-model/catalog_seed.sql."""
    out = {}
    for table in ("label_definition", "metric_definition"):
        m = re.search(r"INSERT INTO " + table + r" \((.*?)\) VALUES(.*?);", sql, re.S)
        if not m:
            continue
        cols = [c.strip() for c in m.group(1).split(",")]
        rows = []
        for tup in re.findall(r"\(\s*('.*?')\s*\)\s*[,;]?\n", m.group(2) + "\n"):
            vals = [v.replace("''", "'") for v in re.findall(r"'((?:[^']|'')*)'", tup)]
            rows.append(dict(zip(cols, vals)))
        out[table] = rows
    return out


def main():
    data = {
        "catalog": json.loads((DATA / "catalog.json").read_text()),
        "buyers": json.loads((DATA / "buyers.json").read_text()),
        "rules": yaml.safe_load((ROOT / "gateway" / "rules.yaml").read_text()),
        "recipes": json.loads((DATA / "recipes.json").read_text()),
        "schema": parse_schema((ROOT / "docs" / "data-model" / "schema.sql").read_text()),
        "seed": parse_seed((ROOT / "docs" / "data-model" / "catalog_seed.sql").read_text()),
        "layersSvg": (ROOT / "docs" / "data-model" / "data_layers.svg").read_text(),
    }
    srcs = "".join((SRC / n).read_text() for n in ("ui.js",))
    data["icons"] = build_icons(srcs)
    (SRC / "data.js").write_text("window.AIMO_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    html = (SRC / "index.html").read_text()
    def inline(name):
        return (SRC / name).read_text()
    html = html.replace("/*__CSS__*/", inline("styles.css"))
    js = "\n".join(inline(n) for n in ("data.js", "engine.js", "flows.js", "ui.js"))
    html = html.replace("/*__JS__*/", js.replace("</script", "<\\/script"))
    out = ROOT / "ui" / "dist" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"built {out} ({len(html) / 1024:.0f} KiB); schema: {len(data['schema']['tables'])} tables, {len(data['schema']['views'])} views")


if __name__ == "__main__":
    main()
