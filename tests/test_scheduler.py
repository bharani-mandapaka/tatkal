import asyncio
from datetime import datetime, timedelta

import pytest

from core.models import BookingConfig, TravelClass, PaymentConfig, PaymentMethod
from scheduler import calculate_booking_times, wait_until


def _cfg(cls: TravelClass, date: str = "27-05-2026") -> BookingConfig:
    return BookingConfig(
        username="t", password="t", train_number="12951",
        from_station="NDLS", to_station="MAS",
        journey_date=date, travel_class=cls,
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


# ── wait_until precision ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_until_fires_within_tolerance():
    target = datetime.now() + timedelta(milliseconds=500)
    t0 = datetime.now()
    await wait_until(target)
    elapsed = (datetime.now() - t0).total_seconds()
    assert 0.45 <= elapsed <= 0.75, f"Elapsed {elapsed:.3f}s — expected ~0.5s"


@pytest.mark.asyncio
async def test_wait_until_past_target_returns_immediately():
    target = datetime.now() - timedelta(seconds=1)
    t0 = datetime.now()
    await wait_until(target)
    elapsed = (datetime.now() - t0).total_seconds()
    assert elapsed < 0.05, f"Should return instantly, took {elapsed:.3f}s"
