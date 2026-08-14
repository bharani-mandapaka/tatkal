"""TEMP dry-run launcher: same as run_auto.py but overrides journey_date in
memory (the saved config's date is in the past). Delete after use."""
import asyncio, builtins, sys, os
from datetime import datetime

_original_input = builtins.input
def _auto_input(prompt=""):
    p = (prompt or "").lower()
    if any(t in p for t in ("captcha", "solve", "solving")):
        print(f"\n  [USER ACTION REQUIRED] {prompt}")
        return _original_input("")
    print(f"  [auto-input] '{prompt}' -> <Enter>")
    return ""
builtins.input = _auto_input

sys.path.insert(0, ".")
from logger import setup_logging, get_logger
from config import load_config
from adapters.browser import PlaywrightBrowser
from adapters.captcha_file import FileCaptchaAdapter
from adapters.notifier import Notifier
from core.booking_flow import BookingFlow
from scheduler import now_ist
from main import _build_config

PASSPHRASE = os.environ.get("TATKAL_DEV_PASSPHRASE", "")
OVERRIDE_DATE = os.environ.get("DRY_DATE", "")  # DD-MM-YYYY


async def main():
    setup_logging(); log = get_logger()
    raw = load_config(PASSPHRASE)
    if OVERRIDE_DATE:
        raw["journey_date"] = OVERRIDE_DATE
    config = _build_config(raw)
    print(f"\n[dry-test] {config.train_number} {config.from_station}->{config.to_station} "
          f"date={config.journey_date} quota={config.quota} class={config.travel_class.value}\n")
    notifier = Notifier()
    captcha = FileCaptchaAdapter(notifier, timeout_s=60)
    browser = PlaywrightBrowser()
    flow = BookingFlow(browser, captcha, None, notifier, dry_run=True)
    await browser.launch()
    try:
        result = await flow.run(config, now_ist())
        print("\n[dry-test] RESULT:", result)
    except Exception as e:
        print("\n[dry-test] STOPPED AT:", repr(e))
    finally:
        await asyncio.sleep(1)
        await browser.close()
        print("[dry-test] Browser closed.")


if __name__ == "__main__":
    asyncio.run(main())
