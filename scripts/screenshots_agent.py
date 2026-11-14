"""Agent mode screenshots (a real Claude agent ordering over the gateway's MCP): 1280 dark and 390 light.

    make run   # with ANTHROPIC_API_KEY in .env
    python scripts/screenshots_agent.py [base]   -> docs/screenshots/v2/v5-agent-*.png
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots" / "v2"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
MILK = "I need 1,000 litres of lactose-free milk by Monday."


def shoot(page, name):
    page.request.post(BASE + "/v1/demo/reset", data="{}", headers={"Content-Type": "application/json", "Authorization": "Bearer demo-ops"})
    page.goto(BASE + "/")
    page.evaluate("localStorage.setItem('aimo.agentMode', 'true'); localStorage.removeItem('aimo.conv')")
    page.goto(BASE + "/")
    page.wait_for_selector("[data-agent-toggle][aria-pressed=true]")
    page.locator('[data-go="new"]:visible').first.click()
    page.fill("#msg", MILK)
    page.press("#msg", "Enter")
    page.wait_for_selector('.agent-run .card[data-type="delivery"]', timeout=120000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / f"{name}.png"))


with sync_playwright() as p:
    b = p.chromium.launch()
    for name, (w, h), scheme, scale in (("v5-agent-1280-dark", (1280, 860), "dark", 1), ("v5-agent-390-light", (390, 844), "light", 2)):
        ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, color_scheme=scheme)
        shoot(ctx.new_page(), name)
        ctx.close()
        print("shot", name)
    b.close()
