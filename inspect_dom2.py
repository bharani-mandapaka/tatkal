"""Deep DOM inspection — finds the station / date / class / quota selectors."""
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright

IRCTC_HOME  = "https://www.irctc.co.in/nget/train-search"
COOKIE_PATH = Path("session.json")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        if COOKIE_PATH.exists():
            await ctx.add_cookies(json.loads(COOKIE_PATH.read_text("utf-8")))

        page = await ctx.new_page()
        await page.goto(IRCTC_HOME, wait_until="load")
        await asyncio.sleep(4)

        # ── 1. Dump full attributes of every visible input ─────────────────────
        details = await page.eval_on_selector_all("input", """els => els.map(e => {
            const attrs = {};
            for (const a of e.attributes) attrs[a.name] = a.value;
            const parent = e.parentElement;
            const grandparent = parent ? parent.parentElement : null;
            return {
                tag:        'input',
                attrs:      attrs,
                parentTag:  parent ? parent.tagName : null,
                parentAttrs: parent ? (() => { const o={}; for (const a of parent.attributes) o[a.name]=a.value; return o; })() : {},
                gpTag:      grandparent ? grandparent.tagName : null,
                gpAttrs:    grandparent ? (() => { const o={}; for (const a of grandparent.attributes) o[a.name]=a.value; return o; })() : {},
                visible:    e.offsetParent !== null,
                rect:       e.getBoundingClientRect().toJSON(),
            };
        })""")

        print("=" * 70)
        print("VISIBLE INPUTS:")
        print("=" * 70)
        for i, d in enumerate(details):
            if not d["visible"]:
                continue
            print(f"\n[{i}]")
            print(f"  attrs:       {json.dumps(d['attrs'], indent=4)}")
            print(f"  parent:      <{d['parentTag']}> {json.dumps(d['parentAttrs'])}")
            print(f"  grandparent: <{d['gpTag']}> {json.dumps(d['gpAttrs'])}")
            print(f"  rect:        {d['rect']}")

        # ── 2. Dump key Angular component attributes ──────────────────────────
        print("\n" + "=" * 70)
        print("p-autocomplete components:")
        pa = await page.eval_on_selector_all("p-autocomplete, app-en-tran-search p-autocomplete", """
            els => els.map(e => {
                const attrs = {};
                for (const a of e.attributes) attrs[a.name] = a.value;
                return { tag: e.tagName, attrs };
            })
        """)
        for x in pa:
            print(f"  <{x['tag']}> {json.dumps(x['attrs'])}")

        # ── 3. Dump p-dropdown components ─────────────────────────────────────
        print("\np-dropdown components:")
        pd = await page.eval_on_selector_all("p-dropdown", """
            els => els.map(e => {
                const attrs = {};
                for (const a of e.attributes) attrs[a.name] = a.value;
                return { tag: e.tagName, attrs };
            })
        """)
        for x in pd:
            print(f"  <{x['tag']}> {json.dumps(x['attrs'])}")

        await page.screenshot(path="irctc_form2.png")
        print("\nScreenshot -> irctc_form2.png")
        await browser.close()

asyncio.run(main())
