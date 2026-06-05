# Tatkal Agent — Claude Context

## What this project does

Automates IRCTC Tatkal ticket booking using Playwright browser automation.
At exactly 10:00 AM (AC classes) or 11:00 AM (non-AC), the agent:
logs in → pre-fills the search form → searches trains → selects class →
navigates the `booking/train-list` intermediate page → fills passengers →
handles CAPTCHA → submits → completes payment.

A WhatsApp interface layer is under development (see `whatsapp/` and `api/`).

## Two deployments

| Layer | Where | Purpose |
|---|---|---|
| Playwright agent | Local / Railway | Browser automation (cannot run serverless) |
| Webhook API | Vercel (`api/index.py`) | WhatsApp inbound message handler |

## Key commands

```bash
# Install agent dependencies
pip install -r requirements-agent.txt
playwright install chromium

# Collect encrypted booking config (run once before booking day)
python main.py collect

# Pre-run check (verifies config, timing, Playwright)
python main.py check

# Live run (real booking at 10/11 AM)
python main.py run

# Non-interactive dry run (stops at payment, no money taken)
python run_auto.py

# Tests
pytest
```

## Architecture — hexagonal

```
ports/          Abstract interfaces (BrowserPort, CaptchaPort)
adapters/       Concrete implementations
  browser.py        Playwright automation against IRCTC Angular SPA
  captcha_file.py   File-based CAPTCHA for automated/Claude-controlled runs
  captcha_manual.py Terminal prompt fallback
  captcha_twocaptcha.py  2captcha API solver
  notifier.py       Desktop notifications (plyer)
core/
  booking_flow.py   State machine: IDLE → LOGGING_IN → … → CONFIRMED
  models.py         BookingConfig, Passenger, PaymentConfig, enums
  state_machine.py  BookingState enum
whatsapp/           WhatsApp HITL components (reply gate, CAPTCHA admin)
api/index.py        Vercel FastAPI webhook
collector.py        Interactive CLI to collect + encrypt booking config
```

## Critical browser.py notes (IRCTC Angular SPA)

**Two passenger form URLs** — handle both:
- `/booking/psgn-dtl` — old layout, fields have IDs like `psgn-name-0`
- `/booking/psgninput` — new layout, inputs use `placeholder='Name'`/`'Age'`; p-dropdowns have no IDs

**booking/train-list intermediate page** — appears between search results and
passenger form. Requires two clicks to enable Book Now:
1. Click `<a>` inside the SL tab (Angular handler is on the anchor, not the LI)
2. Click the `AVAILABLE-XXXX` cell in the date carousel for the journey date
Then handle the station-mismatch Confirmation dialog (click "Yes").

**Dropdown filling on psgninput:**
- Gender: `p-dropdown.nth(1)` (idx confirmed across runs), display values "Male"/"Female"/"Transgender"
- Berth: `p-dropdown.nth(3)` at page load; may shift to nth(2) after gender selection triggers re-render
- Use JS `scrollIntoView` + click to avoid viewport issues

**CAPTCHA:**
- On psgn-dtl: appears before submit button
- On psgninput / GENERAL quota: may not appear at all; `_solve_captcha()` skips gracefully on timeout

**Angular zone.js:** Never use JS `element.click()` for Angular-controlled elements — use
`page.mouse.click(x, y)` or Playwright locator `.click()` to generate real pointer events.

## Encrypted config

`booking_config.enc` + `booking_salt.bin` — never commit these.
Passphrase: stored in user's head only.
For dry runs, `run_auto.py` hardcodes `PASSPHRASE = "17644MAS"`.

## Booking thresholds (planned)

Default policy (from workflow redesign plan):
- Book only if `AVAILABLE` or `CURR_AVBL`
- RAC, WL, REGRET → skip (user can opt in per-run)

## Test train for development

Train 17644 (CIRCAR EXPRESS), MAS → CGL, Sleeper (SL), GENERAL quota.
Short route (Chennai Egmore → Chengalpattu, ~80 min), cheap (₹150),
always has availability — ideal for dry-run testing.

## Environment / secrets

```
TWOCAPTCHA_API_KEY   optional, for auto CAPTCHA solving
NOTIFIER             optional, desktop notification backend
```
