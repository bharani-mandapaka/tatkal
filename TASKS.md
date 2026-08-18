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

## Overnight Fix Pass 🌙 (2026-08-14, ~23:00–00:30 IST)

Worked everything reachable **without a live IRCTC session** — deliberately did NOT
attempt a live run tonight: automated login is confirmed blocked (Akamai, HTTP 510)
and re-trying it unsupervised risks flagging the real account further before Monday;
`login_manual()` blocks on human `input()` which nobody was here to give. Everything
below is code + tests only, unverified live. **130/130 tests pass** (was 121; +9 new).

### Submit→payment blocker — best-effort fix, NOT yet live-verified
Root-caused by code review (no new live diagnostic data exists yet — the diag
added earlier this session was never actually exercised). Leading suspect:
the **Travel Insurance decline radio** (`fill_passenger_details` in `browser.py`)
had narrow, speculative selectors and **failed completely silently** if none
matched — no warning logged, nothing. If that field is required by IRCTC's
Angular reactive form, an unset radio would leave the form permanently invalid
and Continue would just... never enable. No error, no crash — exactly the
"stuck on psgninput" symptom logged on 2026-06-22.
- [x] **Insurance-decline now logs a warning if nothing matched** (was silent)
  and has a scoped JS fallback (finds the section whose text mentions
  "insurance", clicks the option inside it whose own text is "No") — replaces
  the old `:right-of(:text('No'))` selector, which could latch onto an
  unrelated "No" elsewhere on the page (e.g. berth "No Preference").
- [x] Continue/Proceed button click now does an explicit `scroll_into_view_if_needed`
  first, matching the pattern already needed for the confirm-berths checkbox.
- [ ] **Still needs a live run to confirm.** If insurance-decline wasn't
  actually the cause, the new warning log will at least tell us that
  definitively next time, instead of a silent no-op.

### Aadhaar OTP hand-off — built (task #5), NOT yet live-verified
- [x] `BookingState.AWAITING_AADHAAR_OTP` added.
- [x] `BrowserPort.handle_aadhaar_otp_if_present()` — new abstract method.
- [x] `PlaywrightBrowser` impl: broad heuristic (OTP-shaped input OR page text
  mentioning both "Aadhaar"/"Aadhar" and "OTP"), screenshots
  (`step_aadhaar_otp.png`), pauses for a human to enter the OTP directly in
  the browser (same hand-off shape as `login_manual()`). Returns `False`
  near-instantly when absent so it doesn't cost time on every run.
- [x] Wired into `booking_flow.py` at **two** checkpoints — after CAPTCHA-solving
  and after submit — since nobody has seen this screen live yet and its real
  position in the flow is still unknown. Both checks are cheap no-ops today.
- [x] 3 new tests (`test_irctc_platform.py`): both checkpoints get called;
  prompt-present doesn't abort the flow; prompt-absent is unaffected (regression guard).
- [ ] **Still the single highest-risk unknown.** This is a best-effort net,
  not a confirmed fix — task #6 (live rehearsal) is what actually resolves this.

### Payment — test coverage added (was zero)
- [x] `tests/test_payment.py` — 6 new tests: UPI/e-wallet/card happy paths,
  card OTP prompt, unknown-method `ValueError`, and the one that matters most:
  **`config.clear_sensitive()` fires even when a payment step raises mid-flight**
  (verified directly, not just implied by the happy-path tests) — CVV/MPIN/card
  number must never survive in memory past a failed payment attempt.

### Explicitly NOT attempted tonight (needs a human or live data, not just code review)
- Double-book / idempotency guard ("check My Bookings before re-submitting") —
  still open. Didn't blind-guess the "My Bookings" page DOM; a wrong guess here
  (false "already booked" positive, or a false negative that allows a real
  double-charge) would be worse than leaving it as a known gap.
- Client-side (Web Crypto) encryption for the Vercel web form — real fix, but
  too large to build+verify blind overnight. Operational workaround still
  stands: **have the friend run the CLI locally**, not the hosted web form, so
  credentials never leave their machine.
