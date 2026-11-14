"""Runs the JS event-brief parser tests (EN + FI) under Node, if Node is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_event_brief_parser_en_fi():
    if not (ROOT / "ui" / "src" / "data.js").exists():
        subprocess.run(["python3", str(ROOT / "ui" / "build.py")], check=True)
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "parser.test.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "parser tests passed" in r.stdout
