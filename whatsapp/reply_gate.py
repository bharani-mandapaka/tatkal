"""
Reply Gate — asyncio bridge between the WhatsApp webhook and waiting Playwright coroutines.

How it works:
  1. Playwright coroutine calls `wait_for_reply(phone, timeout=10)` and suspends.
  2. Webhook receives a WhatsApp message from `phone`, calls `deliver_reply(phone, text)`.
  3. deliver_reply() sets the asyncio.Event — the waiting coroutine resumes immediately.
  4. If no reply arrives within `timeout` seconds, wait_for_reply() returns None.

Admin HITL for CAPTCHA:
  - CAPTCHA image is sent to `admin_phone` (may differ from passenger phone).
  - The gate listens on `admin_phone` so the operator's reply unblocks the coroutine.
  - Timeout is 10 seconds — operator must be watching their phone at the booking window.
  - 2captcha is always tried first (5–8s); this gate is the fallback only.
"""

import asyncio
from typing import Optional

# phone_number → asyncio.Event
_gates: dict[str, asyncio.Event] = {}

# phone_number → reply text
_replies: dict[str, str] = {}


async def wait_for_reply(phone: str, timeout: float = 10.0) -> Optional[str]:
    """
    Suspend the calling coroutine until `phone` sends a WhatsApp text reply,
    or until `timeout` seconds elapse.

    Returns the reply text, or None on timeout.
    """
    event = asyncio.Event()
    _gates[phone] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return _replies.pop(phone, None)
    except asyncio.TimeoutError:
        return None
    finally:
        _gates.pop(phone, None)


def deliver_reply(phone: str, text: str) -> bool:
    """
    Called by the webhook handler when a text message arrives from `phone`.
    Returns True if a coroutine was waiting (CAPTCHA or OTP gate active),
    False if no one was waiting (message treated as normal conversation input).
    """
    if phone in _gates:
        _replies[phone] = text.strip()
        _gates[phone].set()
        return True
    return False


def is_waiting(phone: str) -> bool:
    """True if a booking coroutine is currently waiting on a reply from this phone."""
    return phone in _gates
