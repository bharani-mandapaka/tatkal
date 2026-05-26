import asyncio

from playwright.async_api import Page

from adapters.notifier import Notifier
from core.models import PaymentConfig, PaymentMethod
from logger import get_logger

log = get_logger()


async def handle_payment(page: Page, config: PaymentConfig, notifier: Notifier) -> None:
    try:
        if config.method == PaymentMethod.EWALLET:
            await _handle_ewallet(page, config)
        elif config.method == PaymentMethod.UPI:
            await _handle_upi(page, config, notifier)
        elif config.method == PaymentMethod.CARD:
            await _handle_card(page, config)
        else:
            raise ValueError(f"Unknown payment method: {config.method}")
    finally:
        config.clear_sensitive()


async def _handle_ewallet(page: Page, config: PaymentConfig) -> None:
    log.info("payment_ewallet_start")
    await page.locator(
        "label:has-text('IRCTC Wallet'), input[value='IRCTC_WALLET']"
    ).first.click()
    await asyncio.sleep(0.5)

    mpin_inp = page.locator(
        "input[placeholder*='MPIN'], input[id*='walletPin'], input[id*='mpin']"
    ).first
    await mpin_inp.fill(config.wallet_mpin or "")
    await asyncio.sleep(0.3)

    await page.locator("button:has-text('Pay')").first.click()
    log.info("payment_ewallet_submitted")


async def _handle_upi(page: Page, config: PaymentConfig, notifier: Notifier) -> None:
    log.info("payment_upi_start")
    await page.locator(
        "label:has-text('UPI'), input[value='UPI']"
    ).first.click()
    await asyncio.sleep(0.5)

    upi_inp = page.locator(
        "input[placeholder*='UPI'], input[placeholder*='VPA'], input[id*='upiId']"
    ).first
    await upi_inp.fill(config.upi_id or "")
    await asyncio.sleep(0.3)

    await page.locator("button:has-text('Pay')").first.click()

    print("\n  ┌──────────────────────────────────────┐")
    print("  │  Approve the payment on your phone   │")
    print(f"  │  VPA: {(config.upi_id or ''):<30}  │")
    print("  │  Timeout: 5 minutes                  │")
    print("  └──────────────────────────────────────┘")
    print("\n  Waiting for UPI callback...\n")
    notifier.alert("Approve UPI collect request on your phone now")
    log.info("payment_upi_waiting")


async def _handle_card(page: Page, config: PaymentConfig) -> None:
    log.info("payment_card_start")
    await page.locator(
        "label:has-text('Credit'), label:has-text('Debit'), input[value='CARD']"
    ).first.click()
    await asyncio.sleep(0.5)

    await page.locator(
        "input[id*='cardNumber'], input[placeholder*='Card Number']"
    ).first.fill(config.card_number or "")
    await asyncio.sleep(0.2)

    await page.locator(
        "input[id*='expiry'], input[placeholder*='MM/YY']"
    ).first.fill(config.card_expiry or "")
    await asyncio.sleep(0.2)

    await page.locator(
        "input[id*='cvv'], input[placeholder*='CVV']"
    ).first.fill(config.card_cvv or "")
    await asyncio.sleep(0.2)

    await page.locator("button:has-text('Pay')").first.click()

    # Wait for OTP input on the bank redirect page
    await page.wait_for_selector(
        "input[id*='otp'], input[placeholder*='OTP'], input[name*='otp']", timeout=30_000
    )
    otp = input("\n  Enter OTP received on mobile: ").strip()
    await page.locator(
        "input[id*='otp'], input[placeholder*='OTP'], input[name*='otp']"
    ).first.fill(otp)
    await page.locator(
        "button:has-text('Submit'), button:has-text('Verify')"
    ).first.click()
    log.info("payment_card_otp_submitted")
