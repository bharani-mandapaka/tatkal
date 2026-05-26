"""
Admin HITL CAPTCHA adapter.

Decision flow (hardcoded, not configurable — clarity over flexibility):

  1. If 2captcha API key is configured → try 2captcha (5–8s).
     On success: fill and continue. Done.
     On failure: fall through to step 2.

  2. Send CAPTCHA image to admin_phone via WhatsApp.
     Wait exactly 10 seconds for a text reply.
     On reply: fill and continue.
     On timeout: raise CaptchaHITLTimeout — booking FAILED, user notified.

The 10-second window is intentional and non-negotiable.
Operators must be watching their phone at the booking window.
"""

import asyncio
from dataclasses import dataclass

from adapters.captcha_twocaptcha import TwoCaptchaAdapter, TwoCaptchaError
from ports.captcha_port import CaptchaPort
from whatsapp.reply_gate import wait_for_reply
from logger import get_logger

log = get_logger()

HITL_TIMEOUT_S = 10  # hard limit — do not increase


class CaptchaHITLTimeout(Exception):
    """Raised when the admin does not reply within HITL_TIMEOUT_S seconds."""


@dataclass
class AdminHITLCaptchaAdapter(CaptchaPort):
    """
    Params:
        admin_phone:    WhatsApp number that receives the CAPTCHA image.
        send_image_fn:  Async callable(phone, image_bytes, caption) → None.
                        Injected to keep this class free of WhatsApp SDK imports.
        api_key:        Optional 2captcha API key. Tried first if present.
    """
    admin_phone: str
    send_image_fn: object          # async (phone: str, img: bytes, caption: str) -> None
    api_key: str | None = None

    async def solve(self, image_bytes: bytes) -> str:
        # ── Step 1: try 2captcha ─────────────────────────────────────────────
        if self.api_key:
            try:
                log.info("captcha_2captcha_attempt")
                text = await TwoCaptchaAdapter(self.api_key).solve(image_bytes)
                log.info("captcha_2captcha_solved")
                return text
            except (TwoCaptchaError, Exception) as e:
                log.warning("captcha_2captcha_failed", error=str(e),
                            fallback="admin_hitl")

        # ── Step 2: admin HITL — 10 seconds, no extensions ──────────────────
        log.info("captcha_hitl_start",
                 admin=self.admin_phone, timeout_s=HITL_TIMEOUT_S)

        await self.send_image_fn(
            self.admin_phone,
            image_bytes,
            f"⚠️ CAPTCHA — reply with the text *right now*. "
            f"You have *{HITL_TIMEOUT_S} seconds*.",
        )

        reply = await wait_for_reply(self.admin_phone, timeout=float(HITL_TIMEOUT_S))

        if reply is None:
            log.error("captcha_hitl_timeout", timeout_s=HITL_TIMEOUT_S)
            raise CaptchaHITLTimeout(
                f"Admin did not reply within {HITL_TIMEOUT_S}s"
            )

        log.info("captcha_hitl_solved", reply_length=len(reply))
        return reply
