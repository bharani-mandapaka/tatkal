"""
Tests for the Admin HITL CAPTCHA adapter.

Pins three invariants:
  1. 2captcha is always tried first when an API key is configured.
  2. Admin HITL timeout is exactly 10 seconds — hardcoded, never configurable.
  3. CaptchaHITLTimeout is raised (not swallowed) when no reply arrives in time.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from whatsapp.captcha_admin_hitl import AdminHITLCaptchaAdapter, CaptchaHITLTimeout, HITL_TIMEOUT_S
from whatsapp import reply_gate

ADMIN_PHONE = "+919876543210"
FAKE_IMAGE = b"\x89PNG\r\n..."


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_adapter(api_key=None, send_image_fn=None):
    return AdminHITLCaptchaAdapter(
        admin_phone=ADMIN_PHONE,
        send_image_fn=send_image_fn or AsyncMock(),
        api_key=api_key,
    )


# ── 2captcha first-path ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_2captcha_used_first_when_key_configured():
    with patch("whatsapp.captcha_admin_hitl.TwoCaptchaAdapter") as MockTC:
        mock_instance = AsyncMock()
        mock_instance.solve.return_value = "AB4K2"
        MockTC.return_value = mock_instance

        adapter = _make_adapter(api_key="valid_key")
        result = await adapter.solve(FAKE_IMAGE)

    assert result == "AB4K2"
    MockTC.assert_called_once_with("valid_key")
    mock_instance.solve.assert_awaited_once_with(FAKE_IMAGE)


@pytest.mark.asyncio
async def test_2captcha_not_called_when_no_key():
    send_fn = AsyncMock()
    adapter = _make_adapter(api_key=None, send_image_fn=send_fn)

    # Simulate admin replying immediately
    async def _reply_quickly(*_):
        await asyncio.sleep(0.05)
        reply_gate.deliver_reply(ADMIN_PHONE, "XY9Z")

    asyncio.create_task(_reply_quickly())

    with patch("whatsapp.captcha_admin_hitl.TwoCaptchaAdapter") as MockTC:
        result = await adapter.solve(FAKE_IMAGE)
        MockTC.assert_not_called()

    assert result == "XY9Z"


@pytest.mark.asyncio
async def test_falls_back_to_hitl_when_2captcha_fails():
    send_fn = AsyncMock()

    with patch("whatsapp.captcha_admin_hitl.TwoCaptchaAdapter") as MockTC:
        mock_instance = AsyncMock()
        mock_instance.solve.side_effect = Exception("API error")
        MockTC.return_value = mock_instance

        adapter = _make_adapter(api_key="valid_key", send_image_fn=send_fn)

        async def _reply_quickly(*_):
            await asyncio.sleep(0.05)
            reply_gate.deliver_reply(ADMIN_PHONE, "fallback_answer")

        asyncio.create_task(_reply_quickly())
        result = await adapter.solve(FAKE_IMAGE)

    # send_image_fn was called → HITL path activated
    send_fn.assert_awaited_once()
    assert result == "fallback_answer"


# ── HITL timeout invariant ────────────────────────────────────────────────────

def test_hitl_timeout_constant_is_10():
    """This test exists to make any accidental change to HITL_TIMEOUT_S fail loudly."""
    assert HITL_TIMEOUT_S == 10, (
        f"HITL timeout must be 10s — got {HITL_TIMEOUT_S}. "
        "This is a product decision, not a config value. "
        "To change it, update this test deliberately."
    )


@pytest.mark.asyncio
async def test_timeout_raises_captcha_hitl_timeout():
    """No reply within 10s → CaptchaHITLTimeout raised, never swallowed."""
    send_fn = AsyncMock()
    adapter = _make_adapter(api_key=None, send_image_fn=send_fn)

    # Patch wait_for_reply to simulate instant timeout (don't actually wait 10s in tests)
    with patch("whatsapp.captcha_admin_hitl.wait_for_reply", return_value=None):
        with pytest.raises(CaptchaHITLTimeout):
            await adapter.solve(FAKE_IMAGE)


@pytest.mark.asyncio
async def test_image_sent_to_admin_phone_before_waiting():
    """send_image_fn must be called before wait_for_reply — admin needs image before clock starts."""
    call_order = []
    send_fn = AsyncMock(side_effect=lambda *_: call_order.append("send"))

    async def mock_wait(*_args, **_kwargs):
        call_order.append("wait")
        return "AB1C2"

    adapter = _make_adapter(api_key=None, send_image_fn=send_fn)

    with patch("whatsapp.captcha_admin_hitl.wait_for_reply", side_effect=mock_wait):
        await adapter.solve(FAKE_IMAGE)

    assert call_order == ["send", "wait"], "Image must be sent before waiting for reply"


@pytest.mark.asyncio
async def test_hitl_caption_mentions_10_seconds():
    """Caption sent with CAPTCHA image must state the 10-second window explicitly."""
    sent_captions = []

    async def capture_send(phone, img, caption):
        sent_captions.append(caption)

    adapter = _make_adapter(api_key=None, send_image_fn=capture_send)

    with patch("whatsapp.captcha_admin_hitl.wait_for_reply", return_value="SOLVED"):
        await adapter.solve(FAKE_IMAGE)

    assert sent_captions, "send_image_fn was not called"
    assert "10" in sent_captions[0], (
        f"Caption must mention '10 seconds'. Got: {sent_captions[0]!r}"
    )


# ── Reply gate integration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reply_gate_deliver_unblocks_waiting_coroutine():
    """Baseline: deliver_reply() correctly unblocks wait_for_reply()."""
    async def _deliver():
        await asyncio.sleep(0.05)
        reply_gate.deliver_reply(ADMIN_PHONE, "live_answer")

    asyncio.create_task(_deliver())
    result = await reply_gate.wait_for_reply(ADMIN_PHONE, timeout=5.0)
    assert result == "live_answer"


@pytest.mark.asyncio
async def test_reply_gate_returns_none_on_timeout():
    result = await reply_gate.wait_for_reply("+910000000000", timeout=0.05)
    assert result is None


def test_deliver_reply_returns_false_when_no_one_waiting():
    consumed = reply_gate.deliver_reply("+919999999999", "hello")
    assert consumed is False


def test_deliver_reply_returns_true_when_gate_active():
    phone = "+911234567890"
    event = asyncio.Event()
    reply_gate._gates[phone] = event  # manually open gate

    result = reply_gate.deliver_reply(phone, "text")

    assert result is True
    assert reply_gate._replies.get(phone) == "text"

    # cleanup
    reply_gate._gates.pop(phone, None)
    reply_gate._replies.pop(phone, None)