- Live TATKAL rehearsal (#6) and friend's-machine prep (#7) — need a human and/or
  a live Tatkal window; unchanged, still queued for the weekend.

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

---

## Stress-Test Findings 🧪 (pm-execution pass — 2026-06-18)

All tasks below were surfaced by running the full pm-execution skill family against
the as-built agent. Tag in `()` = skill that found it. Code refs are file:line.

**Decision on record: NO-GO for any live Tatkal run** until the 🔴 items are closed
and one real end-to-end PNR exists. Current build = flow-automation prototype.

### 🔴 Launch-blocking (fatal — agent cannot win a real seat)

- [ ] **Reality test first — gates everything else.** Do a manual TATKAL booking on
  train 17644 at a real 10/11 AM window. Screenshot every screen between "Book Now"
  and payment; stopwatch each segment. Confirms whether OTP/CAPTCHA/force-logout
  appear and where the time actually goes. *(pre-mortem, red-team-prd, sprint-plan)*
- [ ] **Aadhaar OTP is unhandled and mandatory** (since Jul 2025). Add
  `AWAITING_AADHAAR_OTP` to `BookingState` + a human hand-off (reuse WhatsApp/terminal
  gate). No OTP handling exists anywhere in `booking_flow.py` / `browser.py`.
  *(strategy-red-team, create-prd, pre-mortem T1)*
- [x] **Clock-skew check** — booking fires on local `datetime.now()` (`scheduler.py`),
  not IRCTC server time. Add NTP-vs-local check to `main.py check`; abort if skew
  >0.5s. *(red-team, prioritization ICE 384, pre-mortem T3)*
  — **DONE 2026-06-18**: `get_ntp_offset()` in `scheduler.py` (stdlib SNTP, no dep);
  `main.py check` warns + exits 1 if |skew|>0.5s, degrades gracefully if offline.
- [ ] **Force-logout recovery dead-ends on login-CAPTCHA** — `booking_flow.py:281`
  raises "booking aborted" when re-login needs a CAPTCHA (the most likely T=0 case).
  Handle it (pre-warm 2captcha for login) + measure real recovery wall-time vs
  time-to-soldout. *(red-team #3, pre-mortem T2)*

### 🟠 High (verified bugs / zero coverage)

- [x] **VERIFIED BUG: `AVAILABLE-0` → decision=book.** `evaluate_threshold`
  (`availability_parser.py:100`) checks only `status_type`, never `confirmed_count`.
  A zero-seat "AVAILABLE" badge triggers a booking attempt. Fix: require
  `confirmed_count is None or confirmed_count >= passenger_count`. *(dummy-dataset)*
  — **DONE 2026-06-18**: 0 seats → skip; confirmed < passengers → pause;
  `passenger_count` threaded from `booking_flow.py`. Regression tests in
  `tests/test_adversarial.py`.
- [ ] **Payment has zero tests** — no test exercises UPI/Card/e-Wallet paths in
  `payment.py`. *(test-scenarios S4/S6)*
- [ ] **Auth/OTP has zero tests.** *(test-scenarios S1)*
- [ ] **Double-book risk** — if payment succeeds but `get_booking_confirmation` poll
  times out, run reports FAILED; operator re-runs → second booking. Add idempotency:
  check "My Bookings" for today's PNR before re-submitting. *(pre-mortem T4)*
- [ ] **No post-payment availability guard** — `book_only_if_confirmed` guards the
  search→book flip (`booking_flow.py:112`) but nothing re-checks after payment starts;
  money can be taken for a ticket that flipped to WL. *(user-stories B2, test-scenarios S6)*
- [ ] **Carry-over: confirm `psgninput` submit button** — dry run still hasn't reached
  payment even in GENERAL quota (was already "In Progress"; promoting — it blocks the
  reality test). *(retro)*

### 🟡 Medium (correctness / robustness)

- [x] **Silent name truncation** — names >15 chars chopped with no warning
  (`models.py:56`); truncated name may not match Aadhaar/ID at boarding. Add visible
  warning + ID-match note. *(user-stories D1, test-scenarios S7)*
  — **DONE 2026-08-09**: `Passenger.__post_init__` now prints + logs
  (`passenger_name_truncated`) the original vs. truncated name so a boarding-time ID
  mismatch can be caught before travel day.
- [ ] **Berth dropdown re-render race** — dropdown shifts nth(3)→nth(2) after gender
  select (CLAUDE.md); non-deterministic. Add post-select verification/retry.
  *(test-scenarios S8)*
- [x] **Class-priority loop timing** — serial `read_availability_for_class` calls
  (`booking_flow.py:185`) burn the window. Cap list to 2 or read in parallel.
  *(red-team #2)*
  — **DONE 2026-08-09**: `_check_availability_and_decide` now reads all
  `class_priority` classes concurrently via `asyncio.gather` (`return_exceptions=True`,
  a failed read degrades to "skip" instead of crashing the whole batch), then evaluates
  decisions in priority order as before. Decision semantics unchanged — only the reads
  are now concurrent instead of serial.
- [ ] **Verify `read_availability_for_class` reads the badge without the commit-click**
  — CLAUDE.md says train-list needs 2 clicks to enable booking; the read-then-decide
  architecture is invalid if reading requires committing. *(red-team #4)*
- [x] **Passenger input validation** — empty name, negative age, age >150, accented
  chars, apostrophes all currently accepted (`models.py` Passenger). *(dummy-dataset)*
  — **DONE 2026-08-09**: empty/whitespace-only name and age outside 0–125 now raise
  `ValueError` at construction. Accented names (José) and apostrophes (D'Souza) are
  still accepted **on purpose** — those are valid real names; Playwright's
  `keyboard.type()` already handles Unicode correctly, so there was no actual typing
  risk to fix there. Un-xfailed the 3 corresponding tests in `test_adversarial.py` +
  added boundary/whitespace/truncation-message tests (all passing, 116 total).
- [ ] **Availability parser unknown statuses** — `CHART PREPARED`, `BOOKING CLOSED`,
  concatenated badges, Hindi text fall through to UNKNOWN→skip (safe, but verify real
  IRCTC strings). *(dummy-dataset)*
- [x] **`clear_sensitive()` gaps** — zeroes CVV/MPIN but not `card_number`/`expiry`
  (`models.py:69`); mutates shared in-memory config, relevant on re-run. *(user-stories C3)*
  — **DONE 2026-06-18**: now also zeroes `card_number` + `card_expiry`; test extended.
  (Shared-config mutation left as-is — clearing is the intended effect.)
- [ ] **`admin_phone` shared-service mode** (`models.py:113`) — booking for others
  escalates ToS risk; define consent/auth model or remove. *(stakeholder-map, create-prd)*

### 🔵 Process / metrics (not code, but gating)

- [ ] **Stop trusting GENERAL-quota dry runs** — they skip CAPTCHA/OTP/real payment
  (`booking_flow.py:301` skips CAPTCHA on timeout). Mark any feature validated only in
  GENERAL as "unproven". *(red-team-prd #1 — the most dangerous assumption)*
- [ ] **Add win-rate instrumentation** — `booking_result.json` logs `booking_time_ms`
  (speed) but not the North Star: confirmed-seat win-rate + unintended-booking count.
  *(brainstorm-okrs)*
- [ ] **Freeze performance work** until first real end-to-end PNR exists. *(retro)*
- [ ] **Re-validate IRCTC rule changes** before each live run (5-min check). *(retro)*
- [ ] **Strategic decision pending:** if reality test shows OTP can't be cleared within
  the seat-window, pivot from "autonomous booker" to "fast human-assist" — WhatsApp
  layer becomes primary product. *(outcome-roadmap, summarize-meeting)*

### 🧰 Test-infra follow-ups

- [x] Turn `tests/fixtures_adversarial.py` into a runnable parametrized pytest against
  `parse_availability` / `evaluate_threshold` / `Passenger`. *(dummy-dataset)*
  — **DONE 2026-06-18**: `tests/test_adversarial.py`; passenger-validation gaps
  encoded as `xfail` so they're tracked without breaking the suite.

---

## Competitive Analysis Findings 🥊 (2026-06-18)

Benchmarked against commercial tools (Tatkal Panda, Nexus, Ocean/TSF) and OSS
(shivamguys/cypress, lucky12651 Google-Vision, nashit8421 undetected-chromedriver).
Maturity verdict: **best-architected agent found, but ~Stage 0.7 of 4 operationally**
(zero confirmed PNRs; competitors have thousands). Strategic position: **win as a
"fast human-assist booker," not an autonomous bot** — lean into availability
intelligence + WhatsApp HITL where we already lead; avoid the anti-ban arms race.

### 🟩 Differentiators to lean into (where we already beat the field)
- [ ] **WhatsApp fast-assist as the PRIMARY product** — make CAPTCHA + OTP + payment
  hand-off the headline feature, not a fallback. No competitor pairs this with
  availability logic.
- [ ] **Harden the availability-decision engine** — it's our biggest edge; most tools
  blindly book whatever's clicked. (Depends on the `AVAILABLE-0` fix above.)

### 🟦 Table-stakes to borrow from competitors
- [ ] **Mobile OTP auto-read** — Android SMS-retriever / ADB bridge to grab the
  Aadhaar OTP and autofill it. Closes the Tier-0 OTP gap with near-zero human latency;
  this is THE technique mature mobile tools use. *(competitor: commercial mobile apps)*
- [ ] **OCR-first CAPTCHA (confidence-gated, race against 2captcha)** — flip current
  order: local OCR primary (~0.3s, free), 2captcha fallback, human last. Best as a
  parallel race using whichever returns first with high confidence.
  **Prereq experiment:** test OCR accuracy on ~20 real IRCTC captchas; only adopt if
  ≥~85% confidence-gated accuracy, else keep 2captcha primary. New adapter
  `adapters/captcha_ocr.py` implementing `CaptchaPort`. *(competitor: lucky12651 Google Vision)*
- [ ] **Light anti-detection** — add `playwright-stealth` so we don't look obviously
  scripted. Do NOT enter the fingerprint arms race (unwinnable for a solo project;
  IRCTC blocked 2.4cr IDs in 6 months with AI). *(competitor: undetected-chromedriver)*

### ⬛ Explicitly NOT building (de-scope decisions)
- [ ] Autonomous zero-human booking — killed by the Aadhaar OTP mandate.
- [ ] Fingerprint/anti-ban as a core feature — unwinnable treadmill.
- [ ] `admin_phone` shared-service mode — highest ToS/legal risk; cut it (also listed 🟡).
- [ ] Millisecond form-fill micro-optimization — human OTP latency dwarfs it.

---

## Competitive Analysis — OSS Deep Dive 🔍 (2026-08-14)

Follow-up to the 2026-06-18 pass, triggered by tonight's live finding (automated
login blocked with HTTP 510) and the pivot to `login_manual()`. This round went
deeper on GitHub-hosted OSS specifically and on what IRCTC's anti-bot system
actually is. **Bottom line: nothing here changes the plan for Monday — it
confirms the manual-login pivot was the right call and tells us where NOT to
spend the next 3 days.**

### 🔑 Headline finding: IRCTC's WAF is Akamai Bot Manager
Confirmed via PIB press coverage — Railways' anti-bot stack is Akamai Bot Manager
+ a major CDN, blocking **60+ billion malicious requests in 6 months** and
mitigating **~64% of Tatkal-window traffic**, with bot traffic hitting **~50% of
all login attempts in the first 5 minutes** of the window. This is what returned
our HTTP 510 tonight.
**Why it matters:** Akamai Bot Manager fingerprints TLS/JA3, device sensors, and
behavioral timing — not just `navigator.webdriver`. `playwright-stealth` (the
"light anti-detection" item in the 06-18 analysis) only patches JS-level tells
and would **not** have prevented tonight's block. **Downgrade/drop that item —
it's not worth the time before Monday, and probably not worth it ever** for a
solo project against enterprise-grade bot management. This validates (not just
excuses) the `login_manual()` pivot: it isn't a workaround for a bug, it's the
correct architecture given what IRCTC actually runs.

### 🔑 Aadhaar OTP: confirmed nobody has solved this in public
Checked every OSS Tatkal repo turned up by search — ArpanMajumdar, Prajinkya
Pimpalghare, the-vishal, nashit8421, praneetk2704, shivamguys, dpak-maurya,
mani90, SuneetPatil, sriharshaarangi, DheerendraTomar, suryaansh2002. **All
predate the July 2025 Aadhaar-OTP mandate; none handle it.** This isn't a gap
we're behind on — it's genuinely unmapped ground, same as everyone else.
Practical takeaway: there's no reference implementation to crib from, so task
**#6 (live rehearsal to observe the OTP screen) is the single highest-value
unknown left** — no shortcut exists, it has to be observed directly.

One adjacent pattern worth noting (not adopting this week): SuneetPatil's repo
auto-reads a **login OTP** (the CAPTCHA-alternative one, not Aadhaar) from Gmail
via IMAP, using Windows Credential Manager for the mailbox creds. Architecturally
transferable to Aadhaar OTP *if* it ever lands somewhere automatable (SMS
forwarding, ADB bridge) — but that's a v2 idea, not buildable+testable safely in
2 days. Keep task #5 scoped to a simple terminal/console hand-off for Monday.

### 🟩 Low-risk speed tips worth folding into the runbook (from tatkal-software/community sources, not code changes)
- [ ] Have the friend's `login_time` fire **10–15 min before** the window (not
  right at it) and hold on the search page — matches what the agent already
  does via `calculate_booking_times`, just confirm the lead time is generous.
- [ ] Confirm `payment.method` is **UPI**, not net banking — community consensus
  is UPI/card clears fastest under load.
- [ ] Runbook should tell the friend to keep a **second manual browser tab**
  logged in as a human backup, since `manual_login` is now the primary path
  anyway and the agent has zero confirmed live PNRs yet.
- [ ] Re-confirm clock sync (`main.py check`) in the minutes right before the
  window, not just once earlier in the day.

### What this changes vs. the 06-18 analysis
- **Drop/deprioritize:** `playwright-stealth` / anti-fingerprint work — confirmed
  low ROI against Akamai specifically.
- **Reinforced, not changed:** "fast human-assist booker" positioning, Aadhaar
  OTP as the existential blocker, avoiding the anti-ban arms race entirely.
- **No new blockers found** — the critical path is still #2 → #4 → #5/#6 → #7 → #8,
  unchanged by this research.

---

## Chat-Window UX 💬 (2026-08-17)

New requested product experience: user opens a browser and logs into IRCTC
themselves, double-clicks a launcher, a chat window asks journey/passenger/
payment details, then the agent kicks off booking — immediately for
non-Tatkal quotas, or waits for the window for Tatkal ones. Real Tatkal
window for this friend's trip is **tomorrow (Tue Aug 18)**, so today was
build + test, not a live attempt.

- [x] **`chat_ui.py`** — Tkinter chat window. Architecture: `conversation_script()`
  is a plain generator with **zero Tkinter dependency** (uses `yield`/`yield from`
  instead of `input()`) — `ChatApp` is a thin driver around it. This is what makes
  it testable without a display: 8 tests in `tests/test_chat_ui_script.py` drive
  the generator directly with `.send()`, covering the happy path, cancellation,
  validation-retry loops (bad age/date re-prompts), and payment-method branching.
  Additionally smoke-tested with **real Tk widgets** (not just the logic) — 23
  checks walking the entire questionnaire via actual Entry/Button widgets, ending
  on the cancel path so it never opens a real browser. All pass.
- [x] **Fixed a real bug this surfaced**: `scheduler.calculate_booking_times()` (used
  by every entry point, not just the new chat UI) always computed a Tatkal-style
  10/11 AM window regardless of `config.quota` — GENERAL/LADIES bookings would have
  waited for a window that doesn't apply to them. Added `TATKAL_QUOTAS` check; non-Tatkal
  quotas now fire immediately (`login_time == window_time == now_ist()`). 5 new tests.
- [x] Manual login is now **forced on** in the chat UI (no password question at all) —
  automated login is confirmed dead (Akamai), so there's no reason to still ask.
- [x] **`Start Tatkal Agent.bat`** — double-click launcher, `pause`s on error so a
  crash doesn't just flash and vanish.
- [x] README updated with the new Option A0.
- [ ] **Not yet done**: an actual supervised run through `Start Tatkal Agent.bat`
  end-to-end (real click-through by a human, real browser hand-off into
  `booking_flow.py`) — the widget smoke test stops at the cancel button on purpose,
  it never lets `_launch()` fire. The hand-off code itself is a thin, deliberately
  unmodified reuse of the same wiring `run_interactive.py` already uses, but "wiring
  reused correctly" and "actually verified" aren't the same claim — do one real
  GENERAL-quota run today before trusting this tomorrow.

---

## 🎯 Fix-First Order (recommended sequence)

The single question "what first?" — answered. Do these in order; each gates the next.

1. **Reality test** (manual TATKAL on 17644, screenshots + stopwatch). *Why first:
   it's free, takes 20 min, and can invalidate items 4–5 before you build them.*
2. **`AVAILABLE-0` + `confirmed_count ≥ passengers` fix.** *Why: verified bug,
   one-line-ish, fixture already written, prevents booking a sold-out class.*
3. **Clock-skew guard in `main.py check`.** *Why: cheap, high-confidence (ICE 384),
   independent of everything; a late fire loses the seat regardless of other fixes.*
4. **Aadhaar OTP hand-off** (`AWAITING_AADHAAR_OTP` + terminal entry first, mobile
   auto-read later). *Why: THE existential blocker — without it a live run stalls.
   Scope it from what the reality test reveals.*
5. **Force-logout recovery that handles login-CAPTCHA.** *Why: most-likely T=0 failure;
   pairs with #4 (both are "auth at the window").*
6. **Payment idempotency + post-payment guard.** *Why: prevents the two
   irreversible-harm outcomes (double-charge, WL charge) once you're booking for real.*

Everything else (🟡 robustness, OCR-first, anti-ban, WhatsApp-primary) comes AFTER a
first confirmed PNR. Correctness before speed; reality before polish.

---

## Full-Stack Stress Test Findings 🏗️ (2026-06-18)

Audited every layer: crypto/data, web frontend, web backend, browser automation,
WhatsApp HITL. Crypto **verified correct** (round-trip + wrong-pass rejection).
Biggest new exposure is where **real user secrets meet disk and network**.
File refs are file:line. None block a *personal* run today, but they matter most
if this ever touches another person's data.

### 🟠 Security / data-handling (the highest-value new findings)
- [ ] **Plaintext credentials transit the Vercel server.** The web form POSTs IRCTC
  password + full card (number/expiry/CVV) + MPIN as JSON; encryption is **server-side**
  (`api/index.py:82`), so plaintext lives in the serverless function's memory. The
  "never logged on this server" banner is unverifiable. **Fix: encrypt client-side
  (Web Crypto API) so plaintext never leaves the browser.** *(api/index.py:466)*
- [ ] **CVV stored at rest** (encrypted, but stored). PCI-DSS prohibits storing CVV at
  all. Fix: collect CVV at run-time, or drop card support. *(collector.py:112, models.py:66)*
- [ ] **Sensitive screenshots written to disk unencrypted** — `step_pax_form.png` etc.
  capture passenger names, ages, **ID numbers** in plaintext on every run. Gate behind a
  `DEBUG` flag; scrub or encrypt. *(browser.py:815 + ~12 more call sites)*
- [x] **No passphrase-strength enforcement** (collector + web form). A weak passphrase
  collapses the whole encryption — this is the real attack surface, not the cipher.
  — **DONE 2026-08-09**: `config.save_config()` (the one choke point every local save
  goes through) now rejects passphrases under `MIN_PASSPHRASE_LEN=8`; `collector.py`
  checks it too (friendly re-prompt) and now warns up front that there is no recovery
  if it's lost. `api/index.py` enforces the same minimum server-side via the new
  `ConfigureRequest` Pydantic model. (Prompted by hitting this exact wall this session —
  a forgotten passphrase has no recovery path by design.)
- [ ] **`session.json` cookies stored plaintext** in cwd — leaked file = IRCTC session
  hijack. Confirm `.gitignore` covers it; consider encrypting. *(browser.py:23)*
- [ ] **No log scrubber** (plan claimed one). `username` + header snippets (PII) logged.
  *(browser.py:183, browser.py:263)*
  — **PARTIAL 2026-08-09**: `username` is now masked (`me***l` style) at all 3
  `login_*` log sites in `browser.py`, so console output is safe to paste for
  diagnostics. The `is_logged_in_false_diag` header-snippet dump (can contain the
  logged-in user's display name) is still unscrubbed — left open.

### 🟠 WhatsApp HITL — dangling component (docs overstate it)
- [ ] **Not wired end-to-end.** `deliver_reply` is called only by tests; there is **no
  webhook endpoint** in `api/index.py` (only `/`, `/health`, `/api/configure`) and **no
  `send_image_fn` implementation**. Gate + adapter are unit-tested islands. CLAUDE.md's
  "api/index.py = Vercel FastAPI webhook" is **inaccurate — fix the doc**. *(reply_gate.py)*
- [ ] **No Meta signature verification** (`X-Hub-Signature-256`) — must exist before any
  inbound webhook goes live, or anyone can POST a fake CAPTCHA/OTP reply.
- [ ] **Global-dict gate** (`_gates`/`_replies`) is single-process/single-booking;
  phone-key collision under concurrency. Fine personal, breaks as a service. *(reply_gate.py:21)*
- [ ] **10s hardcoded HITL timeout** is OK for CAPTCHA but **far too short for an SMS OTP**
  (the thing it must eventually handle). *(captcha_admin_hitl.py:29)*

### 🟡 Automation robustness (`browser.py`)
- [x] **`force=True` on Book Now bypasses the `disable-book` guard** — can click a
  genuinely-disabled (not-bookable) button → undefined downstream state. *(browser.py:740)*
  — **DONE 2026-08-09**: the poll loop now tracks whether Book Now actually became
  enabled; if it never does (10 attempts / 5s), raise `RuntimeError` instead of
  force-clicking a still-disabled button. `force=True` is now documented as bypassing
  only Playwright's actionability check, not IRCTC's disabled state — which is already
  confirmed `False` by the time the click happens.
- [x] **`train_number in page.content()`** substring match → false-positive risk (number
  could match a price/time/other train). Scope the check to train-card elements. *(browser.py:408)*
  — **DONE 2026-08-09**: replaced the raw-HTML substring check in
  `find_and_select_train` with a JS scan scoped to `app-train-avl-enq` card elements
  (same pattern already used elsewhere in the file for class-tab matching).
- [ ] **Entirely selector-dependent** ("as of mid-2025"); no selector-drift detection —
  the #1 ongoing breakage risk. Consider a pre-run selector smoke-check. *(browser.py:4)*

### 🟡 Web backend (`/api/configure`)
- [x] **Zero server-side validation** — accepts any JSON shape; no field types,
  passenger-count cap, or age/string sanity. Malformed input flows into the encrypted
  config and breaks later at `_build_config`. *(api/index.py:66)*
  — **DONE 2026-08-09**: added `ConfigureRequest`/`PassengerIn`/`PaymentIn` Pydantic
  models — field types, age 0–125, name 1–15 chars, 1–4 passengers, valid
  gender/berth/id_type/travel_class enums, DD-MM-YYYY date format, payment
  method-specific required fields, and the passphrase-strength check. Bad input now
  gets a 422 with a field-level message instead of silently reaching `_build_config`.
  Verified with 16 hand-written cases (valid + 15 invalid variants) plus 2 route-level
  `TestClient` checks in an isolated venv (fastapi/pydantic aren't in the local agent's
  env) — all passed. Not yet run against the live Vercel deploy.
- [ ] **No rate limiting / body-size limit** — DoS-able (low impact; stateless). *(api/index.py:55)*

### 🔵 Hygiene / consistency
- [ ] Docstring references `tests/test_integration.py` which **doesn't exist**. *(browser.py:6)*
- [ ] **Two countdown implementations** (`scheduler.wait_until` + `booking_flow._countdown`)
  — duplication/drift risk; consolidate.
- [ ] Agent deps loosely pinned (`>=`), no lockfile → supply-chain drift. *(requirements-agent.txt)*

### ✅ Verified solid (do not regress)
- Crypto: PBKDF2-SHA256 480k + Fernet, random salt/save — round-trip + wrong-pass
  rejection **verified in-memory**. *(config.py:17)*
- Login false-positive re-check (`browser.py:146`) and no-hard-reload session guard
  (`browser.py:296`) — genuinely smart IRCTC-specific defenses.
- Hexagonal ports make the whole stack mock-testable. 109 tests pass, 3 xfail.

---

## Manual Booking Video Findings 🎥 (2026-06-19)

Charted the real flow from two screen recordings (GENERAL full flow → review;
TATKAL outside-hours → blocked at ARP). Deltas vs the built `browser.py`:

### 🔴 Flow-breaking (likely why dry run never reaches payment)
- [ ] **Missing `reviewBooking` step.** Real flow is `psgninput → /booking/reviewBooking →
  /payment`. `submit_passenger_form()` waited for `**/payment**` directly and would time
  out at the review page. Fix: after Continue, detect reviewBooking, click Continue again,
  then wait for payment. *(browser.py submit_passenger_form)* — **FIXED 2026-06-19**
- [ ] **Payment mode is chosen on the passenger page**, not a later page — a coarse radio:
  "Credit/Debit/NetBanking/Wallets/EMI/UPI_CC/UPI_CL" vs "BHIM/UPI". Must select it on
  psgninput before Continue. *(browser.py fill_passenger_details)* — **FIXED 2026-06-19**

### 🟠 New steps / failure modes
- [ ] **Welcome/language modal on fresh landing** — combines the Aadhaar "Authenticate now"
  alert with a हिंदी / English choice. Must click **English** (never "Authenticate now").
  Build only closed generic modals. *(browser.py login)* — **FIXED 2026-06-19**
- [ ] **"Date outside Tatkal ARP (50018)"** error fires on the class-tab click when the
  date is outside the Tatkal advance-reservation window. Must detect + fail cleanly, not
  hang. *(browser.py _proceed_from_booking_train_list)* — **FIXED 2026-06-19**
- [ ] **Travel Insurance is an inline Yes/No radio** on psgninput (₹0.45/pax), not a
  "Skip/No Thanks" popup. Must select "No". *(browser.py fill_passenger_details)*
  — **FIXED 2026-06-19**

### 🔵 Confirmed / notes
- [ ] **Login CAPTCHA did NOT appear** in either recording (an "OTP instead of CAPTCHA"
  option exists). Agent must not *require* a login CAPTCHA. *(already OK — handles if present)*
- [ ] **Chrome saved-password autofill** (Windows-PIN popup) is machine-specific — agent
  must rely on manual type-username/password + Sign In, never on autofill. *(already OK)*
- [ ] **Aadhaar OTP location still UNKNOWN** — GENERAL doesn't need it; TATKAL was blocked
  at the ARP error before reaching it. Still requires a real in-window run to observe.
- [x] Confirmed the build's train-list two-click pattern (class anchor → availability cell
  → Book Now) and availability badge formats (`RAC 26`, `AVAILABLE-0112`) match reality.

> ⚠️ All browser.py fixes above are **video-grounded but not yet verified against live
> IRCTC** — they degrade gracefully (try/except) but need a real run to confirm selectors.

### Dry-run results — live IRCTC, 2026-06-22 (2 runs, GENERAL quota, date overridden)
- [x] ✅ **Welcome/English modal fix VERIFIED LIVE** (`welcome_modal_english_selected` logged).
- [x] ✅ Login (manual type + Sign In, no login CAPTCHA), session-reuse guard, and form
  prefill all worked.
- [x] 🔴→✅ **Search blocker ROOT-CAUSED & FIXED (verified below).** Runs 1–2 timed out on
  `/nget/train-search` (no `app-train-avl-enq`). Diagnosis via prefill-readback (run 3): the
  form *fills* correctly but the **Angular reactive-form model isn't committed before the
  Search click** → form invalid → click is a no-op → no navigation. NOT selector drift.
  Fix in `prefill_search_form`: validate-and-re-fill loop (read back origin/dest/date,
  re-fill any missing field, up to 2 passes) + `search_trains` re-clicks once on miss.
  *(browser.py prefill_search_form / search_trains)*

### Verification run — live IRCTC, 2026-06-22 (search fix confirmed)
- [x] ✅ **Search fix VERIFIED WORKING** — `train_list_loaded attempt=1` (clean first-attempt
  search, no flake). Prefill readback correct: `origin='MGR CHENNAI CTL - MAS (CHENNAI)'
  dest='CHENGALPATTU JN - CGL (KANCHIPURAM)' date='04/07/2026' cls='Sleeper (SL)'
  quota='GENERAL'`. The race-condition fix holds.
- [ ] 🔴 **NEW BLOCKER (confirmed): submit → payment navigation fails.** Flow reaches
  SUBMITTING then stalls: `review_booking_not_seen note='proceeding to wait for payment'
  url=…/nget/booking/psgninput`, then 30s timeout waiting for `**/payment**`. The page
  **never leaves `/booking/psgninput`** — it reaches neither `reviewBooking` nor `payment`.
  The Continue click (and/or the payment-mode + insurance selections that gate it) isn't
  advancing the page. `step_submit_timeout.png` earlier showed the Payment-Mode radios still
  on-page. **Next:** capture the psgninput DOM at submit time — confirm the real Continue
  button label/selector and which validation (insurance radio? payment-mode radio? passenger
  field?) is blocking the form. *(browser.py submit_passenger_form / fill_passenger_details)*
- [ ] ⚠️ **Caution:** avoid rapid repeated live logins to the real account (bot-detection
  risk). Space diagnostic runs out.

---

## Chat-UI Live Diagnosis — "shows no seats when seats are available" (2026-08-18)

Root-caused via repeated live diagnostic runs (train 17644, MS→CGL, 30-09-2026, SL,
GENERAL quota) against a real IRCTC session.

### 🔴 Root cause #1 — FIXED: availability badge never rendered without a click
`read_availability_for_class` read the DOM once and returned the literal string
`"UNKNOWN"` whenever no `AVAILABLE`/`WL`/etc. text was found anywhere on the matched
train card. Confirmed via live screenshots: each class box shows a **"Refresh ↻"**
placeholder with no fare/availability data until that class is clicked — IRCTC only
fetches a class's availability once its tab is activated. A 4-second polling retry
(added first, in case it was just an ajax-timing gap) made no difference, proving it
wasn't timing — the data genuinely isn't in the DOM pre-click.
Fix: `read_availability_for_class` now finds the class label (e.g. "(SL)") by text,
walks a few ancestor levels up looking for a nearby "Refresh" element, and clicks its
real screen coordinates via `page.mouse.click()` (JS `.click()` doesn't reliably
trigger Angular's zone.js) before reading the badge. *(browser.py)*
- First attempt at the click-target search required the matched element to have
  `children.length === 0` (a true DOM leaf) — but "Refresh" almost certainly wraps an
  icon glyph as a child element, so the filter skipped right past the real target.
  Removed that constraint and increased the ancestor search depth 4→8. **Not yet
  verified live** — next login attempt will confirm.

### 🔴 Root cause #2 — FIXED: destination field could silently hold the raw code
On one run the whole search failed (`app-train-avl-enq` never appeared) because the
destination field held just `"CGL"` instead of the autocomplete-resolved
`"CHENGALPATTU JN - CGL (KANCHIPURAM)"` — the suggestion click hadn't landed, and the
old verification loop only checked "is the field non-empty", so it didn't notice.
Fix: `prefill_search_form`'s readback now requires the field to actually look like a
resolved station name (contains `"("` and isn't just the bare code), re-filling if not.
*(browser.py prefill_search_form)*

### 🟡 Investigated and reverted — NOT the login problem
One diagnostic run got `"Unable to Process your request, please try later"` on manual
login (same credentials that worked seconds later in the user's normal Chrome). Added
`ignore_default_args=["--enable-automation"]` + `--disable-blink-features=
AutomationControlled` + a `navigator.webdriver` JS patch, suspecting IRCTC was
detecting the CDP-controlled browser itself. **Reverted** — login had already
succeeded via plain manual login 3+ times earlier the same session with none of this,
so the patch wasn't fixing a real baseline problem and a naive `navigator.webdriver`
override can itself read as MORE suspicious to sophisticated bot detection (a
non-native property descriptor is its own tell). Far more likely explanation: this is
the exact "avoid rapid repeated live logins" risk noted above — the login endpoint was
hit 6+ times in ~2 hours of diagnostic runs today, plausibly tripping IRCTC's own
rate-limiting rather than anything automation-specific. **Lesson reinforced: space out
live login attempts, especially during active debugging sessions.**

### Also fixed in passing
- `chat_ui.py`'s real booking run now always writes a timestamped file log
  (`booking_YYYYMMDD_HHMMSS.log`), not console-only — the original bug report
  ("console auto closed, lost the trace") can't recur.
- `_build_captcha_adapter` in both `chat_ui.py` and `run_interactive.py` was missing
  the required `notifier` arg to `ManualCaptchaAdapter(notifier)` — silent `TypeError`
  after the chat completed, with no visible error since it fired after
  `root.destroy()`. Fixed in both, plus wrapped `_launch()` in try/except so any future
  exception prints a traceback and pauses instead of vanishing.
- `adapters/browser.py launch()` now prefers the user's real installed Chrome
  (`channel="chrome"`) over Playwright's bundled Chromium-for-Testing, which was
  getting silently blocked from spawning at all on this machine (likely AV
  distrusting a freshly-downloaded unrecognized .exe) — falls back to bundled
  Chromium if real Chrome isn't installed.
- `scheduler.calculate_booking_times` now fires immediately for non-Tatkal quotas
  instead of waiting for an inapplicable 10/11 AM window.

### Still open
- [ ] Live-verify the availability-click fix (root cause #1) end-to-end — badge should
  read a real `AVAILABLE-xxxx` value, not `UNKNOWN`.
- [ ] A temporary debug block in `read_availability_for_class` dumps the matched
  card's HTML to `card_dump.html` on every call — remove once the click fix is
  confirmed working live.
- [ ] Still no first-ever confirmed real PNR.
