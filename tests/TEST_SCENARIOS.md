# Test Scenarios — Tatkal Agent

**Source:** stress-test user stories + as-built code (`payment.py`, `booking_flow.py`, `scheduler.py`)
**Generated:** 2026-06-18 (pm-execution test-scenarios pass)
**Total:** 22 scenarios · **Legend:** 🟢 mock-automatable now (no reality test) · 🔴 requires live IRCTC

This focuses on the two biggest **zero-coverage** areas that are nonetheless
**fully testable with mocked ports today** — `payment.py` and `booking_flow.py`
orchestration — plus regression guards for the fixes shipped on 2026-06-18.

---

## A. Payment handler (`payment.py`) — 🟢 mock-automatable, currently 0 tests

A fake `Page` that records `.locator(...).fill()/.click()` calls + a fake `Notifier`
is enough to test all of these. No browser, no IRCTC.

### A1 — e-Wallet happy path 🟢
**Tests:** PaymentMethod.EWALLET routing · **Priority:** High
| Step | Action | Expected |
|---|---|---|
| 1 | `handle_payment(page, cfg{EWALLET, mpin})` | selects IRCTC Wallet, fills MPIN, clicks Pay |
| 2 | after return | `cfg.wallet_mpin == ""` (cleared in `finally`) |

### A2 — UPI happy path fires the alert 🟢
**Tests:** `_handle_upi` notifier · **Priority:** High
| Step | Action | Expected |
|---|---|---|
| 1 | `handle_payment(... UPI, upi_id)` | fills VPA, clicks Pay |
| 2 | — | `notifier.alert()` called once ("approve on phone") |
| 3 | — | UPI id is NOT cleared (not sensitive in same way) |

### A3 — Card path waits for OTP then submits 🟢
**Tests:** `_handle_card` · **Priority:** High · **Mock:** `input()` patched to return "123456", OTP selector present
| Step | Action | Expected |
|---|---|---|
| 1 | `handle_payment(... CARD)` | fills number/expiry/cvv, clicks Pay |
| 2 | OTP field appears | reads OTP via `input()`, fills it, clicks Submit |
| 3 | after return | `cvv`, `card_number`, `card_expiry` all `""` |

### A4 — Unknown method raises, still clears 🟢
**Tests:** dispatch `else` + `finally` · **Priority:** Medium
| Step | Action | Expected |
|---|---|---|
| 1 | `handle_payment` with a bogus method | raises `ValueError` |
| 2 | — | `clear_sensitive()` still ran (finally) |

### A5 — Payment raises mid-fill, secrets still cleared 🟢
**Tests:** `finally` guarantee · **Priority:** High (security)
| Step | Action | Expected |
|---|---|---|
| 1 | mock `page.locator().fill` raises on CVV | exception propagates |
| 2 | — | `cfg.card_cvv == ""` despite the crash |

---

## B. Booking-flow orchestration (`booking_flow.py`) — 🟢 mock ports, thin coverage

Mock `BrowserPort` + `CaptchaPort` + `Notifier`. Assert **state transitions** and
**decisions**, not the browser.

### B1 — Login failure aborts cleanly 🟢
**Tests:** `_execute` login guard · **Priority:** Critical
| Step | Action | Expected |
|---|---|---|
| 1 | `browser.login` returns False | raises RuntimeError; state ends `FAILED`; notifier fired; "Nothing was booked" printed |

### B2 — Availability flips to WL → abort when confirmed-only 🟢
**Tests:** `booking_flow.py:112` guard · **Priority:** Critical
| Step | Action | Expected |
|---|---|---|
| 1 | `find_and_select_train` returns availability "WL 5", `book_only_if_confirmed=True` | raises before filling passengers; no payment |

### B3 — class_priority picks first bookable 🟢
**Tests:** `_check_availability_and_decide` · **Priority:** High
| Step | Action | Expected |
|---|---|---|
| 1 | priority [SL,3A]; SL→`read_availability`="REGRET", 3A="AVAILABLE-6" | chooses 3A, decision "book" |
| 2 | both unbookable | prints failure table, raises "Nothing was charged" |

