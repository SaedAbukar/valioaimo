"""Build the chat-first app into one self-contained file.

    python ui/build.py

ui/dist/index.html     full HTML document, served by the gateway at /
ui/dist/artifact.html  same page without the document skeleton (for publishing as a Claude artifact)
Both inline styles.css, app.js and the recorded gateway runs (ui/src/replays.json),
so the page also works with no server.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "src"
DIST = ROOT / "ui" / "dist"


def main():
    body = (SRC / "index.html").read_text()
    replays = (SRC / "replays.json").read_text() if (SRC / "replays.json").exists() else "null"
    body = body.replace("/*__CSS__*/", (SRC / "styles.css").read_text())
    body = body.replace("/*__REPLAYS__*/null", replays.replace("</", "<\\/"))
    js = "\n".join((SRC / f).read_text() for f in ("orders.js", "insights.js", "kitchens.js", "app.js"))
    body = body.replace("/*__JS__*/", js.replace("</script", "<\\/script"))
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "artifact.html").write_text(body)
    full = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}[hidden]{display:none!important}</style>\n'
            + body.replace("<div id=\"app\"", "</head>\n<body>\n<div id=\"app\"", 1) + "\n</body>\n</html>\n")
    (DIST / "index.html").write_text(full)
    print(f"built {DIST / 'index.html'} ({len(full) / 1024:.0f} KiB) and artifact.html")


if __name__ == "__main__":
    main()
