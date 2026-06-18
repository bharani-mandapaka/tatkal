import asyncio
import socket
import struct
from datetime import datetime, timedelta

from core.models import BookingConfig

# Seconds between the NTP epoch (1900-01-01) and the Unix epoch (1970-01-01).
_NTP_UNIX_DELTA = 2208988800


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
