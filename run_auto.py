"""
Non-interactive dry-run launcher for automated / Claude-controlled runs.

Differences from run_now.py:
  - Uses FileCaptchaAdapter: saves captcha_current.png, waits for captcha_answer.txt
  - Patches builtins.input() → empty string so login-CAPTCHA Enter and
    dry-run pause never block on stdin
  - Writes a screenshot at the end of each major step to step_*.png

Run via Bash tool:
    python run_auto.py

Monitor progress:
    Read captcha_current.png when it appears, write answer to captcha_answer.txt
"""
import asyncio
import builtins
import sys
from datetime import datetime
from pathlib import Path

# ── Patch input() before any other import that might call it ──────────────────
# Most prompts can be auto-confirmed (empty Enter), but the login CAPTCHA prompt
# requires a real human in front of the browser to solve the puzzle.  Bypassing
# it silently sends an unsolved CAPTCHA, IRCTC rejects the login, and the
# "first login never goes through" symptom shows up downstream.
#
# Heuristic: any prompt whose text contains "captcha" / "solve" / "solving"
# is treated as needing real human input.  Everything else (Press Enter to
# close, etc.) gets auto-confirmed.
_original_input = builtins.input

def _auto_input(prompt=""):
    p = (prompt or "").lower()
    if any(token in p for token in ("captcha", "solve", "solving")):
        # Wait for the user to solve the CAPTCHA in the browser and hit Enter.
        print(f"\n  [USER ACTION REQUIRED] {prompt}")
        return _original_input("")  # real blocking input
    print(f"  [auto-input] '{prompt}' → <Enter>")
    return ""

builtins.input = _auto_input

# ── Normal imports (after patch) ──────────────────────────────────────────────
sys.path.insert(0, ".")

from logger import setup_logging, get_logger
from config import load_config
from adapters.browser import PlaywrightBrowser
from adapters.captcha_file import FileCaptchaAdapter
from adapters.notifier import Notifier
from core.booking_flow import BookingFlow
from main import _build_config

PASSPHRASE = "17644MAS"
DRY_RUN    = True

_HERE = Path(__file__).resolve().parent


async def _snap(browser: PlaywrightBrowser, name: str) -> None:
    """Save a screenshot to disk for inspection."""
    path = str(_HERE / f"step_{name}.png")
    try:
        await browser.screenshot(path)
        print(f"  [snap] {path}")
    except Exception as e:
        print(f"  [snap] failed: {e}")


async def main() -> None:
    setup_logging()
    log = get_logger()

    try:
        raw = load_config(PASSPHRASE)
    except Exception as e:
        print(f"\nERROR: Could not load config: {e}\n")
        sys.exit(1)

    config = _build_config(raw)

    print()
    print("Tatkal Agent - Auto Dry Run")
    print("-" * 45)
    print(f"Train    {config.train_number}  {config.from_station} -> {config.to_station}")
    print(f"Date     {config.journey_date}")
    print(f"Class    {config.travel_class.value}  |  Quota: {config.quota}")
    print(f"PAX      {config.passengers[0].name}, {config.passengers[0].age}")
    print(f"Mode     DRY RUN (stops at payment page)")
    print("-" * 45)
    print()

    notifier = Notifier()
    captcha  = FileCaptchaAdapter(notifier, timeout_s=120)
    browser  = PlaywrightBrowser()
    flow     = BookingFlow(browser, captcha, None, notifier, dry_run=DRY_RUN)

    window_time = datetime.now()   # fire immediately

    log.info("auto_dry_run_start", train=config.train_number, quota=config.quota)

    await browser.launch()
    try:
        result = await flow.run(config, window_time)
        print(f"\nResult: {result}\n")
        await _snap(browser, "payment_page")
    except KeyboardInterrupt:
        print("\n\nAborted by user.\n")
        await _snap(browser, "aborted")
    except Exception as e:
        print(f"\nStopped at: {e}\n")
        await _snap(browser, "error")
    finally:
        # Give a moment to inspect before closing
        await asyncio.sleep(2)
        await browser.close()
        print("Browser closed.")


if __name__ == "__main__":
    asyncio.run(main())
