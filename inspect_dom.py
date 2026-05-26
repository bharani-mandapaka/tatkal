"""
Opens IRCTC (reusing saved login session) and dumps the search-form
input elements + takes a screenshot so we can fix the selectors.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

IRCTC_HOME  = "https://www.irctc.co.in/nget/train-search"
COOKIE_PATH = Path("session.json")
SHOT_PATH   = "irctc_form.png"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        if COOKIE_PATH.exists():
            cookies = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
            await ctx.add_cookies(cookies)
            print(f"Loaded {len(cookies)} session cookies.")

        page = await ctx.new_page()
        await page.goto(IRCTC_HOME, wait_until="load")
        await asyncio.sleep(3)   # Let React hydrate

        # Dump all visible input elements on the page
        inputs = await page.eval_on_selector_all(
            "input",
            """els => els.map(e => ({
                tag:         e.tagName,
                id:          e.id,
                name:        e.name,
                placeholder: e.placeholder,
                type:        e.type,
                class:       e.className.slice(0, 80),
                formcontrol: e.getAttribute('formcontrolname'),
                ngmodel:     e.getAttribute('ng-model'),
                role:        e.getAttribute('role'),
                visible:     e.offsetParent !== null,
            }))"""
        )

        print(f"\nFound {len(inputs)} input elements:\n")
        for i, el in enumerate(inputs):
            if el["visible"]:
                print(f"  [{i}] placeholder={el['placeholder']!r:30}  id={el['id']!r:25}  "
                      f"type={el['type']!r:10}  formcontrol={el['formcontrol']!r}")

        await page.screenshot(path=SHOT_PATH, full_page=False)
        print(f"\nScreenshot saved -> {SHOT_PATH}")

        print("\nPress Enter to close browser...")
        input()
        await browser.close()


asyncio.run(main())
