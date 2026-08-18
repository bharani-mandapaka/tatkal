# 🚂 Tatkal Agent

An IRCTC Tatkal booking assistant. It logs in, pre-fills the search form, waits for the
Tatkal window to open at exactly 10:00 / 11:00 AM, reads live seat availability, fills
passenger details, handles the CAPTCHA, and drives the payment — keeping you in the loop
only where the law and IRCTC require a human (payment approval, OTP).

Built with **Python + Playwright**, a clean hexagonal architecture, and an encrypted
local config. There is no cloud booking service — **the agent runs on your machine, in
your browser, as your own IRCTC session.**

---

## ⚠️ Project status & disclaimer — read this first

- **This is a personal-use, educational project — not a finished, guaranteed booking
  tool.** It automates the booking *flow*; it does not guarantee a confirmed ticket.
- **IRCTC's Terms of Service prohibit automated booking.** You use this on your own
  account, at your own risk. Don't run it as a service or for other people.
- **Automated login is currently blocked by IRCTC's bot detection** (Akamai — confirmed
  live, HTTP 510 on the auth request). The agent now defaults to a **manual-login
  hand-off**: you log in yourself in the visible browser window, and the agent verifies
  and takes over from there. Set `manual_login: true` (the recommended default) when
  collecting your config.
