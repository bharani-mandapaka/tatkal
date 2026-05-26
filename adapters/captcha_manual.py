from ports.captcha_port import CaptchaPort
from adapters.notifier import Notifier


class ManualCaptchaAdapter(CaptchaPort):
    def __init__(self, notifier: Notifier):
        self.notifier = notifier

    async def solve(self, image_bytes: bytes) -> str:
        self.notifier.alert("CAPTCHA — solve in the browser window now")
        print("\n  ┌─────────────────────────────────────────────┐")
        print("  │  CAPTCHA — solve in the browser window now  │")
        print("  │  The browser is in front. Type the CAPTCHA  │")
        print("  │  text, then press Enter here to continue.   │")
        print("  └─────────────────────────────────────────────┘")
        text = input("\n  CAPTCHA text: ").strip()
        return text
