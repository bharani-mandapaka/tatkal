#!/usr/bin/env python3
"""
Tatkal Agent — Entry Point

Usage:
  python main.py collect   # Run once to save encrypted booking details
  python main.py check     # Verify config, Playwright, and timing
  python main.py run       # Start the agent (keep terminal open)
"""
import asyncio
import json
import sys
from datetime import datetime

from logger import setup_logging, get_logger

log = get_logger()


# ── Command: collect ──────────────────────────────────────────────────────────

def cmd_collect() -> None:
    from collector import collect
    collect()


# ── Command: check ────────────────────────────────────────────────────────────

def cmd_check() -> None:
    import questionary
    from config import config_exists, load_config
    from scheduler import calculate_booking_times

    print("\nTatkal Agent — Pre-run Check")
    print("─" * 35)

    if not config_exists():
        print("Config file         ✗ NOT FOUND — run: python main.py collect")
        sys.exit(1)
    print("Config file         ✓ Found")

    passphrase = questionary.password("Passphrase:").ask()
    try:
        raw = load_config(passphrase)
        print("Passphrase          ✓ Correct")
    except Exception:
        print("Passphrase          ✗ Incorrect")
        sys.exit(1)

    try:
        import playwright  # noqa: F401
        print("Playwright          ✓ Installed")
    except ImportError:
        print(
            "Playwright          ✗ Not installed\n"
            "                    Run: pip install playwright && playwright install chromium"
        )
        sys.exit(1)

    if raw.get("captcha_api_key"):
        print("2captcha key        ✓ Configured")
    else:
        print("2captcha key        — Not set (manual CAPTCHA mode)")

    config = _build_config(raw)
    login_time, window_time = calculate_booking_times(config)
    remaining = window_time - datetime.now()
    hours = int(remaining.total_seconds() // 3600)
    mins = int((remaining.total_seconds() % 3600) // 60)

    print(f"Booking window      {window_time.strftime('%H:%M:%S')} · {window_time.strftime('%d %b %Y')}")
    print(f"Login fires at      {login_time.strftime('%H:%M:%S')}")
    print(f"Time until login    {hours}h {mins:02d}m")
    print("\nAll checks passed.")
    print("Run 'python main.py run' and keep this terminal open.\n")


# ── Command: run ──────────────────────────────────────────────────────────────

async def cmd_run() -> None:
    import questionary
    from config import config_exists, load_config
    from scheduler import calculate_booking_times, wait_until
    from adapters.browser import PlaywrightBrowser
    from adapters.captcha_twocaptcha import TwoCaptchaAdapter
    from adapters.captcha_manual import ManualCaptchaAdapter
    from adapters.notifier import Notifier
    from core.booking_flow import BookingFlow

    if not config_exists():
        print("✗ No config found. Run: python main.py collect")
        sys.exit(1)

    passphrase = questionary.password("Passphrase:").ask()
    try:
        raw = load_config(passphrase)
    except Exception:
        print("✗ Wrong passphrase.")
        sys.exit(1)

    config = _build_config(raw)
    login_time, window_time = calculate_booking_times(config)
    notifier = Notifier()

    _print_preflight(config, login_time, window_time)
    input("\n[Press Enter to start, Ctrl+C to cancel...]\n")

    # Wire captcha solvers
    if raw.get("captcha_api_key"):
        primary_captcha = TwoCaptchaAdapter(raw["captcha_api_key"])
        fallback_captcha = ManualCaptchaAdapter(notifier)
    else:
        primary_captcha = ManualCaptchaAdapter(notifier)
        fallback_captcha = None

    browser = PlaywrightBrowser()
    flow = BookingFlow(browser, primary_captcha, fallback_captcha, notifier)

    log_file = f"session_{datetime.now().strftime('%Y%m%d')}.log"
    setup_logging(log_file)

    await browser.launch()
    try:
        # Wait until login time if we're early
        if datetime.now() < login_time:
            remaining = (login_time - datetime.now()).total_seconds()
            log.info("waiting",
                     target=login_time.strftime("%H:%M:%S"),
                     remaining_min=f"{remaining / 60:.1f}")
            await wait_until(login_time)

        result = await flow.run(config, window_time)

        result_file = f"booking_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"  Full result saved → {result_file}")

    finally:
        await browser.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_config(raw: dict):
    from core.models import (
        BookingConfig, TravelClass, Passenger, PaymentConfig,
        PaymentMethod, Gender, BerthPreference, IDType,
    )

    passengers = [
        Passenger(
            name=p["name"],
            age=p["age"],
            gender=Gender(p["gender"]),
            berth_preference=BerthPreference(p["berth_preference"]),
            id_type=IDType(p["id_type"]),
            id_number=p["id_number"],
        )
        for p in raw["passengers"]
    ]

    pr = raw["payment"]
    payment = PaymentConfig(
        method=PaymentMethod(pr["method"]),
        upi_id=pr.get("upi_id"),
        wallet_mpin=pr.get("wallet_mpin"),
        card_number=pr.get("card_number"),
        card_expiry=pr.get("card_expiry"),
        card_cvv=pr.get("card_cvv"),
    )

    return BookingConfig(
        username=raw["username"],
        password=raw["password"],
        train_number=raw["train_number"],
        from_station=raw["from_station"],
        to_station=raw["to_station"],
        journey_date=raw["journey_date"],
        travel_class=TravelClass(raw["travel_class"]),
        boarding_point=raw.get("boarding_point"),
        passengers=passengers,
        mobile=raw["mobile"],
        payment=payment,
        book_only_if_confirmed=raw.get("book_only_if_confirmed", True),
        captcha_api_key=raw.get("captcha_api_key"),
    )


def _print_preflight(config, login_time: datetime, window_time: datetime) -> None:
    from core.models import PaymentMethod

    pm = config.payment
    if pm:
        if pm.method == PaymentMethod.UPI:
            pay_str = f"UPI ({pm.upi_id})"
        elif pm.method == PaymentMethod.EWALLET:
            pay_str = "IRCTC e-Wallet"
        else:
            pay_str = "Credit/Debit Card"
    else:
        pay_str = "UNKNOWN"

    print(f"""
Tatkal Agent — v1.0
{'─' * 39}
Decrypting config...          ✓
Target train                  {config.train_number} · {config.from_station} → {config.to_station}
Class                         {config.travel_class.value} (Tatkal)
Booking window opens          {window_time.strftime('%H:%M:%S')} on {window_time.strftime('%d %b %Y')}
Login fires at                {login_time.strftime('%H:%M:%S')}

Passengers:""")
    for i, p in enumerate(config.passengers, 1):
        print(f"  {i}. {p.name} ({p.gender.value}, {p.age}) — {p.berth_preference.value}")
    print(f"""
Payment method                {pay_str}

[Do NOT close this window or let your laptop sleep.]""")


# ── Entry ─────────────────────────────────────────────────────────────────────

def main() -> None:
    setup_logging()
    if len(sys.argv) < 2:
        print("Usage: python main.py [collect|run|check]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "collect":
        cmd_collect()
    elif cmd == "check":
        cmd_check()
    elif cmd == "run":
        asyncio.run(cmd_run())
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
