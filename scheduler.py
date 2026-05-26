import asyncio
from datetime import datetime, timedelta

from core.models import BookingConfig


def calculate_booking_times(config: BookingConfig) -> tuple[datetime, datetime]:
    """Return (login_time, window_open_time) for the given config."""
    day, month, year = config.journey_date.split("-")
    journey_dt = datetime(int(year), int(month), int(day))
    booking_date = journey_dt - timedelta(days=1)

    hour = 10 if config.is_ac_class else 11
    window_open = booking_date.replace(hour=hour, minute=0, second=0, microsecond=0)
    login_time = window_open - timedelta(minutes=3)
    return login_time, window_open


async def wait_until(target: datetime) -> None:
    """High-precision async wait — wakes every 100 ms in the final 10 seconds."""
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        if remaining > 60:
            await asyncio.sleep(30)
        elif remaining > 10:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.1)
