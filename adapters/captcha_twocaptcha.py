import asyncio
import base64
import random

import httpx

from ports.captcha_port import CaptchaPort
from logger import get_logger

log = get_logger()

SUBMIT_URL = "https://2captcha.com/in.php"
RESULT_URL = "https://2captcha.com/res.php"


class TwoCaptchaError(Exception):
    pass


class TwoCaptchaAdapter(CaptchaPort):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def solve(self, image_bytes: bytes) -> str:
        return await self._solve_with_retry(image_bytes)

    async def _solve_with_retry(self, image_bytes: bytes) -> str:
        for attempt in range(1, 4):
            try:
                async with asyncio.timeout(35):
                    return await self._call_api(image_bytes)
            except (asyncio.TimeoutError, TwoCaptchaError) as e:
                if attempt == 3:
                    raise
                wait = 2 ** attempt + random.uniform(0, 1)
                log.warning("captcha_retry", attempt=attempt, error=str(e), wait_s=f"{wait:.1f}")
                await asyncio.sleep(wait)
        raise TwoCaptchaError("unreachable")

    async def _call_api(self, image_bytes: bytes) -> str:
        img_b64 = base64.b64encode(image_bytes).decode()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                SUBMIT_URL,
                data={"key": self.api_key, "method": "base64", "body": img_b64, "json": 1},
            )
            data = resp.json()
            if data.get("status") != 1:
                raise TwoCaptchaError(f"Submission error: {data.get('request')}")

            captcha_id = data["request"]
            log.info("captcha_submitted", captcha_id=captcha_id)

            for _ in range(20):
                await asyncio.sleep(3)
                poll = await client.get(
                    RESULT_URL,
                    params={"key": self.api_key, "action": "get", "id": captcha_id, "json": 1},
                )
                result = poll.json()
                if result.get("status") == 1:
                    log.info("captcha_result_received")
                    return result["request"]
                if result.get("request") != "CAPCHA_NOT_READY":
                    raise TwoCaptchaError(f"API error: {result.get('request')}")

        raise TwoCaptchaError("No answer after 60s of polling")
