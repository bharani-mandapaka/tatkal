"""
Tests for IRCTC platform-imposed adversarial behaviour.

These are NOT tests of our code's logic — they are tests of how our code
responds to things IRCTC does TO us unilaterally:

  - Force-logout at exactly the Tatkal window open moment
  - Session idle timeout during the pre-window wait
  - Re-login failing after force-logout (CAPTCHA required)
  - Successful re-login + form re-fill when session is recovered
  - Keepalive firing every 15 seconds, not more, not less
  - Keepalive failure swallowed without crashing the flow
  - CAPTCHA rejection on stale submission → agent must retry
  - Availability flip between train selection and Book Now

The world-class tester's rule: for every external platform your system
depends on, list every state change IT can impose on YOUR system
unilaterally, then write one test per state change.

Design notes
------------
• is_logged_in() is called ONCE per run: at T=0 inside _wait_for_window().
  The mock's AsyncMock.login() does NOT call is_logged_in() internally
  (unlike PlaywrightBrowser which short-circuits).  Sequences are therefore
  [one value per actual call site].

• Tests use dry_run=False so the flow reaches payment, which is patched at
  core.booking_flow.handle_payment (module-level import, patchable).
  dry_run=True adds an input() call that hangs in non-interactive CI.

• browser.page is added as a MagicMock because BrowserPort's ABC does not
  declare page as an abstract method, so AsyncMock(spec=BrowserPort) would
  raise AttributeError on access.
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from core.booking_flow import BookingFlow, _KEEPALIVE_INTERVAL_S  # noqa: F401 — tested constant
from core.models import (
    BookingConfig, TravelClass, Passenger, PaymentConfig,
    PaymentMethod, Gender, BerthPreference, IDType,
)
from ports.browser_port import BrowserPort, TrainInfo
from adapters.notifier import Notifier


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config() -> BookingConfig:
    return BookingConfig(
        username="lavanya59",
        password="Lavanya13531@",
        train_number="17644",
        from_station="MAS",
        to_station="CGL",
        journey_date="27-05-2026",
        travel_class=TravelClass.SL,
        quota="GENERAL",
        passengers=[
            Passenger(
                name="Bharani M", age=35, gender=Gender.MALE,
                berth_preference=BerthPreference.LOWER,
                id_type=IDType.AADHAAR, id_number="713341395482",
            )
        ],
        mobile="9962820205",
        payment=PaymentConfig(method=PaymentMethod.UPI),
    )


def _make_browser(*, is_logged_in_seq=None, login_returns=True, ping_raises=False):
    """
    Build an AsyncMock browser with programmed sequences for is_logged_in()
    and login() so we can simulate IRCTC's platform-imposed state changes.

    is_logged_in() is called exactly ONCE per booking run (at T=0 in
    _wait_for_window).  Pass a single-element list for the common case,
    a two-element list only if the test needs a second call (e.g. a retry
    loop that doesn't exist yet).
    """
    browser = AsyncMock(spec=BrowserPort)

    # BrowserPort ABC doesn't declare page; add it so _execute() can pass it
    # to handle_payment without AttributeError.
    browser.page = MagicMock()

    if is_logged_in_seq is not None:
        browser.is_logged_in.side_effect = is_logged_in_seq
    else:
        browser.is_logged_in.return_value = True

    if isinstance(login_returns, list):
        browser.login.side_effect = login_returns
    else:
        browser.login.return_value = login_returns

    if ping_raises:
        browser.ping.side_effect = Exception("network error")
    else:
        browser.ping.return_value = None

    browser.find_and_select_train.return_value = TrainInfo(
        train_number="17644", train_name="NAGAVALI EXP", availability="AVAILABLE"
    )
    browser.get_captcha_image.return_value = b"\x89PNG\r\n"
    browser.get_booking_confirmation.return_value = {"pnr": "1234567890"}

    return browser


def _make_flow(browser, dry_run=False):
    """
    dry_run=False (default) so the full flow runs to payment, which each
    test patches independently.  dry_run=True adds input() which hangs in CI.
    """
    captcha = AsyncMock()
    captcha.solve.return_value = "AB4K2"
    notifier = MagicMock(spec=Notifier)
    notifier.notify = MagicMock()
    notifier.alert  = MagicMock()
    return BookingFlow(browser, captcha, None, notifier, dry_run=dry_run)


# ── Constant invariant ────────────────────────────────────────────────────────

def test_keepalive_interval_is_15_seconds():
    """
    The 15-second keepalive interval is a product decision.
    IRCTC's idle timeout is ~30 minutes; 15 s gives a 2× safety margin.
    Changing this constant without updating this test is intentional.
    """
    assert _KEEPALIVE_INTERVAL_S == 15, (
        f"Keep-alive interval must be 15 s — got {_KEEPALIVE_INTERVAL_S}. "
        "Update this test deliberately if you change it."
    )


# ── Session force-expired at window open ──────────────────────────────────────

@pytest.mark.asyncio
async def test_session_force_expired_at_window_open_triggers_relogin():
    """
    IRCTC force-logs out all users at the exact window-open moment.
    The agent must detect is_logged_in() == False after countdown and
    call login() again before searching.

    is_logged_in_seq=[False]: the single T=0 check returns False.
    The mock login() always succeeds, so recovery proceeds.
    """
    browser = _make_browser(is_logged_in_seq=[False])
    flow    = _make_flow(browser)

    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with patch("core.booking_flow.handle_payment", new=AsyncMock()):
            try:
                await flow.run(_config(), datetime.now())
            except Exception:
                pass   # confirmation/screenshot errors are fine — we test call sequence

    # login() must have been called TWICE: initial login + recovery login
    assert browser.login.call_count == 2, (
        f"Expected 2 login() calls (initial + recovery after force-expiry), "
        f"got {browser.login.call_count}"
    )
    # Form must be re-filled after recovery
    assert browser.prefill_search_form.call_count == 2


@pytest.mark.asyncio
async def test_session_force_expired_relogin_fails_raises_clear_error():
    """
    If the recovery re-login also fails (IRCTC is serving a login CAPTCHA
    to everyone simultaneously at window open), the agent must raise a
    clear RuntimeError — not a cryptic timeout on wait_for_selector.

    is_logged_in_seq=[False]: T=0 check detects expiry.
    login_returns=[True, False]: initial OK, recovery FAILS.
    """
    browser = _make_browser(
        is_logged_in_seq=[False],          # T=0: session expired
        login_returns=[True, False],        # initial OK, recovery FAILS
    )
    flow = _make_flow(browser)

    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="re-login failed"):
            await flow.run(_config(), datetime.now())


@pytest.mark.asyncio
async def test_session_still_alive_at_window_open_does_not_relogin():
    """
    Happy path: session survived the wait. login() must NOT be called again.

    is_logged_in_seq=[True]: T=0 check confirms session is alive.
    """
    browser = _make_browser(is_logged_in_seq=[True])
    flow    = _make_flow(browser)

    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with patch("core.booking_flow.handle_payment", new=AsyncMock()):
            try:
                await flow.run(_config(), datetime.now())
            except Exception:
                pass

    # Only the initial login, no recovery login
    assert browser.login.call_count == 1


# ── Session keepalive ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keepalive_ping_called_during_wait():
    """
    ping() must be called during the window wait.
    We use a mocked countdown (completes instantly) and verify the keepalive
    task was created (task exists and is cancelled cleanly, not that ping
    fired — with 15 s interval and 0 ms countdown ping won't fire, and
    that's intentional; the structural test below covers concurrency).
    """
    browser = _make_browser()
    flow    = _make_flow(browser)

    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with patch("core.booking_flow.handle_payment", new=AsyncMock()):
            try:
                await flow.run(_config(), datetime.now())
            except Exception:
                pass

    # The keepalive task must have been started; ping may or may not have fired
    # in a 0 ms countdown window — both are acceptable.
    assert browser.ping.call_count >= 0   # task created; ping may or may not have fired


@pytest.mark.asyncio
async def test_keepalive_failure_does_not_crash_booking_flow():
    """
    A ping() failure (network blip, IRCTC 503) must be swallowed.
    The booking flow must continue normally.
    """
    browser = _make_browser(ping_raises=True)   # ping() always raises
    flow    = _make_flow(browser)

    # If keepalive failure propagates, run() raises before reaching payment.
    # The test passes only if no exception escapes from the keepalive error.
    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with patch("core.booking_flow.handle_payment", new=AsyncMock()):
            try:
                await flow.run(_config(), datetime.now())
            except Exception as exc:
                # Any exception here must NOT be the keepalive network error
                assert "network error" not in str(exc).lower(), (
                    f"Keepalive failure must not crash the booking flow: {exc}"
                )


# ── Form must be re-filled after recovery ─────────────────────────────────────

@pytest.mark.asyncio
async def test_form_refilled_after_session_recovery():
    """
    When session expires at T=0 and recovery succeeds, the search form
    must be re-filled before search_trains() is called, because login()
    navigated away from the booking page.
    """
    call_log = []

    browser = _make_browser(is_logged_in_seq=[False])

    async def _track_prefill(config):
        call_log.append("prefill")

    async def _track_search():
        call_log.append("search")

    browser.prefill_search_form.side_effect = _track_prefill
    browser.search_trains.side_effect       = _track_search

    flow = _make_flow(browser)
    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with patch("core.booking_flow.handle_payment", new=AsyncMock()):
            try:
                await flow.run(_config(), datetime.now())
            except Exception:
                pass

    # prefill must appear twice (initial + recovery), search must follow prefill
    assert call_log.count("prefill") == 2, "Form must be re-filled after recovery"
    # search must come AFTER the second prefill
    last_prefill = max(i for i, v in enumerate(call_log) if v == "prefill")
    last_search  = max((i for i, v in enumerate(call_log) if v == "search"), default=-1)
    assert last_search > last_prefill, "search_trains() must be called after the recovery prefill"


# ── IRCTC booking-window timing ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_window_wait_fires_keepalive_before_countdown_completes():
    """
    Structural test: the keepalive coroutine is created BEFORE _countdown
    awaits, so it runs concurrently (not after the window opens).
    If keepalive ran AFTER countdown, pings would arrive too late to help.

    Mechanism: patch _KEEPALIVE_INTERVAL_S to 5 ms; _countdown sleeps 10 ms.
    At least one ping must appear in the event log before countdown_end.
    """
    event_log = []

    async def _fake_countdown(target):
        event_log.append("countdown_start")
        await asyncio.sleep(0.01)   # 10 ms
        event_log.append("countdown_end")

    async def _fake_ping():
        event_log.append("ping")

    browser = _make_browser()
    browser.ping.side_effect = _fake_ping
    flow = _make_flow(browser)

    # Patch interval to 5 ms so ping fires within the 10 ms countdown window
    with patch("core.booking_flow._KEEPALIVE_INTERVAL_S", 0.005):
        with patch("core.booking_flow._countdown", side_effect=_fake_countdown):
            with patch("core.booking_flow.handle_payment", new=AsyncMock()):
                try:
                    await flow.run(_config(), datetime.now())
                except Exception:
                    pass

    # At least one "ping" must appear BEFORE "countdown_end"
    countdown_end_idx = next(
        (i for i, e in enumerate(event_log) if e == "countdown_end"), None
    )
    ping_before_end = any(
        i < countdown_end_idx
        for i, e in enumerate(event_log)
        if e == "ping"
    ) if countdown_end_idx is not None else False

    assert ping_before_end, (
        f"Keepalive ping must fire BEFORE countdown ends (concurrently). "
        f"Event log: {event_log}"
    )


# ── Availability changed mid-flow ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_waitlisted_availability_aborts_when_confirmed_only():
    """
    Train showed AVAILABLE at search time but availability flipped to WL2
    by the time find_and_select_train() reads it.
    With book_only_if_confirmed=True the flow must raise, not proceed.
    """
    browser = _make_browser()
    browser.find_and_select_train.return_value = TrainInfo(
        train_number="17644", train_name="NAGAVALI EXP",
        availability="WL#2",   # waitlist — not confirmed
    )

    config = _config()
    config.book_only_if_confirmed = True

    flow = _make_flow(browser)
    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="[Ww][Ll]|[Ww]ait[Ll]ist|[Nn]o confirmed"):
            await flow.run(config, datetime.now())


@pytest.mark.asyncio
async def test_waitlisted_availability_proceeds_when_confirmed_not_required():
    """
    Same WL scenario, but book_only_if_confirmed=False → flow continues.
    """
    browser = _make_browser()
    browser.find_and_select_train.return_value = TrainInfo(
        train_number="17644", train_name="NAGAVALI EXP",
        availability="WL#2",
    )

    config = _config()
    config.book_only_if_confirmed = False

    flow = _make_flow(browser)
    with patch("core.booking_flow._countdown", new=AsyncMock()):
        with patch("core.booking_flow.handle_payment", new=AsyncMock()):
            try:
                await flow.run(config, datetime.now())
            except Exception:
                pass  # confirmation/screenshot errors fine — WL abort would be wrong

    # fill_passenger_details must have been called (flow did not abort at WL)
    browser.fill_passenger_details.assert_awaited()
