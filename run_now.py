"""
Non-interactive dry-run launcher.

Bypasses questionary prompts — loads config directly and fires immediately.
Browser opens in headed (visible) mode so you can watch every step.

Run:
    python run_now.py

Stop:
    Ctrl+C at any point — nothing is booked / charged until you approve payment.
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, ".")

from logger import setup_logging, get_logger
from config import load_config
from adapters.browser import PlaywrightBrowser
from adapters.captcha_manual import ManualCaptchaAdapter
from adapters.notifier import Notifier
from core.booking_flow import BookingFlow
from main import _build_config

# ── Config ────────────────────────────────────────────────────────────────────
PASSPHRASE = "17644MAS"
DRY_RUN    = True    # Set to False when you want to do a real booking


async def main() -> None:
    setup_logging()
    log = get_logger()

    try:
        raw = load_config(PASSPHRASE)
    except Exception as e:
        print(f"\nERROR: Could not load config: {e}")
        print("  Recreate the config and try again.\n")
        sys.exit(1)

    config = _build_config(raw)

    print()
    print("Tatkal Agent - Dry Run")
    print("-" * 45)
    print(f"Train    {config.train_number}  {config.from_station} -> {config.to_station}")
    print(f"Date     {config.journey_date}")
    print(f"Class    {config.travel_class.value}  |  Quota: {config.quota}")
    print(f"PAX      {config.passengers[0].name}, {config.passengers[0].age}, {config.passengers[0].gender.value}")
    print(f"Mode     {'DRY RUN (stops at payment page)' if DRY_RUN else 'LIVE BOOKING'}")
    print("-" * 45)
    print()
    print("The browser will open now. Watch it.")
    print("For CAPTCHA: look at the browser, type the text in this terminal.")
    print("For login CAPTCHA: solve it in the browser, then press Enter here.")
    print()
    print("Ctrl+C to abort at any time.")
    print()

    notifier = Notifier()
    captcha  = ManualCaptchaAdapter(notifier)
    browser  = PlaywrightBrowser()
    flow     = BookingFlow(browser, captcha, None, notifier, dry_run=DRY_RUN)

    # Fire immediately — no waiting for Tatkal window
    window_time = datetime.now()

    log.info("dry_run_start", train=config.train_number, quota=config.quota)

    await browser.launch()
    try:
        result = await flow.run(config, window_time)
        print(f"\nFinal result: {result}\n")
    except KeyboardInterrupt:
        print("\n\nAborted by user — no booking made.\n")
    except Exception as e:
        print(f"\nStopped at error: {e}\n")
        print("This is expected if a selector needs adjustment — note which step failed.")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
