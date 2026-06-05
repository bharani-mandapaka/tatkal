"""
File-based CAPTCHA adapter for non-interactive / automated runs.

Workflow:
  1. Saves the CAPTCHA image to  captcha_current.png  in the project root.
  2. Deletes any stale  captcha_answer.txt.
  3. Polls until  captcha_answer.txt  appears (max timeout_s seconds).
  4. Reads the answer from that file, deletes it, and returns it.

The caller (Claude / CI / operator) just needs to:
  - Look at  captcha_current.png  (via Read tool, file viewer, or screenshot)
  - Write the text to  captcha_answer.txt  (plain UTF-8, one line)
"""
import asyncio
from pathlib import Path

from ports.captcha_port import CaptchaPort
from adapters.notifier import Notifier

_HERE = Path(__file__).resolve().parent.parent   # project root

IMAGE_PATH  = _HERE / "captcha_current.png"
ANSWER_PATH = _HERE / "captcha_answer.txt"


class FileCaptchaAdapter(CaptchaPort):
    def __init__(self, notifier: Notifier, timeout_s: int = 120):
        self.notifier  = notifier
        self.timeout_s = timeout_s

    async def solve(self, image_bytes: bytes) -> str:
        # Save image so it can be inspected externally
        IMAGE_PATH.write_bytes(image_bytes)
        ANSWER_PATH.unlink(missing_ok=True)

        print(f"\n  [CAPTCHA] Image saved to: {IMAGE_PATH}")
        print(f"  [CAPTCHA] Write your answer to: {ANSWER_PATH}")
        print(f"  [CAPTCHA] Waiting up to {self.timeout_s}s for answer...\n")

        self.notifier.alert("CAPTCHA required — check captcha_current.png")

        deadline = asyncio.get_event_loop().time() + self.timeout_s
        while asyncio.get_event_loop().time() < deadline:
            if ANSWER_PATH.exists():
                text = ANSWER_PATH.read_text(encoding="utf-8").strip()
                ANSWER_PATH.unlink(missing_ok=True)
                print(f"  [CAPTCHA] Answer received: {text!r}")
                return text
            await asyncio.sleep(0.2)

        raise TimeoutError(
            f"CAPTCHA not solved within {self.timeout_s}s — "
            f"write the answer to {ANSWER_PATH} and retry"
        )
