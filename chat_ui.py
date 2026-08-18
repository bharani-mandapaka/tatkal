"""
Chat-window front end for the Tatkal Agent.

Run via:  python chat_ui.py   (or double-click "Start Tatkal Agent.bat")

Same underlying questions as core/gather_info.py's terminal questionnaire,
presented as a chat window instead of a terminal prompt. Once the chat
collects all details and you confirm, this hands off to the exact same
booking_flow.py / browser.py engine used everywhere else in this project —
nothing about the actual booking automation changes. A console window stays
open behind the chat for CAPTCHA / login / OTP prompts, exactly as today.

Design note: the conversation itself (`conversation_script` below) is a
plain generator with zero Tkinter dependency, so it can be unit-tested by
driving it with .send() — see tests/test_chat_ui_script.py. ChatApp is a
thin Tkinter driver around it.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional

sys.path.insert(0, ".")

from core.models import (
    BookingConfig, BookingThresholds, Passenger, PaymentConfig,
    TravelClass, Gender, BerthPreference, IDType, PaymentMethod,
)
from scheduler import calculate_booking_times, now_ist, TATKAL_QUOTAS

_AC_CLASSES = {"1A", "2A", "3A", "3E", "CC", "EC"}


# ── Step spec ────────────────────────────────────────────────────────────────

@dataclass
class Step:
    kind: str          # info | text | secret | number | date | choice | multi_choice | confirm
    message: str
    choices: Optional[list] = None     # list[(value, label)]
    lo: Optional[int] = None
    hi: Optional[int] = None
    default: object = None

    @staticmethod
    def info(message: str) -> "Step":
        return Step(kind="info", message=message)

    @staticmethod
    def text(message: str) -> "Step":
        return Step(kind="text", message=message)

    @staticmethod
    def secret(message: str) -> "Step":
        return Step(kind="secret", message=message)

    @staticmethod
    def number(message: str, lo: int, hi: int, default: Optional[int] = None) -> "Step":
        return Step(kind="number", message=message, lo=lo, hi=hi, default=default)

    @staticmethod
    def date(message: str) -> "Step":
        return Step(kind="date", message=message)

    @staticmethod
    def choice(message: str, choices: list, default: Optional[str] = None) -> "Step":
        return Step(kind="choice", message=message, choices=choices, default=default)

    @staticmethod
    def multi_choice(message: str, choices: list, preselected: Optional[list] = None) -> "Step":
        return Step(kind="multi_choice", message=message, choices=choices,
                     default=preselected or [])

    @staticmethod
    def confirm(message: str, default: bool = False) -> "Step":
        return Step(kind="confirm", message=message, default=default)


# ── Validated-ask sub-generators (mirror core/gather_info.py's helpers) ───────

def _ask_text(prompt: str, min_len: int = 1, max_len: Optional[int] = None,
              upper: bool = False):
    msg = prompt
    while True:
        raw = yield Step.text(msg)
        raw = (raw or "").strip()
        if upper:
            raw = raw.upper()
        if len(raw) < min_len:
            msg = f"{prompt}\n(That can't be empty — try again.)"
            continue
        if max_len:
            raw = raw[:max_len]
        return raw


def _ask_secret(prompt: str):
    raw = yield Step.secret(prompt)
    return raw or ""


def _ask_int(prompt: str, lo: int, hi: int, default: Optional[int] = None):
    msg = prompt
    while True:
        raw = yield Step.number(msg, lo, hi, default)
        raw = (raw or "").strip()
        if not raw and default is not None:
            return default
        try:
            n = int(raw)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        msg = f"{prompt}\n(Enter a number between {lo} and {hi}.)"


_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _parse_natural_date(raw: str, today: Optional[date] = None) -> Optional[str]:
    """Best-effort parse of however a person actually types a date into
    DD-MM-YYYY (the format the rest of the app stores internally). Accepts
    relative terms ('today', 'tomorrow', weekday names), numeric dates with
    any of -/. separators, ISO (YYYY-MM-DD), and month-name dates ('18 Aug',
    'Aug 18'), all with an optional year (missing year = next upcoming
    occurrence). Day-first throughout (18/08, not 08/18) — matches Indian
    date convention and the DD-MM-YYYY the rest of the app already uses, so
    there's never MM/DD-vs-DD/MM ambiguity to resolve. Returns None if the
    text genuinely can't be read as a date — that's the only time the chat
    should ask again."""
    if today is None:
        today = datetime.today().date()

    text = re.sub(r"[,]", " ", raw.strip().lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None

    if text == "today":
        return today.strftime("%d-%m-%Y")
    if text in ("tomorrow", "tmrw", "tmrrw"):
        return (today + timedelta(days=1)).strftime("%d-%m-%Y")
    if text in ("day after tomorrow", "day after"):
        return (today + timedelta(days=2)).strftime("%d-%m-%Y")

    m = re.fullmatch(r"(?:(?:next|this)\s+)?([a-z]+)", text)
    if m and m.group(1) in _WEEKDAY_NAMES:
        target_wd = _WEEKDAY_NAMES[m.group(1)]
        delta = (target_wd - today.weekday()) % 7
        delta = delta or 7  # today's own weekday name means next week
        return (today + timedelta(days=delta)).strftime("%d-%m-%Y")

    def _resolve(day: int, month: int, year: Optional[int]) -> Optional[date]:
        try:
            if year is None:
                candidate = date(today.year, month, day)
                return candidate if candidate >= today else date(today.year + 1, month, day)
            if year < 100:
                year += 2000
            return date(year, month, day)
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            result = _resolve(d, mo, y)
            if result:
                return result.strftime("%d-%m-%Y")

    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})", text)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            result = _resolve(d, mo, None)
            if result:
                return result.strftime("%d-%m-%Y")

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)  # ISO, unambiguous
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).strftime("%d-%m-%Y")
        except ValueError:
            pass

    m = re.fullmatch(r"(\d{1,2})\s*([a-z]+)\.?\s*(\d{2,4})?", text)
    if m and m.group(2) in _MONTH_NAMES:
        result = _resolve(int(m.group(1)), _MONTH_NAMES[m.group(2)],
                           int(m.group(3)) if m.group(3) else None)
        if result:
            return result.strftime("%d-%m-%Y")

    m = re.fullmatch(r"([a-z]+)\.?\s*(\d{1,2})\s*(\d{2,4})?", text)
    if m and m.group(1) in _MONTH_NAMES:
        result = _resolve(int(m.group(2)), _MONTH_NAMES[m.group(1)],
                           int(m.group(3)) if m.group(3) else None)
        if result:
            return result.strftime("%d-%m-%Y")

    return None


def _ask_date(prompt: str):
    msg = prompt
    while True:
        raw = yield Step.date(msg)
        parsed = _parse_natural_date(raw or "")
        if parsed is None:
            msg = (f"{prompt}\n(Didn't catch that — try something like "
                    "'18 Aug', '18-08-2026', or 'tomorrow'.)")
            continue
        if datetime.strptime(parsed, "%d-%m-%Y").date() < datetime.today().date():
            msg = f"{prompt}\n(That's in the past — journey date must be today or later.)"
            continue
        return parsed


def _ask_choice(prompt: str, choices: list, default: Optional[str] = None):
    return (yield Step.choice(prompt, choices, default))


def _ask_multi_choice(prompt: str, choices: list, preselected: Optional[list] = None):
    raw = yield Step.multi_choice(prompt, choices, preselected)
    return raw or []


def _ask_confirm(prompt: str, default: bool = False):
    return (yield Step.confirm(prompt, default))


# ── The conversation ───────────────────────────────────────────────────────
# A straight-line generator using `yield from` for each question — mirrors
# gather_info.py's imperative flow almost line-for-line, just replacing
# blocking input() with yield. Returns a BookingConfig (or None if cancelled)
# via StopIteration.value.

def conversation_script():
    yield Step.info(
        "Hi! I'm your Tatkal booking agent. I'll ask a few quick questions, "
        "then get everything ready.\n\n"
        "Your IRCTC password never goes through me — when the browser opens "
        "you'll log in yourself, same as always."
    )

    username = yield from _ask_text("What's your IRCTC username?")

    train_number = yield from _ask_text("Train number? (e.g. 17644)", upper=True)
    from_station = yield from _ask_text("From station code? (e.g. MAS)", upper=True)
    to_station = yield from _ask_text("To station code? (e.g. CGL)", upper=True)
    journey_date = yield from _ask_date("Journey date?")

    quota = yield from _ask_choice("Which quota?", [
        ("TATKAL", "Tatkal"),
        ("PREMIUM TATKAL", "Premium Tatkal"),
        ("GENERAL", "General (non-Tatkal)"),
        ("LADIES", "Ladies"),
    ], default="TATKAL")

    if quota in TATKAL_QUOTAS:
        yield Step.info(
            f"Got it — {quota.title()}. I'll wait for the booking window to "
            "open and fire the moment it does."
        )
    else:
        yield Step.info(
            f"Got it — {quota.title()}. This quota has no fixed opening time, "
            "so I'll start booking right away once you confirm."
        )

    class_priority = yield from _ask_multi_choice(
        "Which class(es)? Click in the order you'd like them tried, then Done.",
        [(c.value, c.value) for c in TravelClass],
    )

    num_pax = yield from _ask_int("How many passengers? (1-4)", 1, 4, default=1)

    passengers_raw = []
    for n in range(1, num_pax + 1):
        yield Step.info(f"Passenger {n} of {num_pax}:")
        name = yield from _ask_text("Full name (as on ID, max 15 chars)", max_len=15)
        age = yield from _ask_int("Age", 1, 120)
        gender = yield from _ask_choice("Gender", [
            ("M", "Male"), ("F", "Female"), ("T", "Transgender"),
        ])
        berth = yield from _ask_choice("Berth preference", [
            ("LB", "Lower"), ("MB", "Middle"), ("UB", "Upper"),
            ("SL", "Side Lower"), ("SU", "Side Upper"), ("NO PREFERENCE", "No Preference"),
        ], default="LB")
        id_type = yield from _ask_choice("ID type (Tatkal mandatory)", [
            ("AADHAAR CARD", "Aadhaar Card"), ("PAN CARD", "PAN Card"),
            ("VOTER ID CARD", "Voter ID Card"), ("PASSPORT", "Passport"),
            ("DRIVING LICENCE", "Driving Licence"),
        ])
        id_number = yield from _ask_text("ID number")
        passengers_raw.append(dict(
            name=name, age=age, gender=gender, berth=berth,
            id_type=id_type, id_number=id_number,
        ))

    mobile = yield from _ask_text("Mobile number (10 digits, for booking SMS)",
                                   min_len=10, max_len=10)

    method = yield from _ask_choice("Payment method?", [
        ("UPI", "UPI (approve on your phone)"),
        ("EWALLET", "IRCTC e-Wallet"),
        ("CARD", "Debit / Credit Card"),
    ])
    payment_raw = {"method": method}
    if method == "UPI":
        payment_raw["upi_id"] = yield from _ask_text("UPI ID (e.g. you@upi)")
    elif method == "EWALLET":
        payment_raw["wallet_mpin"] = yield from _ask_secret("e-Wallet MPIN")
    else:
        payment_raw["card_number"] = yield from _ask_text("Card number (no spaces)")
        payment_raw["card_expiry"] = yield from _ask_text("Expiry (MM/YY)")
        payment_raw["card_cvv"] = yield from _ask_secret("CVV")

    policy = yield from _ask_choice("Booking policy?", [
        ("CONFIRMED_ONLY", "Confirmed seats only (recommended)"),
        ("ALLOW_RAC_WL", "Also accept RAC / Waitlist"),
    ], default="CONFIRMED_ONLY")

    thresholds_raw = {"max_rac": None, "max_wl": None, "allowed_wl_types": [],
                       "borderline_buffer": 2}
    if policy == "ALLOW_RAC_WL":
        allow_rac = yield from _ask_confirm("Allow RAC?", default=False)
        if allow_rac:
            thresholds_raw["max_rac"] = yield from _ask_int(
                "Maximum RAC position to accept", 1, 99, default=4
            )
        allow_wl = yield from _ask_confirm("Allow Waitlist?", default=False)
        if allow_wl:
            thresholds_raw["max_wl"] = yield from _ask_int(
                "Maximum WL position to accept", 1, 200, default=10
            )
            thresholds_raw["allowed_wl_types"] = yield from _ask_multi_choice(
                "Which waitlist types? (GNWL has the best odds)",
                [("GNWL", "GNWL"), ("RLWL", "RLWL"), ("WL", "Generic WL"),
                 ("PQWL", "PQWL"), ("TQWL", "TQWL"), ("RSWL", "RSWL")],
                preselected=["GNWL"],
            )

    passengers = [
        Passenger(
            name=p["name"], age=p["age"], gender=Gender(p["gender"]),
            berth_preference=BerthPreference(p["berth"]), id_type=IDType(p["id_type"]),
            id_number=p["id_number"],
        )
        for p in passengers_raw
    ]
    payment = PaymentConfig(
        method=PaymentMethod(payment_raw["method"]),
        upi_id=payment_raw.get("upi_id"),
        wallet_mpin=payment_raw.get("wallet_mpin"),
        card_number=payment_raw.get("card_number"),
        card_expiry=payment_raw.get("card_expiry"),
        card_cvv=payment_raw.get("card_cvv"),
    )
    thresholds = BookingThresholds(**thresholds_raw)

    try:
        initial_class = TravelClass(class_priority[0])
    except (ValueError, IndexError):
        initial_class = TravelClass.SL

    config = BookingConfig(
        username=username, password="", manual_login=True,
        train_number=train_number, from_station=from_station, to_station=to_station,
        journey_date=journey_date, travel_class=initial_class, quota=quota,
        passengers=passengers, mobile=mobile, payment=payment,
        class_priority=class_priority, thresholds=thresholds,
    )

    proceed = yield from _ask_confirm(_format_summary(config), default=True)
    if not proceed:
        yield Step.info("OK, cancelled. Close this window and run it again to re-enter details.")
        return None

    return config


def _format_summary(config: BookingConfig) -> str:
    lines = [
        "Here's what I've got:",
        f"  Login    Manual (you log in yourself)",
        f"  Train    {config.train_number}  {config.from_station} → {config.to_station}",
        f"  Date     {config.journey_date}   Quota: {config.quota}",
        f"  Classes  {' → '.join(config.class_priority)} (tried in order)",
    ]
    for p in config.passengers:
        lines.append(f"           {p.name}, {p.age}y, {p.gender.value}, {p.berth_preference.value}")
    lines.append(f"  Payment  {config.payment.method.value}")
    t = config.thresholds
    if t.max_rac is None and t.max_wl is None:
        lines.append("  Policy   Confirmed seats only")
    else:
        parts = []
        if t.max_rac is not None:
            parts.append(f"RAC<={t.max_rac}")
        if t.max_wl is not None:
            parts.append(f"WL<={t.max_wl} ({', '.join(t.allowed_wl_types) or 'all types'})")
        lines.append(f"  Policy   {', '.join(parts)}")
    lines.append("\nAll correct? Start booking?")
    return "\n".join(lines)


# ── Booking hand-off (identical wiring to run_interactive.py) ────────────────

def _build_captcha_adapter(config: BookingConfig, notifier):
    api_key = config.captcha_api_key or os.environ.get("TWOCAPTCHA_API_KEY")
    if api_key:
        from adapters.captcha_twocaptcha import TwoCaptchaAdapter
        return TwoCaptchaAdapter(api_key), None
    from adapters.captcha_manual import ManualCaptchaAdapter
    return ManualCaptchaAdapter(notifier), None


async def _run_booking(config: BookingConfig, window_time: datetime) -> None:
    from logger import setup_logging, get_logger
    from adapters.browser import PlaywrightBrowser
    from adapters.notifier import Notifier
    from core.booking_flow import BookingFlow

    log_file = f"booking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    setup_logging(log_file)
    log = get_logger()
    print(f"(Full log is being saved to {log_file} in case this window closes.)")

    notifier = Notifier()
    captcha, captcha_fallback = _build_captcha_adapter(config, notifier)
    browser = PlaywrightBrowser()
    flow = BookingFlow(browser, captcha, captcha_fallback, notifier, dry_run=False)

    log.info("chat_ui_run_start", train=config.train_number,
              classes=config.class_priority, quota=config.quota,
              window=window_time.strftime("%H:%M:%S"))

    print("\n" + "=" * 60)
    print("  Chat window closed — continuing here in the console.")
    print("  Watch this window for CAPTCHA / login / OTP prompts.")
    print("=" * 60 + "\n")

    await browser.launch()
    try:
        result = await flow.run(config, window_time)
        print(f"\nResult: {result}\n")
    except KeyboardInterrupt:
        print("\n\nAborted by user.\n")
    except Exception as e:
        print(f"\nFailed: {e}\n")
    finally:
        await asyncio.sleep(2)
        await browser.close()
        print("Browser closed.")


# ── Tkinter driver ─────────────────────────────────────────────────────────

class ChatApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import scrolledtext

        self.tk = tk
        self.root = root
        root.title("Tatkal Agent")
        root.geometry("560x640")

        toolbar = tk.Frame(root)
        toolbar.pack(fill="x", padx=8, pady=(8, 0))
        self.back_btn = tk.Button(toolbar, text="< Back", command=self._go_back)
        self.back_btn.pack(side="left")
        tk.Button(toolbar, text="Start Over", command=self._reset).pack(side="left", padx=(6, 0))

        self.transcript = scrolledtext.ScrolledText(
            root, wrap="word", state="disabled", font=("Segoe UI", 10)
        )
        self.transcript.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        self.transcript.tag_configure("agent", foreground="#0a5b8a")
        self.transcript.tag_configure("user", foreground="#333333")

        self.input_area = tk.Frame(root)
        self.input_area.pack(fill="x", padx=8, pady=(0, 8))

        self._multi_selected: list[str] = []

        # Replay-based Back/Reset: conversation_script() is a pure function
        # of the answer sequence, so "going back" is just re-running it with
        # one fewer answer rather than trying to rewind a live generator
        # (which Python generators don't support). _log holds everything
        # ever shown (for redrawing the transcript); _answer_positions[i]
        # is len(_log) right before the i-th answer was submitted, so
        # popping the last answer can truncate the transcript back to
        # exactly where that question was still unanswered.
        self._history: list = []
        self._answer_positions: list[int] = []
        self._log: list[tuple] = []
        self._launch_after_id = None

        self.script = conversation_script()
        self._update_back_button()
        self._advance(None)

    # ── transcript helpers ──────────────────────────────────────────────
    def _append(self, who: str, text: str) -> None:
        self._log.append((who, text))
        self._render_log_line(who, text)

    def _render_log_line(self, who: str, text: str) -> None:
        self.transcript.configure(state="normal")
        tag = "agent" if who == "Agent" else "user"
        self.transcript.insert("end", f"{who}: ", tag)
        self.transcript.insert("end", f"{text}\n\n")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _redraw_transcript(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        for who, text in self._log:
            self._render_log_line(who, text)

    def _clear_input_area(self) -> None:
        for w in self.input_area.winfo_children():
            w.destroy()

    def _update_back_button(self) -> None:
        self.back_btn.config(state=("normal" if self._history else "disabled"))

    # ── generator driving ────────────────────────────────────────────────
    def _advance(self, value) -> None:
        try:
            step = self.script.send(value)
        except StopIteration as stop:
            config = stop.value
            if config is None:
                return  # cancelled — leave the last message on screen
            self._start_booking(config)
            return
        self._render(step)

    def _render(self, step: Step) -> None:
        self._append("Agent", step.message)
        self._render_input(step)

    def _render_input(self, step: Step) -> None:
        """Show the input widgets for `step` WITHOUT re-appending its
        message — used both after a normal forward advance (message was
        just appended by _render above) and after Back (message is already
        sitting in the transcript from when it was first shown)."""
        self._clear_input_area()

        if step.kind == "info":
            self.root.after(400, lambda: self._advance(None))
            return

        if step.kind in ("text", "number", "date"):
            self._render_entry(step, mask=False)
        elif step.kind == "secret":
            self._render_entry(step, mask=True)
        elif step.kind == "choice":
            self._render_buttons(step.choices, self._submit_choice)
        elif step.kind == "confirm":
            self._render_buttons(
                [("__yes__", "Yes"), ("__no__", "No")], self._submit_confirm
            )
        elif step.kind == "multi_choice":
            self._render_multi(step)

    def _submit(self, display_text: str, value) -> None:
        self._answer_positions.append(len(self._log))
        self._append("You", display_text)
        self._history.append(value)
        self._update_back_button()
        self._advance(value)

    # ── Back / Start Over ─────────────────────────────────────────────────
    def _replay(self, history: list):
        """Rebuild a fresh script by re-sending a list of prior REAL answers
        (auto-skipping the info steps in between, same as the driver does
        live). Deterministic and side-effect-free — conversation_script()
        does no I/O, so this always reproduces the exact same state."""
        script = conversation_script()
        step = script.send(None)
        while step.kind == "info":
            step = script.send(None)
        for ans in history:
            step = script.send(ans)
            while step.kind == "info":
                step = script.send(None)
        return script, step

    def _go_back(self) -> None:
        if not self._history:
            return
        if self._launch_after_id is not None:
            self.root.after_cancel(self._launch_after_id)
            self._launch_after_id = None
        self._history.pop()
        cut = self._answer_positions.pop()
        self._log = self._log[:cut]
        self._redraw_transcript()
        self._update_back_button()
        self.script, step = self._replay(self._history)
        self._render_input(step)

    def _reset(self) -> None:
        if self._launch_after_id is not None:
            self.root.after_cancel(self._launch_after_id)
            self._launch_after_id = None
        self._history = []
        self._answer_positions = []
        self._log = []
        self._redraw_transcript()
        self._update_back_button()
        self.script = conversation_script()
        self._advance(None)

    # ── free-text / number / date / secret entry ─────────────────────────
    def _render_entry(self, step: Step, mask: bool) -> None:
        tk = self.tk
        entry = tk.Entry(self.input_area, show="*" if mask else "")
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.focus_set()

        def submit(_event=None):
            raw = entry.get()
            display = "*" * len(raw) if mask else (raw or "(blank)")
            self._submit(display, raw)

        entry.bind("<Return>", submit)
        send_btn = tk.Button(self.input_area, text="Send", command=submit)
        send_btn.pack(side="left", padx=(6, 0))

    # ── single choice / confirm ──────────────────────────────────────────
    def _render_buttons(self, choices: list, on_click: Callable) -> None:
        tk = self.tk
        row = tk.Frame(self.input_area)
        row.pack(fill="x")
        for value, label in choices:
            btn = tk.Button(row, text=label, command=lambda v=value, l=label: on_click(v, l))
            btn.pack(side="left", padx=4, pady=2)

    def _submit_choice(self, value: str, label: str) -> None:
        self._submit(label, value)

    def _submit_confirm(self, value: str, label: str) -> None:
        self._submit(label, value == "__yes__")

    # ── ordered multi-choice (class priority, WL types) ──────────────────
    def _render_multi(self, step: Step) -> None:
        tk = self.tk
        self._multi_selected = list(step.default or [])

        status = tk.Label(self.input_area, text=self._multi_status_text(), anchor="w")
        status.pack(fill="x")

        grid = tk.Frame(self.input_area)
        grid.pack(fill="x")
        for i, (value, label) in enumerate(step.choices):
            btn = tk.Button(
                grid, text=label,
                command=lambda v=value: self._toggle_multi(v, status),
            )
            btn.grid(row=i // 6, column=i % 6, padx=3, pady=3, sticky="ew")

        controls = tk.Frame(self.input_area)
        controls.pack(fill="x", pady=(4, 0))
        tk.Button(controls, text="Remove last",
                  command=lambda: self._remove_last_multi(status)).pack(side="left")
        tk.Button(controls, text="Done",
                  command=self._submit_multi).pack(side="right")

    def _multi_status_text(self) -> str:
        return "Selected: " + (", ".join(self._multi_selected) or "(none yet)")

    def _toggle_multi(self, value: str, status_label) -> None:
        if value not in self._multi_selected:
            self._multi_selected.append(value)
        status_label.config(text=self._multi_status_text())

    def _remove_last_multi(self, status_label) -> None:
        if self._multi_selected:
            self._multi_selected.pop()
        status_label.config(text=self._multi_status_text())

    def _submit_multi(self) -> None:
        if not self._multi_selected:
            return  # require at least one — Done is a no-op until then
        self._submit(", ".join(self._multi_selected), list(self._multi_selected))

    # ── hand-off to the real booking engine ──────────────────────────────
    def _start_booking(self, config: BookingConfig) -> None:
        login_time, window_time = calculate_booking_times(config)
        if config.quota in TATKAL_QUOTAS:
            when = window_time.strftime("%H:%M:%S IST on %d %b %Y")
            msg = f"Booking window: {when}. I'll wait for it and fire the moment it opens."
        else:
            msg = "Non-Tatkal quota — starting the booking right away, no wait needed."

        self._append("Agent",
            f"{msg}\n\nA browser window will open now. This chat window will close — "
            "watch the console window behind it for anything I need you to do "
            "(logging in, CAPTCHA, OTP)."
        )
        self._clear_input_area()
        self.root.update()
        self._launch_after_id = self.root.after(1500, lambda: self._launch(config, window_time))

    def _launch(self, config: BookingConfig, window_time: datetime) -> None:
        self.root.destroy()
        # Once the chat window is destroyed, Tkinter's own exception
        # reporting (which needs a live root) can no longer surface a
        # crash here — without this try/except, any error before the
        # browser opens fails completely silently (confirmed live
        # 2026-08-18: a missing constructor arg crashed here and nothing
        # was printed anywhere the user could see). Belt-and-suspenders on
        # top of fixing the actual bug: never let this path go silent again.
        try:
            asyncio.run(_run_booking(config, window_time))
        except Exception:
            import traceback
            print("\n" + "=" * 60)
            print("  Something went wrong starting the booking engine:")
            traceback.print_exc()
            print("=" * 60)
            input("\nPress Enter to close this window: ")


def main() -> None:
    import tkinter as tk
    root = tk.Tk()
    ChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
