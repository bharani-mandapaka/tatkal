"""
Playwright implementation of BrowserPort.

IRCTC is a React SPA — selectors here reflect the site as of mid-2025.
If IRCTC updates their DOM, adjust the selectors in each method below.
Run integration tests (tests/test_integration.py) against General quota
off-peak to verify before a live Tatkal run.
"""
import asyncio
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from ports.browser_port import BrowserPort, TrainInfo
from core.models import BookingConfig
from logger import get_logger

log = get_logger()

IRCTC_HOME = "https://www.irctc.co.in/nget/train-search"
COOKIE_PATH = Path("session.json")

# Human-like typing delay range (ms)
_TYPE_DELAY = 40


class PlaywrightBrowser(BrowserPort):
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def page(self) -> Page:
        assert self._page is not None, "Browser not launched — call launch() first"
        return self._page

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def launch(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        if COOKIE_PATH.exists():
            try:
                cookies = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
                await self._context.add_cookies(cookies)
                log.info("session_cookies_loaded", path=str(COOKIE_PATH))
            except Exception as e:
                log.warning("session_cookie_load_failed", error=str(e))

        self._page = await self._context.new_page()
        log.info("browser_launched")

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("browser_closed")

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self, username: str, password: str) -> bool:
        # "networkidle" never fires on IRCTC (persistent WebSocket keep-alives).
        # "load" waits for window.onload — reliable and fast.
        await self.page.goto(IRCTC_HOME, wait_until="load")
        await asyncio.sleep(2)   # React hydration

        # If session cookies are still valid, skip the full login flow entirely
        if await self.is_logged_in():
            log.info("login_session_reused", username=username)
            return True

        # Close any modal/popup if present
        try:
            close_btn = self.page.locator(".modal-close, button.close").first
            if await close_btn.is_visible():
                await close_btn.click()
                await asyncio.sleep(0.3)
        except Exception:
            pass

        # Click the LOGIN link
        await self.page.locator("a.search_btn.loginText, a:has-text('LOGIN')").first.click()
        await self.page.wait_for_selector("input[formcontrolname='userid']", timeout=10_000)

        # Username
        user_input = self.page.locator("input[formcontrolname='userid']")
        await user_input.click()
        await user_input.fill("")
        await self.page.keyboard.type(username, delay=_TYPE_DELAY)
        await asyncio.sleep(0.3)

        # Password
        pwd_input = self.page.locator("input[formcontrolname='password']")
        await pwd_input.click()
        await pwd_input.fill("")
        await self.page.keyboard.type(password, delay=_TYPE_DELAY)
        await asyncio.sleep(0.3)

        # IRCTC login page also has a CAPTCHA — handled manually for now
        login_captcha = self.page.locator("app-captcha, img.captcha-img")
        if await login_captcha.count() > 0:
            print("\n  ── Login CAPTCHA ──────────────────────────────────────")
            print("  Solve the login CAPTCHA in the browser, then press Enter.")
            input("  Press Enter after solving: ")

        await self.page.locator("button[type='submit']:has-text('SIGN IN'), button:has-text('Login')").first.click()

        try:
            # Wait for the user dashboard indicator
            await self.page.wait_for_selector(
                ".user-name-text, a:has-text('MY ACCOUNT')", timeout=20_000
            )
            # Persist session cookies
            cookies = await self._context.cookies()
            COOKIE_PATH.write_text(json.dumps(cookies), encoding="utf-8")
            log.info("login_success", username=username)
            return True
        except Exception as e:
            log.error("login_failed", error=str(e))
            return False

    async def is_logged_in(self) -> bool:
        try:
            el = self.page.locator(".user-name-text, a:has-text('MY ACCOUNT')")
            return await el.count() > 0
        except Exception:
            return False

    # ── Navigation & form ─────────────────────────────────────────────────────

    async def navigate_to_booking(self) -> None:
        await self.page.goto(IRCTC_HOME, wait_until="load")
        await asyncio.sleep(0.5)

    async def prefill_search_form(self, config: BookingConfig) -> None:
        # Wait for Angular/PrimeNG to fully hydrate before touching anything
        await self.page.wait_for_selector(
            "p-autocomplete[formcontrolname='origin']", timeout=15_000
        )

        async def fill_station(formcontrol: str, code: str) -> None:
            # PrimeNG autocomplete: the <input> sits inside
            # <p-autocomplete formcontrolname="origin|destination">
            inp = self.page.locator(
                f"p-autocomplete[formcontrolname='{formcontrol}'] input"
            )
            await inp.click()
            await inp.fill(code)
            await asyncio.sleep(0.7)   # allow suggestion list to appear
            suggestion = self.page.locator("li.ui-autocomplete-list-item").first
            await suggestion.wait_for(timeout=8_000)
            await suggestion.click()
            await asyncio.sleep(0.3)

        await fill_station("origin", config.from_station)
        await fill_station("destination", config.to_station)

        # Journey date — PrimeNG calendar uses DD/MM/YYYY (not DD-MM-YYYY)
        journey_date_fmt = config.journey_date.replace("-", "/")  # 27-05-2026 → 27/05/2026
        date_input = self.page.locator("p-calendar[formcontrolname='journeyDate'] input")
        await date_input.click(click_count=3)    # select all existing text
        await date_input.fill(journey_date_fmt)
        await self.page.keyboard.press("Tab")
        await asyncio.sleep(0.3)

        # Travel class dropdown (formcontrolname confirmed in DOM)
        class_dd = self.page.locator("p-dropdown[formcontrolname='journeyClass']")
        await class_dd.click()
        await self.page.locator(
            f"li.ui-dropdown-item:has-text('{config.travel_class.value}')"
        ).click()
        await asyncio.sleep(0.3)

        # Quota — configurable (TATKAL / GENERAL / PREMIUM TATKAL / etc.)
        quota_dd = self.page.locator("p-dropdown[formcontrolname='journeyQuota']")
        await quota_dd.click()
        await self.page.locator(
            f"li.ui-dropdown-item:has-text('{config.quota}')"
        ).click()
        await asyncio.sleep(0.3)

        log.info("form_prefilled",
                 from_=config.from_station, to=config.to_station,
                 date=journey_date_fmt, cls=config.travel_class.value,
                 quota=config.quota)

    async def search_trains(self) -> None:
        await self.page.locator(
            "button:has-text('Search'), button.search_btn"
        ).first.click()
        await self.page.wait_for_selector(
            "app-train-avl-enq, .train-heading", timeout=20_000
        )
        log.info("train_list_loaded")

    # ── Train selection ───────────────────────────────────────────────────────

    async def find_and_select_train(self, train_number: str, travel_class: str) -> TrainInfo:
        await self.page.wait_for_selector(".train-heading", timeout=15_000)

        # Locate the row for the target train
        train_row = self.page.locator(f".train-heading:has-text('{train_number}')").first
        if await train_row.count() == 0:
            raise RuntimeError(
                f"Train {train_number} not found. "
                "Check the train number, date, and quota in your config."
            )

        train_name = (await train_row.text_content() or "").strip()

        # The availability cell for the requested class
        row_container = train_row.locator("xpath=ancestor::div[contains(@class,'train-avl')]").first
        class_cell = row_container.locator(
            f"td:has-text('{travel_class}'), div:has-text('{travel_class}')"
        ).first
        avail_text = (await class_cell.text_content() or "UNKNOWN").strip()

        log.info("train_found",
                 train=train_number, cls=travel_class, availability=avail_text)

        # NO abort window here — every millisecond counts at the Tatkal window
        print(f"  ✓ {train_number} · {travel_class} · {avail_text} — booking now")

        await class_cell.click()
        await asyncio.sleep(0.5)

        book_btn = self.page.locator("button:has-text('Book Now')").first
        await book_btn.wait_for(timeout=8_000)
        await book_btn.click()

        return TrainInfo(
            train_number=train_number,
            train_name=train_name,
            availability=avail_text,
        )

    # ── Passenger form ────────────────────────────────────────────────────────

    async def fill_passenger_details(self, config: BookingConfig) -> None:
        await self.page.wait_for_selector(
            ".passenger-detail, app-passenger-info", timeout=15_000
        )

        # ── Post-window phase: ZERO artificial delays ────────────────────────
        # Every asyncio.sleep here is removed — Playwright awaits DOM events,
        # not fixed timers. Use asyncio.sleep(0.05) ONLY if a React dropdown
        # needs a tick to render its option list after being clicked.
        for i, pax in enumerate(config.passengers):
            n = i + 1  # 1-based index used in IRCTC IDs

            await self.page.fill(f"#passengerName{n}, input[id='name_{n}']", pax.name)
            await self.page.fill(f"#passengerAge{n}, input[id='age_{n}']", str(pax.age))

            # Gender dropdown
            gender_dd = self.page.locator(
                f"p-dropdown[id='passengerGender{n}'], select[id='gender_{n}']"
            )
            await gender_dd.click()
            await asyncio.sleep(0.05)   # React tick — dropdown renders options
            await self.page.locator(
                f"li.ui-dropdown-item:has-text('{pax.gender.value}')"
            ).first.click()

            # Berth preference dropdown
            berth_dd = self.page.locator(
                f"p-dropdown[id='passengerBerthChoice{n}'], select[id='berth_{n}']"
            )
            await berth_dd.click()
            await asyncio.sleep(0.05)
            await self.page.locator(
                f"li.ui-dropdown-item:has-text('{pax.berth_preference.value}')"
            ).first.click()

            # ID type (Tatkal mandatory)
            id_type_dd = self.page.locator(
                f"p-dropdown[id='passengerIdType{n}'], select[id='idType_{n}']"
            )
            await id_type_dd.click()
            await asyncio.sleep(0.05)
            await self.page.locator(
                f"li.ui-dropdown-item:has-text('{pax.id_type.value}')"
            ).first.click()

            await self.page.fill(
                f"#passengerIdNumber{n}, input[id='idNumber_{n}']", pax.id_number
            )

        # Mobile number
        mobile_inp = self.page.locator("#mobileNumber, input[formcontrolname='mobileNumber']")
        if await mobile_inp.count() > 0:
            await mobile_inp.fill(config.mobile)

        # "Book only if confirmed" checkbox
        if config.book_only_if_confirmed:
            cb = self.page.locator(
                "input[type='checkbox'][id*='confirm'], p-checkbox[formcontrolname='confirmBerths']"
            ).first
            if await cb.count() > 0 and not await cb.is_checked():
                await cb.click()

        log.info("passengers_filled", count=len(config.passengers))

    # ── CAPTCHA ───────────────────────────────────────────────────────────────

    async def get_captcha_image(self) -> bytes:
        captcha_el = self.page.locator("img.captcha-img, app-captcha img").first
        await captcha_el.wait_for(timeout=10_000)
        return await captcha_el.screenshot()

    async def fill_captcha(self, text: str) -> None:
        inp = self.page.locator(
            "input[id='captcha'], input[formcontrolname='captcha']"
        ).first
        await inp.fill(text)
        await asyncio.sleep(0.3)

    # ── Submit & confirmation ─────────────────────────────────────────────────

    async def submit_passenger_form(self) -> None:
        await self.page.locator("button:has-text('Next')").first.click()
        await self.page.wait_for_url("**/payment**", timeout=30_000)
        log.info("passenger_form_submitted")

    async def get_booking_confirmation(self) -> dict:
        await self.page.wait_for_url("**/bookingConfirm**", timeout=300_000)
        pnr = ""
        pnr_el = self.page.locator(".pnr-no, .pnr-number, span:has-text('PNR')").first
        if await pnr_el.count() > 0:
            pnr = (await pnr_el.text_content() or "").strip()
        return {"pnr": pnr}

    async def screenshot(self, path: str) -> None:
        await self.page.screenshot(path=path, full_page=True)
        log.info("screenshot_saved", path=path)
