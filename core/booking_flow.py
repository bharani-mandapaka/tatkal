import asyncio
from datetime import datetime
from typing import Optional

from core.models import BookingConfig
from core.state_machine import BookingState
from ports.browser_port import BrowserPort
from ports.captcha_port import CaptchaPort
from adapters.notifier import Notifier
from logger import get_logger

log = get_logger()


def _elapsed_ms(start: datetime) -> int:
    return int((datetime.now() - start).total_seconds() * 1000)


def _fmt_elapsed(ms: int) -> str:
    if ms >= 60_000:
        return f"{ms // 60000}m {(ms % 60000) // 1000}s"
    return f"{ms // 1000}s"


class BookingFlow:
    def __init__(
        self,
        browser: BrowserPort,
        captcha: CaptchaPort,
        captcha_fallback: Optional[CaptchaPort],
        notifier: Notifier,
        dry_run: bool = False,
    ):
        self.browser = browser
        self.captcha = captcha
        self.captcha_fallback = captcha_fallback
        self.notifier = notifier
        self.dry_run = dry_run
        self.state = BookingState.IDLE
        self._window_start: Optional[datetime] = None

    def _transition(self, new_state: BookingState, **ctx) -> None:
        log.info("state", from_=self.state.name, to=new_state.name, **ctx)
        self.state = new_state

    async def run(self, config: BookingConfig, window_time: datetime) -> dict:
        try:
            return await self._execute(config, window_time)
        except Exception as e:
            self._transition(BookingState.FAILED, error=str(e))
            self.notifier.notify(
                "Tatkal Agent — FAILED",
                f"Error at {self.state.name}: {e}",
            )
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] FAILED: {e}")
            print(f"  State at failure: {self.state.name}")
            print("  Nothing was booked. No payment was taken.\n")
            raise

    async def _execute(self, config: BookingConfig, window_time: datetime) -> dict:
        # ── Login ──────────────────────────────────────────────────────────────
        self._transition(BookingState.LOGGING_IN)
        success = await self.browser.login(config.username, config.password)
        if not success:
            raise RuntimeError("Login failed — check credentials or solve login CAPTCHA")

        # ── Pre-fill form ──────────────────────────────────────────────────────
        self._transition(BookingState.PREFILLING_FORM)
        await self.browser.navigate_to_booking()
        await self.browser.prefill_search_form(config)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Journey details pre-filled. "
              f"Waiting for {window_time.strftime('%H:%M:%S')}...")

        # ── Wait for window ────────────────────────────────────────────────────
        self._transition(BookingState.WAITING_FOR_WINDOW)
        await _countdown(window_time)
        self._window_start = datetime.now()

        # ── Search ─────────────────────────────────────────────────────────────
        self._transition(BookingState.SEARCHING)
        await self.browser.search_trains()

        # ── Select train ───────────────────────────────────────────────────────
        self._transition(BookingState.SELECTING_TRAIN)
        train_info = await self.browser.find_and_select_train(
            config.train_number, config.travel_class.value
        )
        log.info("train_selected",
                 train=train_info.train_number,
                 avail=train_info.availability,
                 elapsed_ms=_elapsed_ms(self._window_start))

        # ── Fill passengers ────────────────────────────────────────────────────
        self._transition(BookingState.FILLING_PASSENGERS)
        await self.browser.fill_passenger_details(config)

        # ── Solve CAPTCHA ──────────────────────────────────────────────────────
        self._transition(BookingState.SOLVING_CAPTCHA)
        await self._solve_captcha()

        # ── Submit form ────────────────────────────────────────────────────────
        self._transition(BookingState.SUBMITTING)
        await self.browser.submit_passenger_form()

        # ── Payment ────────────────────────────────────────────────────────────
        self._transition(BookingState.PAYING)

        if self.dry_run:
            elapsed = _elapsed_ms(self._window_start) if self._window_start else 0
            print()
            print("  " + "-" * 53)
            print("  [OK] DRY RUN COMPLETE -- payment page reached")
            print(f"  Elapsed from window open: {_fmt_elapsed(elapsed)}")
            print("  Browser is open -- inspect, then press Enter to close.")
            print("  " + "-" * 53)
            print()
            input("  Press Enter to close the browser: ")
            return {"dry_run": True, "reached": "payment_page", "elapsed_ms": elapsed}

        from payment import handle_payment
        await handle_payment(self.browser.page, config.payment, self.notifier)

        # ── Confirmation ───────────────────────────────────────────────────────
        self._transition(BookingState.CONFIRMED)
        result = await self.browser.get_booking_confirmation()
        pnr = result.get("pnr", "UNKNOWN")
        elapsed = _elapsed_ms(self._window_start)
        screenshot = f"confirmation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await self.browser.screenshot(screenshot)

        self.notifier.notify("Tatkal Agent — CONFIRMED", f"PNR: {pnr}")
        _print_success(pnr, config, elapsed, screenshot)

        return {
            "pnr": pnr,
            "train": config.train_number,
            "class": config.travel_class.value,
            "passengers": len(config.passengers),
            "booking_time_ms": elapsed,
            "payment_method": config.payment.method.value if config.payment else "UNKNOWN",
            "screenshot": screenshot,
        }

    async def _solve_captcha(self) -> None:
        image_bytes = await self.browser.get_captcha_image()
        try:
            log.info("captcha_solving", solver=type(self.captcha).__name__)
            text = await self.captcha.solve(image_bytes)
            await self.browser.fill_captcha(text)
            log.info("captcha_solved")
        except Exception as e:
            log.warning("captcha_primary_failed", error=str(e))
            if self.captcha_fallback:
                log.info("captcha_fallback", solver=type(self.captcha_fallback).__name__)
                text = await self.captcha_fallback.solve(image_bytes)
                await self.browser.fill_captcha(text)
            else:
                raise


async def _countdown(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            print()
            return
        if remaining <= 5:
            print(
                f"\r  [{datetime.now().strftime('%H:%M:%S')}]"
                f" ──── {remaining:.1f} seconds ────",
                end="", flush=True,
            )
            await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(min(remaining - 5, 30))


def _print_success(pnr: str, config: BookingConfig, elapsed_ms: int, screenshot: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    elapsed_str = _fmt_elapsed(elapsed_ms)
    print(f"""
[{now}] ✅ BOOKING CONFIRMED

  PNR              {pnr}
  Train            {config.train_number} · {config.from_station} → {config.to_station}
  Date             {config.journey_date}
  Class            {config.travel_class.value} (Tatkal)
  Passengers       {len(config.passengers)}
  Booked in        {elapsed_str} from window open

  Screenshot saved → {screenshot}
  Full log saved   → session_{datetime.now().strftime('%Y%m%d')}.log

[Desktop notification sent]
""")
