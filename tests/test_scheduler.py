import asyncio
from datetime import timedelta

import pytest

from core.models import BookingConfig, TravelClass, PaymentConfig, PaymentMethod
from scheduler import calculate_booking_times, wait_until, now_ist


def _cfg(cls: TravelClass, date: str = "27-05-2026", quota: str = "TATKAL") -> BookingConfig:
    return BookingConfig(
        username="t", password="t", train_number="12951",
        from_station="NDLS", to_station="MAS",
        journey_date=date, travel_class=cls, quota=quota,
        passengers=[], mobile="9999999999",
        payment=PaymentConfig(method=PaymentMethod.UPI, upi_id="t@upi"),
    )


# ── Booking time calculation ───────────────────────────────────────────────────

def test_ac_window_opens_at_10():
    _, window = calculate_booking_times(_cfg(TravelClass.TWO_A))
    assert window.hour == 10 and window.minute == 0 and window.second == 0


def test_sl_window_opens_at_11():
    _, window = calculate_booking_times(_cfg(TravelClass.SL))
    assert window.hour == 11 and window.minute == 0 and window.second == 0


def test_login_is_3_minutes_before_window():
    login, window = calculate_booking_times(_cfg(TravelClass.TWO_A))
    assert (window - login).total_seconds() == 180


def test_booking_date_is_day_before_journey():
    _, window = calculate_booking_times(_cfg(TravelClass.TWO_A, "27-05-2026"))
    assert window.day == 26 and window.month == 5 and window.year == 2026


def test_cc_is_ac_class():
    _, window = calculate_booking_times(_cfg(TravelClass.CC))
    assert window.hour == 10


def test_two_s_is_non_ac():
    _, window = calculate_booking_times(_cfg(TravelClass.TWO_S))
    assert window.hour == 11


# ── Non-Tatkal quotas fire immediately (no fixed opening time) ─────────────────

def test_general_quota_fires_immediately():
    """GENERAL has no 10/11 AM window — login_time and window_time must both
    collapse to 'now', not the Tatkal-style day-before calculation."""
    before = now_ist()
    login, window = calculate_booking_times(_cfg(TravelClass.SL, quota="GENERAL"))
    after = now_ist()
    assert before <= login <= after
    assert login == window


def test_ladies_quota_fires_immediately():
    login, window = calculate_booking_times(_cfg(TravelClass.SL, quota="LADIES"))
    assert login == window


def test_tatkal_quota_still_uses_fixed_window():
    """Regression guard: TATKAL (the default) must be unaffected by the
    non-Tatkal fast-path."""
    _, window = calculate_booking_times(_cfg(TravelClass.SL, quota="TATKAL"))
    assert window.hour == 11


def test_premium_tatkal_quota_still_uses_fixed_window():
    _, window = calculate_booking_times(_cfg(TravelClass.TWO_A, quota="PREMIUM TATKAL"))
    assert window.hour == 10


def test_quota_check_is_case_insensitive():
    login, window = calculate_booking_times(_cfg(TravelClass.SL, quota="general"))
    assert login == window


# ── Timezone-awareness (booking windows are IST regardless of machine tz) ──────

def test_window_times_are_ist_aware():
    login, window = calculate_booking_times(_cfg(TravelClass.TWO_A))
    assert window.tzinfo is not None and window.utcoffset() == timedelta(hours=5, minutes=30)
    assert login.tzinfo is not None and login.utcoffset() == timedelta(hours=5, minutes=30)


def test_now_ist_matches_ist_offset():
    assert now_ist().utcoffset() == timedelta(hours=5, minutes=30)


# ── wait_until precision ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_until_fires_within_tolerance():
    target = now_ist() + timedelta(milliseconds=500)
    t0 = now_ist()
    await wait_until(target)
    elapsed = (now_ist() - t0).total_seconds()
    assert 0.45 <= elapsed <= 0.75, f"Elapsed {elapsed:.3f}s — expected ~0.5s"


@pytest.mark.asyncio
async def test_wait_until_past_target_returns_immediately():
    target = now_ist() - timedelta(seconds=1)
    t0 = now_ist()
    await wait_until(target)
    elapsed = (now_ist() - t0).total_seconds()
    assert elapsed < 0.05, f"Should return instantly, took {elapsed:.3f}s"