- **Aadhaar OTP is mandatory for all Tatkal bookings (since July 2025).** A hand-off
  exists (you enter the OTP yourself when the agent detects the prompt and pauses), but
  it has **never been seen against a real Tatkal window** — only GENERAL quota (which
  doesn't require it) has been live-tested. Treat live Tatkal booking as
  **experimental / not verified end-to-end** until a real rehearsal confirms it.
- **No confirmed PNR has been produced yet, in any quota.** Current status against live
  IRCTC (**GENERAL quota**, dry-run mode):
  - ✅ Verified working: login, the welcome/language modal, form pre-fill, and search
    (reliably reaching live results).
  - ❌ **Currently broken — the active blocker:** after filling passenger details, the
    flow gets stuck on the passenger-details page (`/booking/psgninput`) and does not
    yet reach the review or payment page. A likely-cause fix has been applied (an
    insurance-decline field that could fail to select silently) but is **not yet
    live-verified**.
  - 🔧 **Availability-reading fix applied, not yet live-verified**: IRCTC only fetches
    a class's fare/availability once its tab is clicked — reading it without clicking
    first always reported "no seats" even when seats were available. A fix that clicks
    the class tab before reading is in place but hasn't completed a clean end-to-end
    live confirmation yet. See [TASKS.md](TASKS.md) for details.
  - See [TASKS.md](TASKS.md) for the live debugging log and root-cause notes.
- **Space out live login attempts.** Repeated manual logins in a short window (several
  within an hour or two) appear to trip IRCTC's own rate-limiting — a
  `"Unable to Process your request, please try later"` message, unrelated to
  credentials. Don't loop live diagnostic runs back-to-back; wait several minutes
  between them.
- Always keep a human watching the run. The agent is an assistant, not an autopilot.

> If you just want to understand or contribute to the code, everything below still
> applies — start with [Installation](#-installation) and [Development](#-development).

---

## ✨ Features

- **Precise window firing** — waits to the sub-second and fires at the Tatkal window
  (10:00 AM for AC classes, 11:00 AM for non-AC), with an NTP **clock-skew check** so a
  wrong laptop clock doesn't lose you the seat.
- **Availability-aware booking** — reads the live availability badge and decides
  **book / pause / skip** based on your rules. Tries a **priority list of classes**
  (e.g. `SL → 3A → 2A`) and books the first acceptable one.
- **Confirmed-only by default** — won't silently book RAC or waitlist unless you opt in.
- **Three payment paths** — UPI (approve on phone), IRCTC e-Wallet (MPIN), Card (OTP).
- **CAPTCHA handling** — 2captcha API (optional) with a manual fallback.
- **Encrypted credentials** — config is encrypted with a passphrase only you know
  (PBKDF2 + Fernet/AES). Your passphrase is never stored.
- **Two setup paths** — a web form that generates an encrypted config, or a fully
  interactive CLI that keeps credentials in memory only.
- **Session resilience** — keepalive pings + re-login recovery if IRCTC drops the
  session at the window.

---

## 🧭 How it works

```
   Setup (once)                 Booking day
 ┌──────────────┐         ┌───────────────────────────────────────────┐
 │ collect your │         │  login → pre-fill search form → WAIT for   │
 │ booking +    │  ────▶  │  10/11 AM → search → read availability →   │
 │ passenger    │         │  pick class → fill passengers → CAPTCHA →  │
 │ details      │         │  submit → PAY → confirmation (PNR)         │
 └──────────────┘         └───────────────────────────────────────────┘
                                  ▲ you step in only at: CAPTCHA (if no
                                    2captcha key), payment approval, OTP
```

---

## 📦 Requirements

- **Python 3.10+** (the code uses modern type syntax)
- **Google Chrome / Chromium** (installed automatically by Playwright)
- An **Aadhaar-linked IRCTC account** (required for Tatkal since July 2025)
- *(Optional)* a **[2captcha](https://2captcha.com)** API key for automatic CAPTCHA solving
- A laptop that **stays awake and online** during the booking window

---

## 🔧 Installation

```bash
# 1. Clone
git clone https://github.com/bharani-mandapaka/tatkal.git
cd tatkal

# 2. (Recommended) create a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements-agent.txt
playwright install chromium
```

---

## ⚙️ Configuration

You can supply your booking details in **three ways**. Pick one.

### Option A0 — Chat window (recommended for a non-technical friend)

Double-click **`Start Tatkal Agent.bat`**, or run:

```bash
python chat_ui.py
```

A small chat window opens and asks the same questions as Option A below, one at a
time — click buttons for choices (gender, berth, payment method, class priority...),
type into the box for everything else. Nothing is written to disk. Once you confirm
the summary, the chat window closes and a browser opens — the booking runs exactly
the same way as every other option here (same tested engine, just a friendlier way to
get the details in). **Non-Tatkal quotas (GENERAL, LADIES) start booking immediately**
instead of waiting for a 10/11 AM window, since they don't have one.

A console window stays open behind the chat for anything that needs you directly
(logging into IRCTC, CAPTCHA, Aadhaar OTP) — don't close it.

### Option A — Interactive run (simplest; nothing written to disk)

Run everything in one go. The agent asks for your details at runtime, keeps them **in
memory only**, and never writes credentials to disk. Best for a one-off booking.

```bash
python run_interactive.py
```

You'll be asked for: IRCTC username/password, journey (train, from/to, date, quota),
**class priority** (e.g. `SL 3A 2A`), passengers, mobile, payment method, and optional
RAC/waitlist thresholds. It then logs in and runs the full flow. → Jump to
[Booking day](#-the-booking-day-workflow).

### Option B — Encrypted config (set up once, run later)

Save an encrypted config now, run on booking day with just your passphrase. Two ways to
create it:

**B1 — CLI collector**
```bash
python main.py collect
```
Answer the prompts, set an encryption passphrase, and it writes
`booking_config.enc` + `booking_salt.bin` into the project folder.

**B2 — Web form** (the hosted config UI on Vercel)
1. Open the deployed config page in your browser.
2. Fill in the booking details and set a passphrase.
3. Download `tatkal_config.zip`, and extract `booking_config.enc` and
   `booking_salt.bin` into your local `tatkal/` folder.

> 🔒 Your passphrase is **never** stored or included in the download — only you know it.
> If you forget it, just re-run the collector.

---

## 🏃 The booking-day workflow

### Step 1 — Verify everything is ready (encrypted-config path)

Run the pre-flight check the night before or the morning of:

```bash
python main.py check
```

It verifies your config decrypts, Playwright is installed, your **clock is in sync**
(aborts if off by >0.5s), and prints the exact booking window and login time.

```
Tatkal Agent — Pre-run Check
───────────────────────────────────
Config file         ✓ Found
Passphrase          ✓ Correct
Playwright          ✓ Installed
2captcha key        ✓ Configured
Clock sync          ✓ Within +0.12s of true time
Booking window      10:00:00 · 27 Jun 2026
Login fires at      09:57:00
Time until login    14h 03m
```

### Step 2 — Run the agent

```bash
python main.py run          # encrypted-config path (asks for your passphrase)
# — or —
python run_interactive.py   # interactive path (asks for everything at runtime)
```

Start it **a few minutes before** the window. Then:

- **Keep the terminal open**, the laptop **awake**, and stay **online**.
- The browser opens (headed — you can watch every step) and logs in.
- The form pre-fills and the agent waits, counting down to the window.
- At 10:00 / 11:00 it searches, picks a class per your priority, and fills passengers.
- **CAPTCHA:** auto-solved if you set a 2captcha key; otherwise solve it in the browser
  and press Enter.
- **Payment:** the agent reaches the payment page and you approve (see below).
- On success it captures the **PNR**, saves a confirmation screenshot, and notifies you.

### Step 3 — Approve payment

| Method | What the agent does | What you do |
|---|---|---|
| **UPI** | Enters your UPI ID, clicks Pay, sends a collect request | **Approve the request in your UPI app** (PIN on your phone) |
| **e-Wallet** | Enters your IRCTC Wallet MPIN, clicks Pay | Nothing — fully automated |
| **Card** | Fills card number/expiry/CVV, clicks Pay | **Type the bank OTP** into the terminal when prompted |

---

## 🧪 Dry run (test without booking or paying)

Test the whole flow safely — it's designed to stop at the payment page and **take no
money**. Uses the encrypted config and a dev passphrase from an environment variable.

> ⚠️ **Currently**, a live dry run gets stuck one step earlier, on the passenger-details
> page — see the status note at the top of this README and [TASKS.md](TASKS.md).

```bash
# set the dev passphrase (see .env.example)
export TATKAL_DEV_PASSPHRASE="your-passphrase"   # Windows: set TATKAL_DEV_PASSPHRASE=...
python run_auto.py
```

Recommended test target (cheap, short, always available): **train 17644 (MAS → CGL),
Sleeper, GENERAL quota.** Run it off-peak to confirm your selectors and flow work before
risking a real Tatkal window.

---

## 🎚️ Class priority & booking thresholds

- **Class priority** — give an ordered list (`SL 3A 2A`). The agent reads availability
  for each in turn and books the first that meets your policy.
- **Thresholds** decide what counts as bookable:
  - **Default:** book only when `AVAILABLE` / `CURR_AVBL` (confirmed). RAC and waitlist
    are skipped.
  - **Opt-in RAC:** accept RAC up to a position you set.
  - **Opt-in Waitlist:** accept WL up to a position, restricted to WL types you allow
    (e.g. `GNWL`). TQWL/RSWL have near-zero confirmation odds.
  - **Borderline buffer:** if a status is within *N* of your limit, the agent **pauses
    and asks** instead of auto-booking.

The agent never books fewer confirmed seats than you have passengers without pausing.

---

## 🔐 Security & privacy

- **Encryption:** config is encrypted with **PBKDF2-HMAC-SHA256 (480k iterations) +
  Fernet (AES-128 + HMAC)**. A random salt is generated per save.
- **Your passphrase is never stored** — the key is derived from it at runtime.
- **Interactive mode writes nothing to disk** — credentials live in memory only.
- **Sensitive payment fields** (CVV, MPIN) are zeroed in memory after the payment attempt.
- **Never commit secrets.** `booking_config.enc`, `booking_salt.bin`, `session.json`,
  and `.env` are git-ignored.

> ⚠️ **Honest caveats** (see [TASKS.md](TASKS.md) for the full security audit): the web
> config form encrypts **server-side**, so plaintext briefly transits the server — prefer
> the **CLI collector** or **interactive mode** for maximum privacy. Card CVV is stored
> (encrypted) when you choose card payment; UPI/e-Wallet avoid that.

---

## 🗂️ Project structure

```
core/
  booking_flow.py        State machine: IDLE → LOGGING_IN → … → CONFIRMED
  models.py              BookingConfig, Passenger, PaymentConfig, thresholds, enums
  availability_parser.py Parses IRCTC availability badges → book/pause/skip
  gather_info.py         Interactive questionnaire (Option A)
  state_machine.py       BookingState enum
ports/                   Abstract interfaces (BrowserPort, CaptchaPort)
adapters/
  browser.py             Playwright automation against the IRCTC Angular SPA
  captcha_twocaptcha.py  2captcha API solver
  captcha_manual.py      Terminal-prompt fallback
  captcha_file.py        File-based CAPTCHA for automated dry runs
  notifier.py            Desktop notifications
payment.py               UPI / e-Wallet / Card payment handling
scheduler.py             Window-time calc (quota-aware) + NTP clock-skew check
config.py                Encrypt / decrypt the booking config
chat_ui.py               Chat-window front end (Option A0) — Tkinter driver around
                          a testable, Tkinter-free conversation_script() generator
Start Tatkal Agent.bat   Double-click launcher for chat_ui.py
collector.py             CLI collector (Option B1)
main.py                  Entry point: collect | check | run
run_interactive.py       Entry point: interactive 5-stage flow (Option A)
run_auto.py              Entry point: non-interactive dry run
api/index.py             Web config UI (FastAPI, deployed on Vercel)
whatsapp/                Remote CAPTCHA/OTP hand-off (in development)
tests/                   pytest suite (run: pytest)
```

---

## 🛠️ Development

```bash
pip install -r requirements-agent.txt
pytest                      # run the test suite
```

The hexagonal architecture means the booking logic is tested against **mock browser and
CAPTCHA ports** — no real browser or IRCTC needed for unit tests. See
[tests/TEST_SCENARIOS.md](tests/TEST_SCENARIOS.md) for the test plan.

---

## ⚖️ Legal

This software is provided for **personal and educational use only**. You are solely
responsible for how you use it. The authors accept no liability for account actions,
failed bookings, or financial loss. Do not use it to book tickets for others or to run
a commercial service. Researched 2026-08-18 — read this before relying on the tool:

- **IRCTC's Terms & Conditions explicitly prohibit automation/scripting software**,
  independent of intent or payment. This is a straightforward contract violation if
  detected — expect **account deactivation and ticket cancellation** as the baseline
  risk, every time, regardless of anything below.
- **Section 143 of the Railways Act, 1989** criminalizes running the *"business"* of
  procuring/supplying tickets for others (up to 3 years / ₹10,000 fine, 1-month/₹5,000
  minimum). Every prosecuted software case found (Super Tatkal, "Neo") involved payment
  from third parties or CAPTCHA/OTP bypass — the latter also drew separate **IT Act**
  charges. No case of prosecution for purely personal, unpaid, single-family use was
  found — but treat that as an enforcement gap, not legal clearance.
- **Closest analog**: a 2024 Tatkal-autofill browser extension ("Tatkalforsure") had its
  §143 case **quashed by the Karnataka High Court**, on the reasoning that the developer
  didn't procure/supply tickets — users booked their own. Not a Supreme Court precedent,
  and the developer was still arrested and had to litigate for months before it was
  cleared.
- This tool's manual-login, manual-CAPTCHA/OTP design is closer to that lower-risk
  pattern than to the bot-detection-bypassing tools that drew IT Act charges — but that
  is not the same as being legal. **This is not legal advice; consult a lawyer before
  relying on this for a real booking, especially for anyone other than yourself.**
