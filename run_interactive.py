"""
Interactive entry point for the 5-stage Tatkal booking agent.

Usage:
    python run_interactive.py

No config files, no passphrase.  All booking details are collected interactively
at runtime and stay in memory only.  Credentials are never written to disk.

Stages:
  1. Gather info  — interactive CLI questionnaire
  2. Login        — browser opens, credentials submitted
  3. Pre-fill     — form pre-filled, agent waits for window
  4. Availability — reads live badges, decides class, respects thresholds
  5A. Book        — fills passengers, solves CAPTCHA, pays
  5B. Report      — prints failure table if no class is bookable
"""
import asyncio
import os
import sys
from datetime import datetime, time

sys.path.insert(0, ".")

from logger import setup_logging, get_logger
from core.gather_info import gather_info_interactive
from adapters.browser import PlaywrightBrowser
from adapters.notifier import Notifier
from scheduler import now_ist

log = get_logger()


def _build_captcha_adapter(config):
    """Build the best available CAPTCHA adapter."""
    api_key = config.captcha_api_key or os.environ.get("TWOCAPTCHA_API_KEY")
    if api_key:
        from adapters.captcha_twocaptcha import TwoCaptchaAdapter
        return TwoCaptchaAdapter(api_key), None

    from adapters.captcha_manual import ManualCaptchaAdapter
    return ManualCaptchaAdapter(), None


def _window_datetime(config, override: time | None) -> datetime:
    """Compute the booking window datetime from today's IST date — anchored to
    IST regardless of the machine's own timezone configuration."""
    now = now_ist()
    if override:
        return now.replace(
            hour=override.hour, minute=override.minute,
            second=override.second, microsecond=0
        )
    # Auto-detect: AC classes open at 10:00, non-AC at 11:00
    ac_classes = {"1A", "2A", "3A", "3E", "CC", "EC"}
    hour = 10 if any(c in ac_classes for c in config.class_priority) else 11
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


async def main() -> None:
    setup_logging()

    try:
        config, window_override = gather_info_interactive()
    except KeyboardInterrupt:
        print("\n\nCancelled.\n")
        sys.exit(0)

    window_time = _window_datetime(config, window_override)

    print(f"\n  Window opens at: {window_time.strftime('%H:%M:%S')} IST today")
    if window_time <= now_ist():
        print("  (Window is in the past — firing immediately for testing)")

    from adapters.captcha_file import FileCaptchaAdapter
    from core.booking_flow import BookingFlow

    notifier = Notifier()
    captcha, captcha_fallback = _build_captcha_adapter(config)
    browser = PlaywrightBrowser()
    flow = BookingFlow(browser, captcha, captcha_fallback, notifier, dry_run=False)

    log.info("interactive_run_start",
             train=config.train_number,
             classes=config.class_priority,
             window=window_time.strftime("%H:%M:%S"))

    await browser.launch()
    try:
        result = await flow.run(config, window_time)
        print(f"\nResult: {result}\n")
    except KeyboardInterrupt:
        print("\n\nAborted by user.\n")
    except Exception as e:
        print(f"\nFailed: {e}\n")
        sys.exit(1)
    finally:
        await asyncio.sleep(2)
        await browser.close()
        print("Browser closed.")


if __name__ == "__main__":
    asyncio.run(main())
