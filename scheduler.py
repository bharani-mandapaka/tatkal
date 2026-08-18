import asyncio
import socket
import struct
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.models import BookingConfig

# Seconds between the NTP epoch (1900-01-01) and the Unix epoch (1970-01-01).
_NTP_UNIX_DELTA = 2208988800

# Tatkal windows are defined in India Standard Time regardless of what
# timezone the machine running this is configured for. datetime.now(IST)
# gives the correct real-world IST instant off the system's UTC-based clock —
# it does NOT trust the OS's configured local timezone the way a naive
# datetime.now() comparison would, so a misconfigured machine clock (wrong
# timezone, not just wrong time) can't silently fire the booking hours off.
IST = ZoneInfo("Asia/Kolkata")

# Only these quotas have a fixed IRCTC opening time (10:00 AC / 11:00 non-AC,
# exactly one day before travel). GENERAL, LADIES, and other non-Tatkal
# quotas can be booked any time within the normal reservation period —
# there is nothing to wait for.
TATKAL_QUOTAS = {"TATKAL", "PREMIUM TATKAL"}


def now_ist() -> datetime:
    return datetime.now(IST)


def get_ntp_offset(server: str = "pool.ntp.org", timeout: float = 3.0) -> float:
    """
    Return (true time − local clock) in seconds via a minimal SNTP query.

    Positive  → the local clock is BEHIND real time (booking would fire late).
    Negative  → the local clock is AHEAD of real time (booking would fire early).

    Dependency-free (stdlib socket/struct). Raises OSError on network failure
    or timeout — callers should treat that as "skew unknown", not "skew zero".
    """
    # SNTP client request: leap=0, version=3, mode=3 → first byte 0x1B, rest zero.
    packet = b"\x1b" + 47 * b"\x00"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(packet, (server, 123))
        t0 = datetime.now().timestamp()
        data, _ = s.recvfrom(48)
        t1 = datetime.now().timestamp()

    # Transmit timestamp = bytes 40..48: 32-bit seconds + 32-bit fraction.
    secs, frac = struct.unpack("!II", data[40:48])
    server_time = (secs - _NTP_UNIX_DELTA) + frac / 2 ** 32
    # Approximate local time at the instant the server stamped its reply.
    local_at_reply = (t0 + t1) / 2
    return server_time - local_at_reply


def calculate_booking_times(config: BookingConfig) -> tuple[datetime, datetime]:
    """Return (login_time, window_open_time) for the given config, anchored to
    IST regardless of the machine's own timezone configuration.

    Non-Tatkal quotas (GENERAL, LADIES, ...) have no fixed opening time —
    fire immediately instead of waiting for a Tatkal-style 10/11 AM window
    that doesn't apply to them."""
    if config.quota.upper() not in TATKAL_QUOTAS:
        immediate = now_ist()
        return immediate, immediate

    day, month, year = config.journey_date.split("-")
    journey_dt = datetime(int(year), int(month), int(day), tzinfo=IST)
    booking_date = journey_dt - timedelta(days=1)

    hour = 10 if config.is_ac_class else 11
    window_open = booking_date.replace(hour=hour, minute=0, second=0, microsecond=0)
    login_time = window_open - timedelta(minutes=3)
    return login_time, window_open


async def wait_until(target: datetime) -> None:
    """High-precision async wait — wakes every 100 ms in the final 10 seconds.

    `target` must be timezone-aware (see calculate_booking_times) — compared
    against the true IST instant, not the machine's local clock reading."""
    while True:
        remaining = (target - now_ist()).total_seconds()
        if remaining <= 0:
            return
        if remaining > 60:
            await asyncio.sleep(30)
        elif remaining > 10:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.1)