### B4 — AVAILABLE-0 across the loop skips it 🟢 *(regression for today's fix)*
**Tests:** zero-seat guard via the flow · **Priority:** High
| Step | Action | Expected |
|---|---|---|
| 1 | only class reads "AVAILABLE-0" | decision skip → failure table, no booking |

### B5 — CAPTCHA primary fails → fallback solves 🟢
**Tests:** `_solve_captcha` fallback · **Priority:** High
| Step | Action | Expected |
|---|---|---|
| 1 | primary `.solve` raises, fallback returns "abcd" | `fill_captcha("abcd")` called; flow continues |

### B6 — No CAPTCHA element → skip gracefully 🟢
**Tests:** `_solve_captcha` timeout path · **Priority:** Medium
| Step | Action | Expected |
|---|---|---|
| 1 | `get_captcha_image` raises TimeoutError | logs "captcha_not_found_skipping", proceeds (no raise) |

### B7 — dry_run stops at payment 🟢
**Tests:** `dry_run` branch · **Priority:** Medium · **Mock:** `input()` patched
| Step | Action | Expected |
|---|---|---|
| 1 | run with `dry_run=True` | returns `{"reached":"payment_page"}`; `handle_payment` NOT called |

---

## C. Scheduler / timing (`scheduler.py`) — 🟢 partly covered

### C1 — Clock skew >0.5s flagged 🟢 *(regression for today's fix)*
**Tests:** `get_ntp_offset` consumption · **Priority:** Critical · **Mock:** patch `get_ntp_offset` → 1.2
| Step | Action | Expected |
|---|---|---|
| 1 | `main.py check` with mocked offset 1.2 | prints ✗, exits 1 |
| 2 | offset 0.1 | prints ✓ |
| 3 | `get_ntp_offset` raises OSError | prints "Could not reach NTP", does NOT exit |

### C2 — Booking-time calc: AC=10:00, non-AC=11:00 🟢 *(covered in test_scheduler)*
### C3 — `wait_until` past target returns immediately 🟢

---

## D. Auth / OTP / force-logout — 🔴 requires live IRCTC (reality-test gated)

These cannot be confidently automated until the reality test reveals real selectors
and triggers. Document as **manual scenarios** for the first live run.

### D1 — Aadhaar OTP appears mid-flow 🔴
**Priority:** Critical — currently UNHANDLED. Manual: reach passenger submit on TATKAL,
observe whether an Aadhaar OTP screen appears, capture selector + timing.

### D2 — Force-logout at window open 🔴
**Priority:** Critical. Manual: hold a session across 10:00:00, observe if IRCTC kills it,
time the re-login (and whether a CAPTCHA appears — the current dead-end case).

### D3 — `psgninput` submit button 🔴
**Priority:** High (carry-over). Manual: confirm exact submit label; blocks even the dry run.

---

## Coverage Matrix

| Area | Happy | Edge | Error | Security | Status |
|---|---|---|---|---|---|
| Availability parse/decide | ✅ | ✅ | ✅ | — | **covered** (+today's fix) |
| Payment handler | ❌ | ❌ | ❌ | ❌ | **A1–A5 proposed (mockable now)** |
| Booking-flow orchestration | partial | ❌ | partial | — | **B1–B7 proposed (mockable now)** |
| Scheduler/clock | ✅ | partial | ❌ | — | **C1 proposed (mockable now)** |
| Auth / OTP / force-logout | ❌ | ❌ | ❌ | ❌ | 🔴 live-gated (D1–D3 manual) |

## Test Data Requirements
- **Fake `Page`** — records `locator(sel).first.fill(x)/.click()`; configurable to raise on a chosen selector (A5).
- **Mock ports** — `BrowserPort`/`CaptchaPort`/`Notifier` returning scripted values (already used in existing tests; extend).
- **`input()` patch** — for card OTP (A3) and dry-run pause (B7).
- **Availability strings** — reuse `tests/fixtures_adversarial.py`.
- No real credentials, no network for any 🟢 scenario.

## Priority order to implement (all 🟢, no reality test)
1. **A1–A5 (payment)** — biggest zero-coverage area; security-critical (A5).
2. **B1–B7 (flow)** — locks in the orchestration + today's AVAILABLE-0 fix end-to-end.
3. **C1 (clock gate)** — small, guards a Critical fix.
