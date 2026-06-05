# Tatkal Agent — Task Tracker

## Done ✅

### Core booking flow fixes
- [x] Login session reuse — skip reload if already on train-search with live session (`navigate_to_booking` skip guard)
- [x] Spurious re-login eliminated — root cause was `page.goto(IRCTC_HOME)` hard-reload destroying Angular in-memory session
- [x] `is_logged_in()` hardened — 12 retries (6 s total), broader selectors, post-login verify step
- [x] Login CAPTCHA detection — checked both before AND after Sign In click; retry once on post-submit CAPTCHA

### booking/train-list intermediate page (unblocked end-to-end flow)
- [x] Identified the page as IRCTC's intermediate confirmation step between search results and passenger form
- [x] Fixed class tab click — click `<a>` inside `li.ui-tabmenuitem` (Angular handler on anchor, not LI)
- [x] Fixed disable-book — click the `AVAILABLE-XXXX` cell in the date carousel (not just the date header)
- [x] Handle station-mismatch Confirmation dialog ("Yes" click after Book Now)
- [x] Accept `/booking/psgninput` URL as passenger form (was only accepting `/booking/psgn-dtl`)

### Passenger form — psgninput layout
- [x] Name: `input[placeholder='Name']` + `keyboard.type()` + Tab for Angular events
- [x] Age: `input[placeholder='Age']` + `keyboard.type()` + Tab
- [x] Gender: JS scroll+click at `p-dropdown.nth(1)`, visible-li strategy for item selection
- [x] Berth: JS scroll+click at `p-dropdown.nth(3)` / nth(2) post-render, visible-li strategy
- [x] Confirm-berths checkbox: JS `scrollIntoView` + click (fixes "outside viewport" error)
- [x] Mobile number: `#mobileNumber` selector works on psgninput

### CAPTCHA
- [x] Scroll to bottom before looking for CAPTCHA image
- [x] Click "Next" to trigger CAPTCHA if not pre-loaded (psgninput flow)
- [x] `_solve_captcha()` skips gracefully on Playwright TimeoutError (GENERAL quota = no CAPTCHA)

### Infrastructure
- [x] `run_auto.py` — non-interactive dry-run launcher with smart `builtins.input` patch
- [x] `adapters/captcha_file.py` — file-based CAPTCHA adapter for Claude-controlled runs
- [x] Commit `2b889b6` pushed to `github.com/bharani-mandapaka/tatkal`
- [x] Vercel auto-deployed (status: Ready)

---

## In Progress 🔧

### Complete the dry run to payment page
The agent reaches `booking/psgninput` and fills Name/Age/Gender.
Still failing at `submit_passenger_form()` — the "Next"/"Proceed to Pay" button label
on psgninput hasn't been confirmed. Need to:
- [ ] Identify the exact submit button label on psgninput (screenshot shows "Back" but submit is cut off)
- [ ] Select a payment mode radio button before submitting (required by IRCTC form validation)
- [ ] Confirm the agent reaches payment URL and DRY_RUN stops cleanly

---

## Planned 📋 (from approved workflow redesign)

### Stage 1 — Interactive gather-info (replace encrypted config)
- [ ] `core/gather_info.py` — full interactive CLI questionnaire
  - Train number, from/to stations, date
  - Class priority list (ordered fallback: e.g. SL, 3A, 2A)
  - Quota (GENERAL / TATKAL / PREMIUM TATKAL)
  - Up to 4 passengers (name, age, gender, berth, ID type, ID number)
  - Mobile, payment method + credentials
  - Booking thresholds (RAC max, WL max, allowed WL types) — default = AVAILABLE only
- [ ] `run_interactive.py` — new entry point that calls gather_info then runs the flow

### Stage 4 — Availability-aware booking decision
- [ ] `core/availability_parser.py` — parse IRCTC badge text into structured result
  - Statuses: AVAILABLE, CURR_AVBL, RAC, GNWL, RLWL, PQWL, TQWL, RSWL, REGRET, NOT AVAILABLE, TRAIN CANCELLED
  - `evaluate_threshold(result, thresholds) → "book" | "pause" | "skip"`
- [ ] `BookingThresholds` dataclass in `core/models.py`
  - `max_rac: int | None = None` (None = don't book RAC)
  - `max_wl: int | None = None` (None = don't book any WL)
  - `allowed_wl_types: list[str] = []`
- [ ] `class_priority: list[str]` field on `BookingConfig`
- [ ] `read_availability_for_class(train_number, travel_class)` in `browser.py` — read badge without clicking
- [ ] `_check_availability_and_decide()` in `booking_flow.py` — class-fallback loop
- [ ] New `BookingState` values: `READING_AVAILABILITY`, `AWAITING_USER_APPROVAL`, `TRYING_NEXT_CLASS`, `REPORTING_FAILURE`

### Stage 5B — Failure report
- [ ] Structured failure table printed to console when no class is bookable

### WhatsApp interface (after CLI is solid)
- [ ] Wire gather-info stage to WhatsApp conversation flow (Claude-powered)
- [ ] CAPTCHA image → WhatsApp, text reply → agent
- [ ] UPI collect request flow, Card OTP via WhatsApp
- [ ] Confirmation PNR + screenshot sent to user on success

---

## Known Minor Issues 🐛

- `plyer` balloon tip `ValueError: string too long (318, max 256)` — Windows notification truncation; cosmetic, doesn't affect booking
- Hindi characters (हिंदी) in IRCTC header crash Windows console log encoder (charmap) — workaround: `errors='replace'` in diagnostic code
- `inspect_dom.py`, `inspect_dom2.py` in repo — debug scripts, consider removing
