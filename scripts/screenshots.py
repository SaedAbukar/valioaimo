"""Screenshots of the six golden scenarios + main views, 390 px and 1280 px, light and dark.

    make run            # in another terminal (gateway on :8000)
    python scripts/screenshots.py   -> docs/screenshots/v2/*.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots" / "v2"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SIZES = {"390": (390, 844), "1280": (1280, 860)}


def wait_idle(page):
    page.wait_for_timeout(250)
    page.wait_for_selector(".typing", state="detached", timeout=15000)
    page.wait_for_timeout(250)


def open_app(page, buyer="BUY-POHJOLA", reset=True):
    if reset:
        page.request.post(BASE + "/v1/demo/reset", data="{}", headers={"Content-Type": "application/json"})
    page.goto(BASE + "/")
    page.evaluate(f"localStorage.setItem('aimo.buyer', {json.dumps(json.dumps(buyer))}); localStorage.removeItem('aimo.conv')")
    page.goto(BASE + "/")
    page.wait_for_selector("#app .main")
    wait_idle(page)


def new_chat(page):
    page.locator('[data-go="new"]:visible').first.click()


def say(page, text):
    page.fill("#msg", text)
    page.press("#msg", "Enter")
    wait_idle(page)


def tap(page, card_type, label):
    page.locator(f'.card[data-type="{card_type}"] button:has-text("{label}")').last.click()
    wait_idle(page)


def shot(page, name, scroll_to=None):
    if scroll_to:
        page.locator(scroll_to).last.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / f"{name}.png"))


def scenarios(page, tag):
    # s1 milk
    open_app(page); new_chat(page); say(page, "I need 1,000 L lactose-free milk by Monday")
    shot(page, f"s1-milk-{tag}", '.card[data-type="basket"]')
    # s2 gala (seeded: understood -> favourites -> basket -> ordered)
    open_app(page)
    shot(page, f"s2-gala-{tag}", '.card[data-type="delivery"]')
    page.locator('.card[data-type="understood"]').first.scroll_into_view_if_needed()
    shot(page, f"s2-gala-top-{tag}")
    # s5 guest change -> needs OK, then board + panel
    say(page, "now 200 guests")
    shot(page, f"s5-change-{tag}", '.card[data-type="needs_ok"]')
    tap(page, "needs_ok", "OK")
    page.locator('[data-go="orders"]:visible').first.click(); page.wait_for_timeout(400)
    shot(page, f"orders-{tag}")
    page.locator(".ticket:visible").first.click(); page.wait_for_timeout(400)
    shot(page, f"order-panel-{tag}")
    page.locator('.panel [data-approve]').click(); wait_idle(page)
    shot(page, f"s5-approved-{tag}", '.card[data-type="delivery"]')
    # s6 after the event -> how did it go -> tip on the next gala
    page.locator('[data-go="orders"]:visible').first.click(); page.wait_for_timeout(300)
    page.locator(".ticket:visible").first.click(); page.wait_for_timeout(300)
    page.locator('.panel [data-delivered]').click(); wait_idle(page)
    shot(page, f"s6-how-did-it-go-{tag}", '.card[data-type="how_did_it_go"]')
    page.locator('.card[data-type="how_did_it_go"] [data-need="whipping cream"][data-val="some"]').last.click()
    tap(page, "how_did_it_go", "Save")
    new_chat(page); say(page, "Gala dinner for 150 on 12.12.: salmon starter, beef tenderloin, chocolate mousse.")
    shot(page, f"s6-tip-{tag}", '.card[data-type="tip"]')
    page.locator('[data-go="insights"]:visible').first.click(); page.wait_for_timeout(600)
    shot(page, f"insights-{tag}")
    page.locator('[data-go="settings"]:visible').first.click(); page.wait_for_timeout(600)
    shot(page, f"settings-{tag}")
    # s3 new kitchen -> product choice -> basket
    open_app(page, "BUY-UUSI"); say(page, "100 L milk by Wednesday")
    shot(page, f"s3-choice-{tag}", '.card[data-type="choice"]')
    page.locator('.card[data-type="choice"] .opt').first.click(); wait_idle(page)
    shot(page, f"s3-basket-{tag}", '.card[data-type="basket"]')
    # s4 allergen conflict
    open_app(page, "BUY-KOULU"); say(page, "60 L oat drink by Monday")
    shot(page, f"s4-cant-do-{tag}", '.card[data-type="cant_do"]')
    # empty chat / first screen
    new_chat(page); page.wait_for_timeout(200)
    shot(page, f"new-chat-{tag}")
    v3_views(page, tag)


def go(page, view):
    page.locator(f'[data-go="{view}"]:visible').first.click()
    page.wait_for_timeout(1500)


def v3_views(page, tag):
    """Jira-style orders, Your year, Explore, Kitchens."""
    open_app(page)
    go(page, "orders")
    page.locator('[data-omode="board"]').click(); page.wait_for_timeout(400)
    shot(page, f"v3-orders-board-{tag}")
    page.locator('[data-omode="list"]').click(); page.wait_for_timeout(300)
    page.select_option("#o-group", "event"); page.wait_for_timeout(400)
    shot(page, f"v3-orders-list-{tag}")
    page.locator('[data-open][data-live="0"]:visible').first.click(); page.wait_for_timeout(800)
    shot(page, f"v3-order-history-panel-{tag}")
    page.keyboard.press("Escape")
    go(page, "insights"); page.wait_for_timeout(800)
    shot(page, f"v3-year-intro-{tag}")
    for _ in range(2):
        page.locator('[data-ycard="1"]').last.click(); page.wait_for_timeout(900)
    shot(page, f"v3-year-personality-{tag}")
    page.locator('[data-itab="explore"]').click(); page.wait_for_timeout(2000)
    page.locator('[data-ask="Category mix per kitchen"]').click(); page.wait_for_timeout(2000)
    shot(page, f"v3-explore-{tag}")
    go(page, "settings")
    shot(page, f"v3-kitchens-{tag}")
    page.locator(".site").first.click(); page.wait_for_timeout(500)
    shot(page, f"v3-kitchen-panel-{tag}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for size, (w, h) in SIZES.items():
            for scheme in ("light", "dark"):
                ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if w < 500 else 1, color_scheme=scheme)
                page = ctx.new_page()
                scenarios(page, f"{size}-{scheme}")
                ctx.close()
                print("done", size, scheme)
        b.close()
    print(f"{len(list(OUT.glob('*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    main()
