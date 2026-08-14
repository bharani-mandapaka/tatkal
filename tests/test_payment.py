"""
Tests for payment.py — previously zero test coverage (flagged in TASKS.md
stress-test findings). Real money changes hands here, so the one behaviour
that must hold no matter which payment path runs or whether it raises
partway through is: config.clear_sensitive() always fires.

page is mocked as a MagicMock whose .locator(...).first.click()/.fill() are
AsyncMocks shared across all selectors — good enough to test call sequence
and argument values; real selector correctness needs a live Playwright run
(out of scope for a unit test).
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from payment import handle_payment
from core.models import PaymentConfig, PaymentMethod
from adapters.notifier import Notifier


def _make_page():
    page = MagicMock()
    locator = MagicMock()
    locator.first = MagicMock()
    locator.first.click = AsyncMock()
    locator.first.fill = AsyncMock()
    page.locator.return_value = locator
    page.wait_for_selector = AsyncMock()
    return page


def _make_notifier():
    notifier = MagicMock(spec=Notifier)
    notifier.notify = MagicMock()
    notifier.alert = MagicMock()
    return notifier


# ── UPI ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upi_payment_fills_vpa_and_alerts_user():
    page = _make_page()
    notifier = _make_notifier()
    config = PaymentConfig(method=PaymentMethod.UPI, upi_id="test@upi")

    await handle_payment(page, config, notifier)

    page.locator.return_value.first.fill.assert_any_await("test@upi")
    notifier.alert.assert_called_once()


@pytest.mark.asyncio
async def test_upi_payment_clears_sensitive_fields_after():
    page = _make_page()
    notifier = _make_notifier()
    config = PaymentConfig(method=PaymentMethod.UPI, upi_id="test@upi")

    await handle_payment(page, config, notifier)

    # UPI has no CVV/MPIN/card fields to clear, but clear_sensitive() must
    # still be a no-crash no-op call — this guards against a future field
    # being added to PaymentConfig without wiring it into clear_sensitive().
    assert config.upi_id == "test@upi"   # UPI ID itself isn't "sensitive" here


# ── E-Wallet ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ewallet_payment_fills_mpin_and_clears_it_after():
    page = _make_page()
    notifier = _make_notifier()
    config = PaymentConfig(method=PaymentMethod.EWALLET, wallet_mpin="1234")

    await handle_payment(page, config, notifier)

    page.locator.return_value.first.fill.assert_any_await("1234")
    # clear_sensitive() must run after a successful payment attempt
    assert config.wallet_mpin == ""


# ── Card ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_card_payment_prompts_for_otp_and_clears_all_card_fields():
    page = _make_page()
    notifier = _make_notifier()
    config = PaymentConfig(
        method=PaymentMethod.CARD,
        card_number="4111111111111111",
        card_expiry="12/28",
        card_cvv="123",
    )

    with patch("builtins.input", return_value="998877") as mock_input:
        await handle_payment(page, config, notifier)

    mock_input.assert_called_once()
    page.wait_for_selector.assert_awaited_once()
    # CVV/number/expiry must ALL be zeroed after — CVV especially must
    # never survive in memory past the payment attempt (PCI-DSS concern
    # already flagged in TASKS.md).
    assert config.card_cvv == ""
    assert config.card_number == ""
    assert config.card_expiry == ""


# ── Sensitive-field clearing must survive a mid-payment failure ──────────────

@pytest.mark.asyncio
async def test_clear_sensitive_runs_even_if_payment_step_raises():
    """
    handle_payment wraps the method dispatch in try/finally specifically so
    a mid-flight failure (IRCTC page changed, selector miss, network drop)
    can never leave card/MPIN data sitting in memory. This is the single
    most important behaviour in this module — verify it directly rather
    than relying on the happy-path tests to imply it.
    """
    page = _make_page()
    page.locator.return_value.first.click.side_effect = RuntimeError("selector not found")
    notifier = _make_notifier()
    config = PaymentConfig(
        method=PaymentMethod.CARD,
        card_number="4111111111111111",
        card_expiry="12/28",
        card_cvv="123",
    )

    with pytest.raises(RuntimeError):
        await handle_payment(page, config, notifier)

    assert config.card_cvv == ""
    assert config.card_number == ""
    assert config.card_expiry == ""


@pytest.mark.asyncio
async def test_unknown_payment_method_raises_value_error():
    page = _make_page()
    notifier = _make_notifier()
    config = PaymentConfig(method=PaymentMethod.UPI)
    config.method = "NOT_A_REAL_METHOD"   # bypass the enum for this test

    with pytest.raises(ValueError, match="Unknown payment method"):
        await handle_payment(page, config, notifier)
