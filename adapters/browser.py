"""
Playwright implementation of BrowserPort.

IRCTC is an Angular SPA — selectors here reflect the site as of mid-2025.
If IRCTC updates their DOM, adjust the selectors in each method below.
Verify off-peak in GENERAL quota with `python run_auto.py` (dry run, stops at
the payment page) before any live Tatkal run.
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


def _mask(s: str) -> str:
    """Redact a credential for logging — keep enough to confirm identity in
    diagnostics without exposing it in console output / pasted logs."""
    if not s:
        return ""
    return s[0] + "***" if len(s) <= 4 else s[:2] + "***" + s[-1]


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

    async def _dismiss_welcome_modal(self) -> None:
        """
        On a fresh session IRCTC shows a Welcome modal combining a Tatkal/Aadhaar
        alert ("Authenticate now") with a language choice (हिंदी / English).
        Click 'English' to proceed — NEVER 'Authenticate now' (that starts the
        Aadhaar flow). Falls back to a generic close button. Safe no-op if absent.
        """
        try:
            english = self.page.locator(
                "button:has-text('English'), a:has-text('English'), "
                ".btn:has-text('English'), [class*='lang']:has-text('English')"
            ).first
            if await english.count() > 0 and await english.is_visible(timeout=2_000):
                await english.click()
                log.info("welcome_modal_english_selected")
                await asyncio.sleep(0.5)
                return
        except Exception as e:
            log.debug("welcome_modal_english_skip", note=str(e)[:60])

        # Generic close fallback for any promo/alert modal still showing.
        try:
            close_btn = self.page.locator(
                ".modal-close, button.close, .ui-dialog-titlebar-close, "
                "button[aria-label='Close']"
            ).first
            if await close_btn.count() > 0 and await close_btn.is_visible():
                await close_btn.click()
                log.info("welcome_modal_closed_generic")
                await asyncio.sleep(0.3)
        except Exception:
            pass

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self, username: str, password: str) -> bool:
        # "networkidle" never fires on IRCTC (persistent WebSocket keep-alives).
        # "load" waits for window.onload — reliable and fast.
        await self.page.goto(IRCTC_HOME, wait_until="load")
        await asyncio.sleep(2)   # React hydration

        # Fresh sessions show a Welcome modal (Aadhaar alert + language choice).
        # Pick English and dismiss it before anything else.
        await self._dismiss_welcome_modal()

        # If session cookies are still valid, skip the full login flow entirely
        if await self.is_logged_in():
            log.info("login_session_reused", username=_mask(username))
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

        # IRCTC login page has a CAPTCHA — wait for it then prompt user.
        # We check BEFORE and AFTER clicking Sign In because IRCTC sometimes
        # renders the CAPTCHA only after credentials are entered.
        _captcha_sel = (
            "app-captcha, "
            "#captchaImage, #captchaImg, "
            "img.captcha-img, "
            "img[src*='captcha' i], "
            "img[alt*='captcha' i], "
            "[class*='captcha' i] img, "
            "input[formcontrolname*='captcha' i], "
            "input[placeholder*='captcha' i]"
        )
        await asyncio.sleep(1)   # give Angular time to render CAPTCHA widget
        if await self.page.locator(_captcha_sel).count() > 0:
            print("\n  ── Login CAPTCHA ──────────────────────────────────────")
            print("  Solve the login CAPTCHA in the browser, then press Enter.")
            input("  Press Enter after solving the captcha: ")

        await self.page.locator("button[type='submit']:has-text('SIGN IN'), button:has-text('Login')").first.click()

        try:
            # Wait for the user dashboard indicator
            await self.page.wait_for_selector(
                ".user-name-text, a:has-text('MY ACCOUNT')", timeout=20_000
            )

            # VERIFY login was real, not a transient/false-positive element.
            # On a real login, the indicator stays visible.  On a CAPTCHA
            # rejection the page may briefly show a dashboard-shaped element
            # then redirect back to logged-out.  Re-check after 2 s to be sure.
            await asyncio.sleep(2)
            verify = await self.page.evaluate(
                """() => {
                    const allLinks = Array.from(
                        document.querySelectorAll('a, button')
                    );
                    return {
                        hasLoginLink: allLinks.some(
                            e => /\\bLOGIN\\s*\\/\\s*REGISTER\\b/i.test(e.textContent)
                                  || /\\bLOGIN\\b/i.test((e.textContent||'').trim())
                                     && (e.textContent||'').trim().length < 25
                        ),
                        userElCount: document.querySelectorAll(
                            '.user-name-text, a[href*="profile"]'
                        ).length,
                        url: location.href,
                    };
                }"""
            )
            try:
                await self.page.screenshot(path="step_after_login.png")
            except Exception:
                pass
            if verify.get("hasLoginLink") and verify.get("userElCount", 0) == 0:
                # The 'logged in' indicator was a false positive — page
                # is actually still showing LOGIN/REGISTER.  CAPTCHA most
                # likely was not solved.
                log.warning(
                    "login_false_positive",
                    note="login_success element appeared but page is still logged out",
                    url=verify.get("url"),
                )
                return False

            # Persist session cookies
            cookies = await self._context.cookies()
            COOKIE_PATH.write_text(json.dumps(cookies), encoding="utf-8")
            log.info("login_success", username=_mask(username), verified=True)
            return True
        except Exception as e:
            # Login timed out — IRCTC may have shown a CAPTCHA after submit.
            # Give the user a chance to solve it and retry Sign In once.
            log.warning("login_wait_timeout", error=str(e))
            try:
                await self.page.screenshot(path="step_login_timeout.png")
            except Exception:
                pass
            if await self.page.locator(_captcha_sel).count() > 0:
                print("\n  ── Login CAPTCHA (appeared after submit) ──────────────")
                print("  Solve the CAPTCHA in the browser, then press Enter.")
                input("  Press Enter after solving the captcha: ")
                await self.page.locator(
                    "button[type='submit']:has-text('SIGN IN'), button:has-text('Login')"
                ).first.click()
                try:
                    await self.page.wait_for_selector(
                        ".user-name-text, a:has-text('MY ACCOUNT')", timeout=20_000
                    )
                    cookies = await self._context.cookies()
                    COOKIE_PATH.write_text(json.dumps(cookies), encoding="utf-8")
                    log.info("login_success", username=_mask(username), verified=True,
                             note="captcha_retry")
                    return True
                except Exception as e2:
                    log.error("login_failed_after_captcha_retry", error=str(e2))
            else:
                log.error("login_failed", error=str(e))
            return False

    async def is_logged_in(self) -> bool:
        # Retry up to 12× with 0.5 s backoff (6 s total).  Angular mid-render
        # can briefly remove .user-name-text after a dropdown / form
        # interaction, which previously caused a false 'session expired'
        # reading at T=0 when the booking-window countdown fired immediately
        # (dry-run mode).  6 s is still invisible during a 3-min real-Tatkal
        # countdown but eliminates the false-negative.
        selectors = (
            ".user-name-text, "
            "a:has-text('MY ACCOUNT'), "
            "a:has-text('Welcome'), "
            ".welcome-text, "
            "[class*='user-name']"
        )
        for _ in range(12):
            try:
                if await self.page.locator(selectors).count() > 0:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)

        # Returned False — dump diagnostic info so we know WHY the page
        # didn't look logged in.
        try:
            diag = await self.page.evaluate(
                """() => {
                    const txt = e => (e && e.textContent ? e.textContent.trim() : '');
                    const userEl = document.querySelector(
                        '.user-name-text, [class*="user-name"], .welcome-text, '
                        + '[class*="welcome"]'
                    );
                    const header = document.querySelector('app-header, header, .navbar');
                    const allLinks = Array.from(
                        document.querySelectorAll('a, button')
                    );
                    return {
                        url: location.href,
                        title: document.title,
                        hasLoginForm: !!document.querySelector(
                            'input[placeholder*="User"], input[type="password"]'
                        ),
                        hasLoginLink: allLinks.some(
                            e => /\\blogin\\b/i.test(txt(e))
                        ),
                        hasLogoutLink: allLinks.some(
                            e => /\\blogout\\b/i.test(txt(e))
                        ),
                        userElText: txt(userEl).slice(0, 80) || null,
                        headerSnippet: txt(header).slice(0, 300) || null,
                        bodyClass: document.body.className.slice(0, 100)
                    };
                }"""
            )
            log.warning("is_logged_in_false_diag", **diag)
            print(f"  [diag] is_logged_in=False:")
            for k, v in diag.items():
                print(f"    {k}: {v}")
            try:
                await self.page.screenshot(path="step_is_logged_in_false.png")
                print("  [snap] step_is_logged_in_false.png")
            except Exception:
                pass
        except Exception as exc:
            log.warning("is_logged_in_diag_failed", error=str(exc))
        return False

    # ── Navigation & form ─────────────────────────────────────────────────────

    async def navigate_to_booking(self) -> None:
        pre_url = self.page.url
        pre_logged = await self.page.locator(
            ".user-name-text, a:has-text('MY ACCOUNT')"
        ).count() > 0
        print(f"  [navigate_to_booking] pre: url={pre_url} logged_in={pre_logged}")
        log.info("navigate_to_booking_pre", url=pre_url, logged_in=pre_logged)

        # If we are already on the booking page with a live session, do NOT
        # refresh — page.goto() does a hard reload that clears IRCTC's
        # Angular in-memory session state and silently logs the user out
        # (cookies are kept but the navbar reverts to LOGIN/REGISTER).
        if pre_url.startswith(IRCTC_HOME) and pre_logged:
            log.info("navigate_to_booking_skip",
                     reason="already_on_page_with_live_session")
            print("  [navigate_to_booking] skip: already on page, session live")
            return

        await self.page.goto(IRCTC_HOME, wait_until="load")
        await asyncio.sleep(0.5)

        post_url = self.page.url
        post_logged = await self.page.locator(
            ".user-name-text, a:has-text('MY ACCOUNT')"
        ).count() > 0
        print(f"  [navigate_to_booking] post: url={post_url} logged_in={post_logged}")
        log.info("navigate_to_booking_post", url=post_url, logged_in=post_logged)

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

        # Journey date — PrimeNG calendar uses DD/MM/YYYY (not DD-MM-YYYY).
        # fill() bypasses Angular's keyboard listeners and doesn't update the model.
        # We must fire real key events: click to focus+open calendar, Ctrl+A to
        # select all, then type() each character so Angular sees keydown/input events.
        journey_date_fmt = config.journey_date.replace("-", "/")  # 27-05-2026 → 27/05/2026

        async def fill_date() -> None:
            date_input = self.page.locator("p-calendar[formcontrolname='journeyDate'] input")
            await date_input.click()
            await asyncio.sleep(0.3)
            await date_input.press("Control+a")
            await self.page.keyboard.type(journey_date_fmt, delay=80)
            await asyncio.sleep(0.5)
            await self.page.keyboard.press("Tab")    # commit + close calendar popup
            await asyncio.sleep(0.5)

        await fill_date()

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

        # ── Verify the form actually committed (anti-flake) ──────────────────
        # IRCTC's "Search Trains" only navigates if Angular's reactive form is
        # valid. Filling the DOM doesn't guarantee the model updated — there's a
        # race between fill() and Angular change detection. Read each field back
        # and re-fill any that didn't stick. This was the root cause of search
        # intermittently no-op'ing (page stayed on /train-search).
        for _ in range(2):
            rb = await self.page.evaluate("""() => {
                const v = sel => { const e = document.querySelector(sel);
                    return e ? (e.value || '').trim() : ''; };
                return {
                    origin: v("p-autocomplete[formcontrolname='origin'] input"),
                    dest:   v("p-autocomplete[formcontrolname='destination'] input"),
                    date:   v("p-calendar[formcontrolname='journeyDate'] input"),
                };
            }""")
            missing = [k for k in ("origin", "dest", "date") if not rb.get(k)]
            if not missing:
                break
            log.warning("prefill_incomplete_refilling", missing=str(missing))
            if "origin" in missing:
                await fill_station("origin", config.from_station)
            if "dest" in missing:
                await fill_station("destination", config.to_station)
            if "date" in missing:
                await fill_date()

        log.info("form_prefilled",
                 from_=config.from_station, to=config.to_station,
                 date=journey_date_fmt, cls=config.travel_class.value,
                 quota=config.quota)

    async def search_trains(self) -> None:
        # DIAG: confirm the form actually registered values, and inspect the
        # Search button(s) before clicking. Pins "form invalid" vs "wrong button".
        try:
            pre = await self.page.evaluate("""() => {
                const v = sel => { const e = document.querySelector(sel);
                    return e ? (e.value || e.textContent || '').trim()
                        .replace(/[^\\x00-\\x7F]/g,'').slice(0,40) : '<none>'; };
                const btns = Array.from(document.querySelectorAll('button'))
                    .map(b => ({t:(b.textContent||'').trim().replace(/[^\\x00-\\x7F]/g,'').slice(0,22),
                                d:b.disabled}))
                    .filter(b => /search/i.test(b.t));
                return {
                    origin: v("p-autocomplete[formcontrolname='origin'] input"),
                    dest:   v("p-autocomplete[formcontrolname='destination'] input"),
                    date:   v("p-calendar[formcontrolname='journeyDate'] input"),
                    cls:    v("p-dropdown[formcontrolname='journeyClass']"),
                    quota:  v("p-dropdown[formcontrolname='journeyQuota']"),
                    searchButtons: btns,
                };
            }""")
            print(f"  [prefill-check] origin={pre.get('origin')!r} dest={pre.get('dest')!r} "
                  f"date={pre.get('date')!r} cls={pre.get('cls')!r} quota={pre.get('quota')!r}")
            print(f"  [prefill-check] searchButtons={pre.get('searchButtons')}")
            log.info("prefill_check", **{k: str(v)[:80] for k, v in pre.items()})
        except Exception as e:
            print(f"  [prefill-check failed] {e}")

        # Click Search and verify navigation to results. The form-fill and the
        # click can race Angular's change detection, so the first click
        # sometimes no-ops (page stays on /train-search). Re-click once if the
        # results container doesn't attach. state="attached" avoids the
        # false-negative that state="visible" triggers (the Angular host element
        # has 0 height until results hydrate).
        search_btn = self.page.locator(
            "button:has-text('Search Trains'), button.search_btn, button:has-text('Search')"
        ).first
        for attempt in range(1, 3):
            await search_btn.click()
            try:
                await self.page.wait_for_selector(
                    "app-train-avl-enq", timeout=20_000, state="attached"
                )
                await asyncio.sleep(3)   # let train rows fully render
                log.info("train_list_loaded", attempt=attempt)
                return
            except Exception:
                if attempt < 2:
                    log.warning("search_no_nav_retrying",
                                attempt=attempt, url=self.page.url)
                    await asyncio.sleep(2)
                    continue
                # Second miss — capture diagnostics and fail.
                try:
                    await self.page.screenshot(path="step_search_timeout.png", full_page=True)
                    print("  [snap] step_search_timeout.png")
                except Exception:
                    pass
                try:
                    diag = await self.page.evaluate("""() => {
                        const counts = {};
                        ['app-train-avl-enq','app-train-list','.train-list',
                         '[class*=\"train\"]'].forEach(s =>
                            counts[s] = document.querySelectorAll(s).length);
                        return {url: location.href, counts};
                    }""")
                    log.warning("search_results_not_found",
                                url=diag.get("url"), counts=str(diag.get("counts")))
                    print(f"  [search diag] url={diag.get('url')} counts={diag.get('counts')}")
                except Exception as e:
                    print(f"  [search diag failed] {e}")
                raise

    # ── Train selection ───────────────────────────────────────────────────────

    async def find_and_select_train(self, train_number: str, travel_class: str) -> TrainInfo:
        # Wait for ANY train container to appear
        await self.page.wait_for_selector("[class*='train'], h2, [class*='avl']", timeout=45_000)

        # Dump visible train numbers for debugging
        try:
            heading_texts = await self.page.evaluate(
                "() => Array.from(document.querySelectorAll"
                "('[class*=\"train\"]')).map(e => e.textContent.trim())"
                ".filter(t => /\\d{5}/.test(t)).slice(0, 15)"
            )
            print(f"  [debug] Trains found on page: {heading_texts}")
            log.info("trains_on_page", trains=heading_texts)
        except Exception:
            pass

        # Check for the train number scoped to actual train-card elements —
        # a raw page.content() substring match can false-positive on the
        # number appearing in an unrelated fare, time, or another train's
        # number elsewhere on the page.
        train_found = await self.page.evaluate(
            f"() => Array.from(document.querySelectorAll('app-train-avl-enq'))"
            f".some(c => c.textContent.includes('{train_number}'))"
        )
        print(f"  [debug] '{train_number}' found in a train card: {train_found}")

        if not train_found:
            raise RuntimeError(
                f"Train {train_number} not found on page. "
                "Check the train number, date, and quota in your config. "
                "Verify Tatkal window hasn't closed."
            )

        # Now find the clickable train element - try multiple strategies
        # Strategy 1: Find by train heading class
        train_row = self.page.locator(f".train-heading:has-text('{train_number}')").first
        count = await train_row.count()
        
        if count == 0:
            # Strategy 2: Find any element containing train number and click its parent
            train_row = self.page.locator(f"text='{train_number}'").first
            count = await train_row.count()
        
        if count == 0:
            # Strategy 3: Find by partial match
            train_row = self.page.locator(f"*:has-text('{train_number}')").first
            count = await train_row.count()
        
        if count == 0:
            raise RuntimeError(
                f"Train {train_number} is on page but selector failed. "
                "DOM structure has changed significantly."
            )

        train_name = (await train_row.text_content() or "").strip()

        # Find the enclosing app-train-avl-enq Angular component for this train.
        # That component contains the class-availability cells as siblings of the heading.
        train_card = self.page.locator(
            f"app-train-avl-enq:has-text('{train_number}')"
        ).first

        # IRCTC renders each class as a clickable block showing "Sleeper (SL)" etc.
        # The full class label is e.g. "Sleeper (SL)" for SL, "AC 3 Tier (3A)" for 3A.
        # We match any element inside the card whose text contains the class code in
        # parentheses, e.g. "(SL)".  Using :has-text on the card's children gives us
        # Use JS to click the most specific element inside the train card that
        # contains "({travel_class})" — avoids matching parent containers whose
        # textContent transitively includes the class label.
        # JS also sidesteps Windows charmap issues with special chars in print.
        result = await self.page.evaluate(f"""() => {{
            const cards = document.querySelectorAll('app-train-avl-enq');
            const card = Array.from(cards).find(c => c.textContent.includes('{train_number}'));
            if (!card) return null;
            const all = Array.from(card.querySelectorAll('*'));
            const hits = all.filter(el => el.textContent.trim().includes('({travel_class})'));
            if (!hits.length) return null;
            const target = hits.reduce((a, b) =>
                a.textContent.trim().length <= b.textContent.trim().length ? a : b);
            target.click();
            return target.textContent.trim().slice(0, 80);
        }}""")
        avail_text = result or "UNKNOWN"

        log.info("train_found",
                 train=train_number, cls=travel_class, availability=avail_text)

        # ASCII-safe — Windows console charmap can't encode checkmark/middot
        print(f"  [OK] {train_number} {travel_class} | {avail_text} -- booking now")

        await asyncio.sleep(0.5)

        book_btn = self.page.locator("button:has-text('Book Now')").first
        await book_btn.wait_for(timeout=8_000)
        await book_btn.click()

        return TrainInfo(
            train_number=train_number,
            train_name=train_name,
            availability=avail_text,
        )

    async def read_availability_for_class(
        self, train_number: str, travel_class: str
    ) -> str:
        """Read the live availability badge for train_number / travel_class from
        the search results page WITHOUT clicking Book Now.

        Returns the raw badge text, e.g. "AVAILABLE-4", "GNWL 45/WL 30",
        "REGRET", "NOT AVAILABLE", or "UNKNOWN" if the badge can't be found.
        """
        await self.page.wait_for_selector(
            "[class*='train'], app-train-avl-enq", timeout=30_000
        )

        badge_text: str = await self.page.evaluate("""(args) => {
            var tn = args[0], tc = args[1];
            // Find the train card
            var cards = document.querySelectorAll('app-train-avl-enq');
            var card = Array.from(cards).find(function(c) {
                return c.textContent.includes(tn);
            });
            if (!card) return 'NOT_FOUND';
            // Find the class tab that matches travel_class (e.g. "(SL)")
            var all = Array.from(card.querySelectorAll('*'));
            var clsEl = all.find(function(el) {
                return el.textContent.trim().includes('(' + tc + ')');
            });
            if (!clsEl) return 'CLASS_NOT_FOUND';
            // Look for availability badge siblings — text matching AVAILABLE, WL, RAC etc.
            var parent = clsEl.closest('li, .class-avl-enq, [class*="avl"], td') || clsEl.parentElement;
            var avlPat = /AVAILABLE|CURR_AVBL|RAC|GNWL|RLWL|PQWL|TQWL|RSWL|WL|REGRET|NOT AVAILABLE|TRAIN CANCEL/i;
            // Walk up to find the section containing availability text
            var search = parent;
            for (var i = 0; i < 5 && search; i++) {
                var desc = Array.from(search.querySelectorAll('*'));
                var hit = desc.find(function(el) {
                    return avlPat.test(el.textContent.trim()) &&
                           el.textContent.trim().length < 50 &&
                           el.children.length === 0;  // leaf node
                });
                if (hit) return hit.textContent.trim();
                search = search.parentElement;
            }
            // Fallback: return raw text from the card's availability area
            return (card.textContent.match(avlPat) || ['UNKNOWN'])[0];
        }""", [train_number, travel_class])

        log.info("read_availability", train=train_number, cls=travel_class,
                 badge=badge_text)
        return badge_text or "UNKNOWN"

    # ── Intermediate booking/train-list page ─────────────────────────────────

    async def _proceed_from_booking_train_list(self, config: BookingConfig) -> None:
        """IRCTC routes the first 'Book Now' click through /booking/train-list
        before reaching /booking/psgn-dtl.

        This page shows the same train-list layout but in booking mode.
        Two explicit clicks are required to enable the Book Now button:
          1. Click the class tab anchor (<a> inside the <li>) — Angular's
             (click) handler is on the anchor, not the list item.
          2. Click the date cell for the journey date in the date carousel —
             this is the missing click that clears the 'disable-book' class.
        """
        from datetime import datetime as _dt

        tn = config.train_number
        tc = config.travel_class.value
        log.info("booking_train_list_intermediate", train=tn, cls=tc)

        # Format journey date as IRCTC shows it in the carousel, e.g. "28 May"
        try:
            _jd = _dt.strptime(config.journey_date, "%d-%m-%Y")
            date_display = _jd.strftime("%d %b").lstrip("0")  # "28 May"
        except Exception:
            date_display = ""

        # Wait for train cards to appear on this page
        await self.page.wait_for_selector(
            "app-train-avl-enq", timeout=15_000, state="attached"
        )
        await asyncio.sleep(1)  # Let Angular finish hydrating

        # Screenshot at start of intermediate page
        try:
            await self.page.screenshot(path="step_booking_train_list.png")
            print("  [snap] step_booking_train_list.png")
        except Exception:
            pass

        # ── Click 1: the class tab anchor (<a> inside <li>) ─────────────────────
        # Angular's (click) handler lives on the <a> (PrimeNG TabMenu), not the
        # <li>.  Raw mouse.click() on the LI centre misses the anchor when the
        # anchor has its own padding.  Use Playwright's locator so the engine
        # scrolls + focuses the exact element before dispatching pointer events.
        #
        # We ALWAYS click even if the tab looks already active: on this page the
        # Angular component is freshly initialised, so isClassSelected=false
        # regardless of the visual active state inherited from routing.
        try:
            sl_anchor = (
                self.page
                    .locator("app-train-avl-enq")
                    .filter(has_text=tn)
                    .locator("li")
                    .filter(has_text=f"({tc})")
                    .locator("a")
                    .first
            )
            await sl_anchor.click(timeout=5_000)
            log.info("booking_train_list_sl_anchor_clicked", cls=tc)
            print(f"  [booking/train-list] SL anchor clicked (Playwright locator)")
        except Exception as e:
            log.warning("booking_train_list_sl_anchor_failed", error=str(e))
            print(f"  [booking/train-list] SL anchor click failed: {e}")

        await asyncio.sleep(0.5)  # let Angular process the click

        # ── Detect Tatkal ARP / date errors ─────────────────────────────────
        # Clicking the class on a Tatkal date outside the Advance Reservation
        # Period surfaces an inline error + toast: "Date outside Tatkal ARP
        # (50018)".  This is unrecoverable for this date — fail cleanly rather
        # than spinning on the disabled Book Now button below.
        try:
            arp_err = await self.page.evaluate("""() => {
                const t = (document.body.innerText || '');
                const m = t.match(/(Date )?outside Tatkal ARP[^\\n]*|\\(50018\\)[^\\n]*/i);
                return m ? m[0].trim().slice(0, 120) : null;
            }""")
        except Exception:
            arp_err = None
        if arp_err:
            log.error("tatkal_arp_error", detail=arp_err)
            raise RuntimeError(
                f"IRCTC rejected the booking: '{arp_err}'. The journey date is "
                "outside the Tatkal booking window (ARP) or the Tatkal window is "
                "not open yet. Nothing was booked."
            )

        # ── Click 2: the AVAILABILITY cell for the journey date ─────────────
        # The date carousel shows columns (Wed 10 Jun | Thu 11 Jun | …), each
        # with an availability badge below (AVAILABLE-0117 / WL xx / REGRET).
        # Clicking the AVAILABILITY BADGE (not the date header) is what Angular
        # uses to register the class+date selection and clear 'disable-book'.
        # Strategy: find the smallest element containing "10 Jun"-like text
        # AND an availability keyword, falling back to the date header itself.
        if date_display:
            avail_info = await self.page.evaluate(f"""() => {{
                const tn = '{tn}', dateStr = '{date_display}';
                const cards = document.querySelectorAll('app-train-avl-enq');
                const card  = Array.from(cards)
                                   .find(c => c.textContent.includes(tn)) || cards[0];
                if (!card) return {{error: 'no_card'}};

                const allEls = Array.from(card.querySelectorAll('*'));

                // Prefer an element whose text starts with a known avail keyword
                // AND whose parent/ancestor contains our date string.
                // This targets "AVAILABLE-0117" / "WL 5/WL 3" / "REGRET" cells.
                const availKeywords = ['AVAILABLE', 'CURR_AVBL', 'RAC', 'WL', 'GNWL',
                                       'RLWL', 'PQWL', 'TQWL', 'RSWL', 'REGRET',
                                       'NOT AVAILABLE'];

                // Find the date column container first
                const dateCols = allEls.filter(el => {{
                    const t = el.textContent.trim();
                    const r = el.getBoundingClientRect();
                    return t.includes(dateStr) && r.width > 5 && r.width < 300;
                }});

                // Among date column elements, look for child with avail keyword
                for (const col of dateCols) {{
                    const children = Array.from(col.querySelectorAll('*'));
                    const availEl = children.find(el => {{
                        const t = el.textContent.trim();
                        return availKeywords.some(k => t.startsWith(k));
                    }});
                    if (availEl) {{
                        const r = availEl.getBoundingClientRect();
                        if (r.width > 5 && r.height > 5) {{
                            return {{
                                x: Math.round(r.left + r.width  / 2),
                                y: Math.round(r.top  + r.height / 2),
                                text: availEl.textContent.trim().slice(0, 60),
                                tag:  availEl.tagName,
                                cls:  (availEl.className || '').slice(0, 80),
                                method: 'avail_cell',
                            }};
                        }}
                    }}
                }}

                // Fallback: smallest element containing the date string
                const hits = allEls.filter(el => {{
                    const t = el.textContent.trim();
                    const r = el.getBoundingClientRect();
                    return t.includes(dateStr) && r.width > 5 && r.width < 300;
                }});
                if (!hits.length) return {{error: 'no_date_els', sought: dateStr}};
                const target = hits.reduce((a, b) =>
                    a.textContent.trim().length <= b.textContent.trim().length ? a : b
                );
                const rect = target.getBoundingClientRect();
                return {{
                    x:      Math.round(rect.left + rect.width  / 2),
                    y:      Math.round(rect.top  + rect.height / 2),
                    text:   target.textContent.trim().slice(0, 60),
                    tag:    target.tagName,
                    cls:    (target.className || '').slice(0, 80),
                    method: 'date_header_fallback',
                }};
            }}""")
            print(f"  [booking/train-list] avail cell: {avail_info}")
            log.info("booking_train_list_avail_cell", info=str(avail_info)[:200])

            if avail_info and not avail_info.get("error"):
                await self.page.mouse.click(avail_info["x"], avail_info["y"])
                log.info("booking_train_list_avail_clicked",
                         x=avail_info["x"], y=avail_info["y"],
                         text=avail_info.get("text", ""),
                         method=avail_info.get("method", ""))
                print(f"  [booking/train-list] avail cell clicked "
                      f"({avail_info['x']},{avail_info['y']}): "
                      f"{avail_info.get('text','')} [{avail_info.get('method','')}]")
            else:
                log.warning("booking_train_list_avail_not_found",
                            info=str(avail_info), date=date_display)
                print(f"  [booking/train-list] avail cell not found: {avail_info}")
        else:
            log.warning("booking_train_list_date_parse_failed",
                        journey_date=config.journey_date)

        # ── Poll until 'disable-book' is gone (up to 5 s) ───────────────────
        book_now_enabled = False
        last_bn_state = None
        for attempt in range(10):
            await asyncio.sleep(0.5)
            try:
                bn_state = await self.page.evaluate(f"""() => {{
                    const cards = document.querySelectorAll('app-train-avl-enq');
                    const card  = Array.from(cards)
                                       .find(c => c.textContent.includes('{tn}'))
                                  || cards[0];
                    if (!card) return null;
                    const btns = Array.from(card.querySelectorAll('button'));
                    return btns.filter(b => b.textContent.includes('Book Now'))
                           .map(b => ({{text: b.textContent.trim(),
                                        disabled: b.disabled,
                                        cls: b.className.slice(0, 80)}}));
                }}""")
                last_bn_state = bn_state
                disabled = any(
                    b.get("disabled") or "disable-book" in b.get("cls", "")
                    for b in (bn_state or [])
                )
                print(f"  [booking/train-list] Book Now (attempt {attempt+1}): "
                      f"disabled={disabled}  cls={bn_state[0].get('cls','') if bn_state else '?'}")
                if not disabled and bn_state:
                    log.info("booking_train_list_book_now_enabled", attempt=attempt+1)
                    book_now_enabled = True
                    break
            except Exception as exc:
                print(f"  [booking/train-list] poll error: {exc}")

        # Screenshot after class+date selection
        try:
            await self.page.screenshot(path="step_booking_train_list_after_sl.png")
            print("  [snap] step_booking_train_list_after_sl.png")
        except Exception:
            pass

        # Book Now never became enabled — do NOT force-click a genuinely
        # disabled button into undefined downstream state (force=True bypasses
        # Playwright's actionability check, not IRCTC's own disabled state).
        # This combination is very likely not bookable — fail loudly instead
        # of guessing what happens on the other side of a disabled click.
        if not book_now_enabled:
            log.error("booking_train_list_book_now_stayed_disabled",
                      state=str(last_bn_state)[:200])
            raise RuntimeError(
                f"Book Now stayed disabled for {tn} ({tc}) after selecting "
                "class + date — this combination is likely not bookable "
                "(quota exhausted, invalid date, or a stale selection). "
                "Nothing was booked."
            )

        # ── Click Book Now (Playwright locator — respects scroll + visibility) ─
        try:
            book_btn = (
                self.page
                    .locator("app-train-avl-enq")
                    .filter(has_text=tn)
                    .locator("button:has-text('Book Now')")
                    .first
            )
            # force=True bypasses Playwright's own actionability check (e.g. a
            # covered/animating element) — NOT IRCTC's disabled state, which
            # is already confirmed False above.
            await book_btn.click(force=True, timeout=5_000)
            log.info("booking_train_list_book_now_clicked")
            print("  [booking/train-list] Book Now clicked")
        except Exception as e:
            log.warning("booking_train_list_book_now_failed", error=str(e))
            print(f"  [booking/train-list] Book Now click failed: {e}")

        # Screenshot immediately after Book Now click
        await asyncio.sleep(0.5)
        try:
            await self.page.screenshot(path="step_booking_train_list_after_bn.png")
            print("  [snap] step_booking_train_list_after_bn.png")
        except Exception:
            pass

        # ── Handle IRCTC Confirmation dialog (station-code mismatch warning) ──
        # IRCTC sometimes shows: "You searched from MAS but booking from MS to CGL.
        # Do you want to continue?" — we must click 'Yes' to proceed.
        await asyncio.sleep(1)
        try:
            yes_btn = self.page.locator(
                "button:has-text('Yes'), "
                ".modal-footer button:has-text('OK'), "
                "button.btn-primary:has-text('Yes')"
            ).first
            if await yes_btn.count() > 0 and await yes_btn.is_visible(timeout=2_000):
                await yes_btn.click()
                log.info("booking_train_list_confirmation_yes_clicked")
                print("  [booking/train-list] Confirmation dialog → clicked Yes")
                await asyncio.sleep(0.5)
        except Exception as e:
            log.debug("booking_train_list_no_confirmation_dialog", note=str(e)[:60])

        # Wait for navigation to the passenger-details page.
        # IRCTC uses two possible URLs: /booking/psgn-dtl and /booking/psgninput
        try:
            await self.page.wait_for_url("**/booking/psgn**", timeout=30_000)
            log.info("psgn_dtl_reached", url=self.page.url)
        except Exception:
            log.warning("psgn_dtl_url_wait_timeout", url=self.page.url)
            print(f"  [debug] URL after Book Now: {self.page.url}")
            try:
                await self.page.screenshot(path="step_booking_train_list_timeout.png")
                print("  [snap] step_booking_train_list_timeout.png")
            except Exception:
                pass

        # Dismiss insurance / travel-protection popup if it appears
        await asyncio.sleep(0.5)
        try:
            insurance_skip = self.page.locator(
                "button:has-text('Skip'), "
                "button:has-text('No Thanks'), "
                "button:has-text('Continue without insurance')"
            ).first
            if await insurance_skip.count() > 0 and await insurance_skip.is_visible():
                await insurance_skip.click()
                log.info("insurance_popup_dismissed")
        except Exception:
            pass

    # ── Passenger form ────────────────────────────────────────────────────────

    async def fill_passenger_details(self, config: BookingConfig) -> None:
        # ── Step 1: Wait for navigation to the booking page ──────────────────
        # After "Book Now" IRCTC navigates to /nget/booking/psgn-dtl.
        # URL wait is the most reliable first signal.
        try:
            await self.page.wait_for_url("**/booking/**", timeout=30_000)
            log.info("booking_page_navigated", url=self.page.url)
        except Exception:
            log.warning("booking_url_wait_skipped", url=self.page.url)

        # Debug screenshot — lets us see exactly what page loaded
        try:
            await self.page.screenshot(path="step_pax_form.png")
            print("  [snap] step_pax_form.png")
        except Exception:
            pass

        # ── Step 1b: Handle the booking/train-list intermediate page ─────────
        # IRCTC routes the first Book Now click here before psgn-dtl.
        if "booking/train-list" in self.page.url:
            await self._proceed_from_booking_train_list(config)

        # ── Step 2: Wait for the passenger form component ────────────────────
        # IRCTC uses two URLs: /booking/psgn-dtl (app-psgn-dtl component) and
        # /booking/psgninput (different component but same form fields).
        await self.page.wait_for_selector(
            "app-psgn-dtl, "
            "app-psgninput, "
            "input[id*='psgn-name'], "
            "input[id*='passengerName'], "
            "input[placeholder*='Name'], "
            ".passenger-detail, "
            "app-passenger-info, "
            "[class*='passengerRow'], "
            "[class*='passenger-row']",
            timeout=30_000,
            state="attached",
        )
        await asyncio.sleep(0.5)  # Angular rendering tick

        # Debug: dump all visible input IDs/names so we know exact selectors
        try:
            inputs_info = await self.page.evaluate(
                "() => Array.from(document.querySelectorAll("
                "  'input:not([type=\"hidden\"])'"
                ")).map(e => ({id: e.id, name: e.name, ph: e.placeholder})).slice(0, 40)"
            )
            print(f"  [debug] pax form inputs: {inputs_info}")
            log.info("pax_form_inputs_dump", count=len(inputs_info),
                     sample=str(inputs_info[:10])[:300])
        except Exception:
            pass

        # Debug: dump p-dropdown IDs
        try:
            dd_ids = await self.page.evaluate(
                "() => Array.from(document.querySelectorAll('p-dropdown, select'))"
                ".map(e => e.id || e.name || '?').slice(0, 30)"
            )
            print(f"  [debug] dropdowns: {dd_ids}")
        except Exception:
            pass

        # ── Dump dropdowns for diagnosis ─────────────────────────────────────
        try:
            dd_info = await self.page.evaluate("""() =>
                Array.from(document.querySelectorAll('p-dropdown, select')).map((el, i) => ({
                    i,
                    id:          el.id || '',
                    name:        el.getAttribute('name') || '',
                    formctrl:    el.getAttribute('formcontrolname') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    label:       (el.querySelector('.ui-placeholder, .p-placeholder, label') || {}).textContent || '',
                    parentText:  (el.parentElement || {}).textContent?.trim().slice(0, 60) || '',
                })).slice(0, 15)
            """)
            print(f"  [debug] dropdown info: {dd_info}")
            log.info("pax_form_dropdowns_dump", info=str(dd_info)[:600])
        except Exception:
            pass

        # ── Step 3: Fill each passenger row ──────────────────────────────────
        # IRCTC uses two form layouts depending on the booking URL:
        #   - /booking/psgn-dtl  → IDs like psgn-name-0, psgn-age-0, p-dropdown IDs
        #   - /booking/psgninput → inputs have placeholder='Name'/'Age', no IDs;
        #                          p-dropdowns also have no IDs (positional)
        for i, pax in enumerate(config.passengers):
            n = i + 1  # 1-based for some IRCTC field IDs

            # ── Name ─────────────────────────────────────────────────────────
            # Use type() instead of fill() to dispatch real keyboard events that
            # Angular's zone.js intercepts and registers in the FormControl.
            # fill() sets the DOM value but may not trigger Angular's (input)
            # handler in all versions.
            name_filled = False
            for name_sel in [
                f"input[id='psgn-name-{i}']",
                f"#passengerName{n}",
                f"input[id='name_{n}']",
                f"input[placeholder='Name']",           # psgninput layout
                f"input[placeholder='Passenger Name']",
            ]:
                try:
                    loc = self.page.locator(name_sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=2_000)
                        await loc.fill("", timeout=1_000)   # clear first
                        await self.page.keyboard.type(pax.name, delay=50)
                        await self.page.keyboard.press("Tab")
                        log.info("fill_name_ok", pax=i, sel=name_sel)
                        name_filled = True
                        break
                except Exception:
                    pass
            if not name_filled:
                log.warning("fill_name_failed", pax=i)

            # ── Age ──────────────────────────────────────────────────────────
            age_filled = False
            for age_sel in [
                f"input[id='psgn-age-{i}']",
                f"#passengerAge{n}",
                f"input[id='age_{n}']",
                f"input[placeholder='Age']",            # psgninput layout
            ]:
                try:
                    loc = self.page.locator(age_sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=2_000)
                        await loc.fill("", timeout=1_000)
                        await self.page.keyboard.type(str(pax.age), delay=50)
                        await self.page.keyboard.press("Tab")
                        log.info("fill_age_ok", pax=i, sel=age_sel)
                        age_filled = True
                        break
                except Exception:
                    pass
            if not age_filled:
                log.warning("fill_age_failed", pax=i)

            await asyncio.sleep(0.5)  # let Angular process name+age before dropdowns

            # Display-name mappings: IRCTC stores short codes but some pages show
            # full English names in the dropdown.  Try both.
            _GENDER_DISPLAY = {"M": "Male", "F": "Female", "T": "Transgender"}
            _BERTH_DISPLAY  = {
                "LB": "Lower",    "MB": "Middle",    "UB": "Upper",
                "SL": "Side Lower", "SU": "Side Upper",
                "NO PREFERENCE": "No Preference",
            }
            gender_display = _GENDER_DISPLAY.get(pax.gender.value, pax.gender.value)
            berth_display  = _BERTH_DISPLAY.get(pax.berth_preference.value,
                                                 pax.berth_preference.value)

            def _item_sel(val: str, display: str) -> str:
                # Cover both PrimeNG v8 (ui-*) and v14+ (p-*) class names,
                # and fall back to any visible li containing the text
                return (
                    f"li.ui-dropdown-item:has-text('{display}'), "
                    f"li.p-dropdown-item:has-text('{display}'), "
                    f"li[class*='dropdown-item']:has-text('{display}'), "
                    f"li.ui-dropdown-item:has-text('{val}'), "
                    f"li.p-dropdown-item:has-text('{val}'), "
                    f"li[class*='dropdown-item']:has-text('{val}')"
                )

            async def _open_dd_and_pick(dd_idx: int, item_val: str,
                                        item_display: str, label: str) -> bool:
                """JS-scroll the p-dropdown into view, click its inner trigger to
                open the panel, then click the matching list item via broad
                selector (any visible li containing the text)."""
                try:
                    # Scroll + JS click — target the inner trigger div
                    _sel = ".ui-dropdown,.p-dropdown,.ui-dropdown-trigger,.p-dropdown-trigger,.ui-dropdown-label,.p-dropdown-label"
                    opened = await self.page.evaluate("""(args) => {
                        var idx = args[0], trigSel = args[1];
                        var dds = document.querySelectorAll('p-dropdown');
                        if (idx >= dds.length) return false;
                        var dd = dds[idx];
                        dd.scrollIntoView({behavior:'instant', block:'center'});
                        var trigger = dd.querySelector(trigSel);
                        (trigger || dd).click();
                        return true;
                    }""", [dd_idx, _sel])
                    if not opened:
                        log.warning(f"open_dd_not_found", label=label, idx=dd_idx)
                        return False
                    await asyncio.sleep(0.5)  # let panel animate open

                    # Screenshot to diagnose what opened
                    try:
                        await self.page.screenshot(
                            path=f"step_dd_{label}_open.png"
                        )
                    except Exception:
                        pass

                    # Strategy 1: PrimeNG-specific list item classes
                    item = self.page.locator(_item_sel(item_val, item_display)).first
                    if await item.count() > 0:
                        await item.click(timeout=3_000)
                        log.info(f"fill_{label}_dd_primeng_ok", pax=i, idx=dd_idx)
                        return True

                    # Strategy 2: Any visible li on the whole page containing the text
                    # (safe because only the open dropdown panel has new visible lis)
                    for text in [item_display, item_val]:
                        vis_item = self.page.locator(f"li:visible").filter(
                            has_text=text
                        ).first
                        if await vis_item.count() > 0:
                            await vis_item.click(timeout=3_000)
                            log.info(f"fill_{label}_dd_visible_li_ok",
                                     pax=i, text=text)
                            return True

                    # Strategy 3: JS — find any li across the whole document
                    picked = await self.page.evaluate("""(args) => {
                        var display = args[0], val = args[1];
                        var allLis = Array.from(document.querySelectorAll('li'));
                        var match = allLis.find(function(li) {
                            var t = li.textContent.trim();
                            return (t === display || t === val) && li.offsetParent;
                        });
                        if (match) { match.click(); return match.textContent.trim(); }
                        return allLis.filter(function(l){ return l.offsetParent; })
                            .map(function(l){ return l.textContent.trim().slice(0,30); })
                            .join(' | ').slice(0, 300);
                    }""", [item_display, item_val])
                    if picked and picked in (item_display, item_val):
                        log.info(f"fill_{label}_dd_js_li_ok", pax=i, text=picked)
                        return True
                    log.warning(f"fill_{label}_item_not_found",
                                val=item_val, display=item_display,
                                visible_lis=str(picked)[:200])
                    # Close dropdown gently by clicking elsewhere (avoids Escape
                    # which triggers Angular change detection and re-render)
                    try:
                        await self.page.locator("body").click(
                            position={"x": 10, "y": 10}, force=True
                        )
                    except Exception:
                        pass
                    return False
                except Exception as exc:
                    log.warning(f"fill_{label}_open_dd_failed", err=str(exc)[:80])
                    return False

            async def _click_dd_by_content(content_keywords: list, item_val: str,
                                            item_display: str, label: str) -> bool:
                """Find a p-dropdown whose PARENT element text contains ALL of
                content_keywords (e.g. ['Male', 'Female'] uniquely identifies the
                gender dropdown).  PrimeNG hides the option panel inside the
                component, so `el.textContent` may only show the selected value;
                the PARENT includes the label + all options text, which our DOM
                dump confirmed contains the full list (e.g. 'GenderMaleFemaleTransgender').
                """
                idx = await self.page.evaluate(f"""() => {{
                    const keywords = {content_keywords!r};
                    const dds = Array.from(document.querySelectorAll('p-dropdown'));
                    return dds.findIndex(el => {{
                        // Check parent element text (includes label + all options)
                        const parent = el.parentElement;
                        const t = (parent ? parent.textContent : el.textContent) || '';
                        return keywords.every(k => t.includes(k));
                    }});
                }}""")
                log.info(f"dd_content_idx", label=label, keywords=content_keywords,
                         idx=idx)
                if idx < 0:
                    return False
                try:
                    await self.page.locator("p-dropdown").nth(idx).click(timeout=3_000)
                    await asyncio.sleep(0.3)
                    await self.page.locator(
                        _item_sel(item_val, item_display)
                    ).first.click(timeout=3_000)
                    log.info(f"fill_{label}_content_ok", pax=i, idx=idx)
                    return True
                except Exception as exc:
                    log.warning(f"fill_{label}_content_failed", err=str(exc)[:80])
                    await self.page.keyboard.press("Escape")
                    return False

            # ── Gender dropdown ──────────────────────────────────────────────
            gender_filled = False
            # psgn-dtl: p-dropdown[id='psgn-gender-{i}']
            for gender_sel in [
                f"p-dropdown[id='psgn-gender-{i}']",
                f"p-dropdown[id='passengerGender{n}']",
                f"select[id='gender_{n}']",
            ]:
                try:
                    loc = self.page.locator(gender_sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=3_000)
                        await asyncio.sleep(0.2)
                        await self.page.locator(
                            _item_sel(pax.gender.value, gender_display)
                        ).first.click(timeout=3_000)
                        log.info("fill_gender_ok", pax=i, sel=gender_sel)
                        gender_filled = True
                        break
                except Exception:
                    pass
            if not gender_filled:
                # psgninput: idx=1 = passengerGender (stable from DOM dump)
                if "psgninput" in self.page.url:
                    gender_filled = await _open_dd_and_pick(
                        1, pax.gender.value, gender_display, "gender"
                    )
                if not gender_filled:
                    gender_filled = await _click_dd_by_content(
                        ["Male", "Female", "Transgender"],
                        pax.gender.value, gender_display, "gender"
                    )
            if not gender_filled:
                log.warning("fill_gender_failed", pax=i)

            # ── Berth preference dropdown ────────────────────────────────────
            berth_filled = False
            for berth_sel in [
                f"p-dropdown[id='psgn-berth-choice-{i}']",
                f"p-dropdown[id='passengerBerthChoice{n}']",
                f"select[id='berth_{n}']",
            ]:
                try:
                    loc = self.page.locator(berth_sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=3_000)
                        await asyncio.sleep(0.2)
                        await self.page.locator(
                            _item_sel(pax.berth_preference.value, berth_display)
                        ).first.click(timeout=3_000)
                        log.info("fill_berth_ok", pax=i, sel=berth_sel)
                        berth_filled = True
                        break
                except Exception:
                    pass
            if not berth_filled:
                # psgninput: berth starts at idx=3 but Angular re-renders after
                # gender fill and removes the nationality dropdown, shifting berth
                # to idx=2.  Try both before falling back to content detection.
                if "psgninput" in self.page.url:
                    for berth_idx in (3, 2):
                        berth_filled = await _open_dd_and_pick(
                            berth_idx, pax.berth_preference.value,
                            berth_display, "berth"
                        )
                        if berth_filled:
                            break
                if not berth_filled:
                    berth_filled = await _click_dd_by_content(
                        ["Lower", "Upper", "No Preference"],
                        pax.berth_preference.value, berth_display, "berth"
                    )
            if not berth_filled:
                log.warning("fill_berth_failed", pax=i)

            # ── ID type (Tatkal mandatory) ────────────────────────────────────
            # On psgninput/GENERAL quota the ID type field may not exist.
            id_type_filled = False
            for id_type_sel in [
                f"p-dropdown[id='psgn-id-type-{i}']",
                f"p-dropdown[id='passengerIdType{n}']",
                f"select[id='idType_{n}']",
            ]:
                try:
                    loc = self.page.locator(id_type_sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=3_000)
                        await asyncio.sleep(0.2)
                        await self.page.locator(
                            _item_sel(pax.id_type.value, pax.id_type.value)
                        ).first.click(timeout=3_000)
                        log.info("fill_id_type_ok", pax=i, sel=id_type_sel)
                        id_type_filled = True
                        break
                except Exception:
                    pass
            if not id_type_filled:
                log.debug("fill_id_type_skipped", pax=i,
                          note="field absent on this page (GENERAL quota)")

            # ── ID number ────────────────────────────────────────────────────
            id_num_filled = False
            for id_num_sel in [
                f"input[id='psgn-id-no-{i}']",
                f"input[id='psgn-id-{i}']",
                f"#passengerIdNumber{n}",
                f"input[id='idNumber_{n}']",
                f"input[placeholder*='ID Number' i]",
                f"input[placeholder*='Card Number' i]",
                f"input[placeholder*='Aadhaar' i]",
                f"input[formcontrolname*='idCardNumber']",
            ]:
                try:
                    loc = self.page.locator(id_num_sel).first
                    if await loc.count() > 0:
                        await loc.fill(pax.id_number, timeout=3_000)
                        log.info("fill_id_number_ok", pax=i, sel=id_num_sel)
                        id_num_filled = True
                        break
                except Exception:
                    pass
            if not id_num_filled:
                log.warning("fill_id_number_failed", pax=i)

        # ── Mobile number ─────────────────────────────────────────────────────
        mobile_inp = self.page.locator(
            "#mob-num, #mobileNumber, "
            "input[id*='mob'], "
            "input[formcontrolname='mobileNumber']"
        ).first
        if await mobile_inp.count() > 0:
            try:
                await mobile_inp.fill(config.mobile)
            except Exception as exc:
                log.warning("fill_mobile_failed", err=str(exc))

        # ── "Book only if confirmed" checkbox ─────────────────────────────────
        # The checkbox (id='confirmberths', formcontrolname='bookOnlyIfCnf') can
        # be below the viewport fold on long pages.  Playwright's click() retries
        # scroll but sometimes fails ("outside of the viewport").  Use JS
        # scrollIntoView + click as a reliable fallback.
        if config.book_only_if_confirmed:
            cb_clicked = False
            try:
                await self.page.evaluate("""() => {
                    const cb = document.getElementById('confirmberths')
                        || document.querySelector('[formcontrolname="bookOnlyIfCnf"]')
                        || document.querySelector('[formcontrolname="confirmBerths"]')
                        || document.querySelector('input[type="checkbox"][id*="confirm"]');
                    if (cb && !cb.checked) {
                        cb.scrollIntoView({behavior: 'instant', block: 'center'});
                        cb.click();
                    }
                }""")
                log.info("confirm_berths_js_clicked")
                cb_clicked = True
            except Exception as exc:
                log.warning("confirm_berths_js_failed", err=str(exc)[:80])
            if not cb_clicked:
                try:
                    cb = self.page.locator(
                        "input[type='checkbox'][id*='confirm'], "
                        "p-checkbox[formcontrolname='confirmBerths'], "
                        "p-checkbox[formcontrolname='bookOnlyIfCnf']"
                    ).first
                    if await cb.count() > 0:
                        await cb.click(force=True)
                except Exception as exc:
                    log.warning("confirm_berths_fallback_failed", err=str(exc)[:80])

        # ── Decline Travel Insurance (inline Yes/No radio on psgninput) ───────
        # IRCTC shows "Travel Insurance — Yes / No" (₹0.45/pax). It's an inline
        # PrimeNG radio, NOT a popup. Select "No" so the required field is set.
        try:
            no_ins = self.page.locator(
                "label:has-text(\"don't want\"), "
                "label:has-text('No, I don'), "
                "p-radiobutton:right-of(:text('No'))"
            ).first
            if await no_ins.count() > 0:
                await no_ins.scroll_into_view_if_needed()
                await no_ins.click()
                log.info("insurance_declined")
        except Exception as exc:
            log.debug("insurance_decline_skip", note=str(exc)[:60])

        # ── Select payment mode (radio on psgninput, BEFORE Continue) ─────────
        # IRCTC routes payment via a coarse radio on the passenger page:
        #   • "Pay through BHIM/UPI"  → for UPI
        #   • "Pay through Credit & Debit Cards / Net Banking / Wallets / …"
        #                             → for Card / e-Wallet / everything else
        # The specific gateway selection happens later in payment.py.
        if config.payment:
            from core.models import PaymentMethod
            want_bhim_upi = config.payment.method == PaymentMethod.UPI
            label_text = "BHIM" if want_bhim_upi else "Credit"
            try:
                radio = self.page.locator(
                    f"label:has-text('{label_text}')"
                ).first
                if await radio.count() > 0:
                    await radio.scroll_into_view_if_needed()
                    await radio.click()
                    log.info("payment_mode_selected", mode=label_text)
                else:
                    log.warning("payment_mode_radio_not_found", wanted=label_text)
            except Exception as exc:
                log.warning("payment_mode_select_failed", err=str(exc)[:60])

        log.info("passengers_filled", count=len(config.passengers))

    # ── CAPTCHA ───────────────────────────────────────────────────────────────

    async def get_captcha_image(self) -> bytes:
        # The CAPTCHA is at the bottom of the passenger form.
        # On psgn-dtl it appears before submit; on psgninput it appears only
        # AFTER clicking "Proceed to Pay".  Scroll first, then if still absent,
        # trigger the submit to make it appear.
        _captcha_sel = (
            "img.captcha-img, "
            "app-captcha img, "
            "#captchaImage, "
            "img[src*='captcha' i], "
            "[class*='captcha'] img"
        )
        # Step 1: scroll to bottom and check
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        if await self.page.locator(_captcha_sel).count() > 0:
            captcha_el = self.page.locator(_captcha_sel).first
            await captcha_el.wait_for(timeout=5_000)
            return await captcha_el.screenshot()

        # Step 2: CAPTCHA not pre-loaded — click "Proceed to Pay" / "Next"
        # (psgninput requires the submit click to trigger CAPTCHA)
        log.info("captcha_not_preloaded_clicking_next")
        try:
            next_btn = self.page.locator(
                "button:has-text('Next'), "
                "button:has-text('Proceed to Pay'), "
                "button:has-text('Proceed')"
            ).first
            if await next_btn.count() > 0:
                await next_btn.click(timeout=5_000)
                await asyncio.sleep(1.5)
        except Exception as e:
            log.warning("captcha_next_click_failed", error=str(e)[:80])

        # Step 3: wait for CAPTCHA after submit click
        captcha_el = self.page.locator(_captcha_sel).first
        await captcha_el.wait_for(timeout=15_000)
        return await captcha_el.screenshot()

    async def fill_captcha(self, text: str) -> None:
        inp = self.page.locator(
            "input[id='captcha'], input[formcontrolname='captcha']"
        ).first
        await inp.fill(text)
        await asyncio.sleep(0.3)

    # ── Submit & confirmation ─────────────────────────────────────────────────

    async def submit_passenger_form(self) -> None:
        # Real flow (confirmed from manual recordings):
        #   psgninput  --Continue-->  /booking/reviewBooking  --Continue-->  /payment
        # The build previously waited for **/payment** directly and timed out at
        # the review page. We now click Continue, handle the review page, then
        # click Continue again before waiting for payment.
        async def _dump_form_state(tag: str) -> None:
            # Same diagnosis class as the search-button race: don't guess why
            # Continue no-ops, read the actual button/radio/validation state.
            try:
                diag = await self.page.evaluate(r"""() => {
                    const ascii = s => (s || '').replace(/[^\x00-\x7F]/g, '');
                    const buttons = Array.from(document.querySelectorAll('button'))
                        .map(b => ({
                            text: ascii((b.textContent || '').trim()).slice(0, 40),
                            disabled: b.disabled || b.getAttribute('aria-disabled') === 'true'
                                      || b.classList.contains('ui-state-disabled'),
                            visible: !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length),
                        }))
                        .filter(b => /continue|proceed|next/i.test(b.text));
                    const radios = Array.from(document.querySelectorAll('p-radiobutton, input[type="radio"]'))
                        .map(r => {
                            const box = r.querySelector
                                ? r.querySelector('.p-radiobutton-box, .ui-radiobutton-box') : null;
                            const checked = (r.tagName === 'INPUT') ? r.checked :
                                (box ? /highlight|checked/.test(box.className || '') : null);
                            const label = ascii((r.closest('div')?.textContent || '').trim()).slice(0, 30);
                            return { label, checked };
                        })
                        .filter(r => r.label);
                    const invalid = Array.from(document.querySelectorAll('.ng-invalid, [aria-invalid="true"]'))
                        .filter(e => e.offsetWidth || e.offsetHeight)
                        .map(e => ascii(e.tagName + '.' + (e.className || '')).slice(0, 60));
                    const errors = Array.from(
                        document.querySelectorAll('.error, .p-message, .ui-message, [class*="error"]')
                    )
                        .filter(e => (e.offsetWidth || e.offsetHeight) && e.textContent.trim())
                        .map(e => ascii(e.textContent.trim()).slice(0, 80));
                    return {
                        url: location.href, buttons, radios: radios.slice(0, 15),
                        invalidCount: invalid.length, invalidSample: invalid.slice(0, 8),
                        errors: errors.slice(0, 5),
                    };
                }""")
                log.info(f"psgninput_diag_{tag}",
                         url=diag.get("url"), buttons=str(diag.get("buttons"))[:300],
                         radios=str(diag.get("radios"))[:300],
                         invalid_count=diag.get("invalidCount"),
                         invalid_sample=str(diag.get("invalidSample"))[:200],
                         errors=str(diag.get("errors"))[:200])
                print(f"  [psgninput diag/{tag}] buttons={diag.get('buttons')}")
                print(f"  [psgninput diag/{tag}] radios={diag.get('radios')}")
                print(f"  [psgninput diag/{tag}] invalid={diag.get('invalidCount')} "
                      f"sample={diag.get('invalidSample')}")
                if diag.get("errors"):
                    print(f"  [psgninput diag/{tag}] errors={diag.get('errors')}")
            except Exception as e:
                print(f"  [psgninput diag/{tag} failed] {e}")

        async def _click_continue() -> bool:
            try:
                btn = self.page.locator(
                    "button:has-text('Continue'), "
                    "button:has-text('Proceed to Pay'), "
                    "button:has-text('Proceed'), "
                    "button:has-text('Next')"
                ).first
                if await btn.count() > 0:
                    await btn.click(timeout=5_000)
                    return True
            except Exception as e:
                log.warning("continue_click_failed", error=str(e)[:80])
            return False

        # Step 1: leave the passenger page. Same race-condition class as the
        # search-button bug — dump state BEFORE clicking (ground truth even on
        # a run that otherwise succeeds), then retry once if the URL doesn't
        # move off psgninput within a few seconds.
        await _dump_form_state("pre_continue")
        for attempt in range(1, 3):
            await _click_continue()
            log.info("passenger_form_continue_clicked", attempt=attempt)
            try:
                await self.page.wait_for_url(
                    lambda url: "psgninput" not in url, timeout=4_000
                )
                break
            except Exception:
                if attempt < 2:
                    log.warning("continue_no_nav_retrying", url=self.page.url)
                    continue
                await _dump_form_state("stuck_after_continue")
                try:
                    await self.page.screenshot(path="step_submit_stuck.png", full_page=True)
                    print("  [snap] step_submit_stuck.png")
                except Exception:
                    pass

        # Step 2: intermediate Review page (may be skipped on some layouts)
        try:
            await self.page.wait_for_url("**/booking/reviewBooking**", timeout=20_000)
            log.info("review_booking_reached", url=self.page.url)
            await asyncio.sleep(1)   # let the review page render
            await _click_continue()  # Step 3: Review --Continue--> payment
            log.info("review_booking_continue_clicked")
        except Exception:
            log.info("review_booking_not_seen",
                     note="proceeding to wait for payment", url=self.page.url)

        # Step 4: wait for the payment page (handles /payment and /nget/payment)
        try:
            await self.page.wait_for_url("**/payment**", timeout=30_000)
        except Exception:
            # IRCTC may show a CAPTCHA here (modal or inline) — capture for diag.
            try:
                await self.page.screenshot(path="step_submit_timeout.png")
            except Exception:
                pass
            log.warning("payment_url_wait_timeout", url=self.page.url)
            raise
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

    async def ping(self) -> None:
        """
        HEAD request on the current page URL — resets IRCTC's server-side
        session idle timer without navigating or altering DOM state.
        Errors are silently swallowed; the keepalive loop logs them.
        """
        await self.page.evaluate(
            "() => fetch(window.location.href, "
            "{method: 'HEAD', credentials: 'include', cache: 'no-store'})"
            ".catch(() => {})"
        )
