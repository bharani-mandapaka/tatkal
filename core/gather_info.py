"""
Stage 1: interactive CLI questionnaire.

Returns (BookingConfig, window_time) ready to hand to BookingFlow.
No encrypted config files — credentials live only in memory.
"""
import getpass
import re
from datetime import datetime, time

from core.models import (
    BookingConfig, BookingThresholds, Passenger, PaymentConfig,
    TravelClass, Gender, BerthPreference, IDType, PaymentMethod,
)


# ── Display helpers ────────────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    """Prompt with optional default."""
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def _ask_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt}: ")


def _choose(prompt: str, options: list[tuple[str, str]], default: str = "") -> str:
    """
    options: list of (value, display_label)
    Returns the chosen value.
    """
    print(f"\n{prompt}")
    for i, (val, label) in enumerate(options, 1):
        marker = " *" if val == default else ""
        print(f"  {i}. {label}{marker}")
    while True:
        raw = input(f"Choice [1-{len(options)}]{f' [{default}]' if default else ''}: ").strip()
        if not raw and default:
            return default
        try:
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1][0]
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {len(options)}.")


def _ask_date(prompt: str) -> str:
    """Return DD-MM-YYYY after validation."""
    while True:
        raw = input(f"{prompt} (DD-MM-YYYY): ").strip()
        try:
            dt = datetime.strptime(raw, "%d-%m-%Y")
            if dt.date() < datetime.today().date():
                print("  Journey date must be today or in the future.")
                continue
            return raw
        except ValueError:
            print("  Invalid date. Use DD-MM-YYYY (e.g. 15-06-2026).")


def _ask_int(prompt: str, lo: int, hi: int, default: int | None = None) -> int:
    suffix = f" [{default}]" if default is not None else f" ({lo}-{hi})"
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            n = int(raw)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        print(f"  Enter a number between {lo} and {hi}.")


def _ask_yn(prompt: str, default: bool = False) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{default_str}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Enter y or n.")


# ── Section gatherers ──────────────────────────────────────────────────────────

def _gather_journey() -> dict:
    print("\n━━━ Journey Details ━━━")
    train_number = _ask("Train number (e.g. 17644)").upper()
    from_station = _ask("From station code (e.g. MAS)").upper()
    to_station   = _ask("To station code (e.g. CGL)").upper()
    journey_date = _ask_date("Journey date")

    quota = _choose("Quota", [
        ("TATKAL",          "Tatkal"),
        ("PREMIUM TATKAL",  "Premium Tatkal"),
        ("GENERAL",         "General (non-Tatkal)"),
        ("LADIES",          "Ladies"),
    ], default="TATKAL")

    return dict(
        train_number=train_number,
        from_station=from_station,
        to_station=to_station,
        journey_date=journey_date,
        quota=quota,
    )


def _gather_class_priority() -> list[str]:
    print("\n━━━ Class Priority ━━━")
    print("Enter preferred classes in order (e.g. SL 3A 2A).")
    print("Available: SL  2S  CC  EC  3E  3A  2A  1A")
    valid = {c.value for c in TravelClass}
    while True:
        raw = input("Classes (space-separated): ").upper().strip()
        if not raw:
            print("  At least one class is required.")
            continue
        parts = raw.split()
        bad = [p for p in parts if p not in valid]
        if bad:
            print(f"  Unknown class(es): {', '.join(bad)}. Use: {', '.join(sorted(valid))}")
            continue
        return parts


def _gather_window_time(classes: list[str]) -> time | None:
    """Returns a time override if the user wants one, else None (auto-detect)."""
    # Detect default from class
    ac_classes = {"1A", "2A", "3A", "3E", "CC", "EC"}
    default_time = "10:00:00" if any(c in ac_classes for c in classes) else "11:00:00"
    print(f"\n━━━ Booking Window ━━━")
    print(f"  Auto-detected window: {default_time}")
    override = _ask_yn("Override the booking window time?", default=False)
    if not override:
        return None
    while True:
        raw = input("  Window time (HH:MM:SS, 24h): ").strip()
        try:
            h, m, s = map(int, raw.split(":"))
            return time(h, m, s)
        except Exception:
            print("  Use HH:MM:SS format, e.g. 10:00:30")


def _gather_passenger(n: int) -> Passenger:
    print(f"\n  ── Passenger {n} ──")
    name = ""
    while not name:
        raw = _ask("  Name (max 15 chars, as on ID)")
        name = raw[:15].strip()
        if not name:
            print("  Name is required.")
    age = _ask_int("  Age", 1, 120)

    gender_val = _choose("  Gender", [
        ("M", "Male"),
        ("F", "Female"),
        ("T", "Transgender"),
    ])
    gender = Gender(gender_val)

    berth_val = _choose("  Berth preference", [
        ("LB",           "Lower"),
        ("MB",           "Middle"),
        ("UB",           "Upper"),
        ("SL",           "Side Lower"),
        ("SU",           "Side Upper"),
        ("NO PREFERENCE","No Preference"),
    ], default="LB")
    berth = BerthPreference(berth_val)

    id_type_val = _choose("  ID type (Tatkal mandatory)", [
        ("AADHAAR CARD",   "Aadhaar Card"),
        ("PAN CARD",       "PAN Card"),
        ("VOTER ID CARD",  "Voter ID Card"),
        ("PASSPORT",       "Passport"),
        ("DRIVING LICENCE","Driving Licence"),
    ])
    id_type = IDType(id_type_val)
    id_number = _ask("  ID number")

    return Passenger(
        name=name, age=age, gender=gender,
        berth_preference=berth, id_type=id_type, id_number=id_number,
    )


def _gather_payment() -> PaymentConfig:
    print("\n━━━ Payment ━━━")
    method_val = _choose("Payment method", [
        ("UPI",     "UPI (collect request sent to your app)"),
        ("EWALLET", "IRCTC e-Wallet (auto, no action needed)"),
        ("CARD",    "Debit / Credit Card (OTP required)"),
    ])
    method = PaymentMethod(method_val)

    if method == PaymentMethod.UPI:
        upi_id = _ask("UPI ID (e.g. you@upi)")
        return PaymentConfig(method=method, upi_id=upi_id)

    if method == PaymentMethod.EWALLET:
        mpin = _ask_secret("e-Wallet MPIN")
        return PaymentConfig(method=method, wallet_mpin=mpin)

    # Card
    card_number = _ask("Card number (no spaces)")
    card_expiry = _ask("Expiry (MM/YY)")
    card_cvv    = _ask_secret("CVV")
    return PaymentConfig(
        method=method,
        card_number=card_number,
        card_expiry=card_expiry,
        card_cvv=card_cvv,
    )


def _gather_thresholds() -> BookingThresholds:
    print("\n━━━ Booking Thresholds ━━━")
    print("  Default: book ONLY when tickets are AVAILABLE or CURR_AVBL.")
    print("  RAC and waitlists are skipped unless you enable them here.")
    if not _ask_yn("Configure thresholds (RAC / WL)?", default=False):
        return BookingThresholds()  # confirmed-only defaults

    max_rac = None
    if _ask_yn("  Allow RAC?", default=False):
        max_rac = _ask_int("  Maximum RAC position to accept", 1, 99, default=4)

    max_wl = None
    allowed_wl_types: list[str] = []

    if _ask_yn("  Allow Waitlist?", default=False):
        max_wl = _ask_int("  Maximum WL position to accept", 1, 200, default=10)
        print("  WL types to allow (leave blank to skip):")
        wl_options = [
            ("GNWL", "GNWL — origin quota, best cancellation odds"),
            ("RLWL", "RLWL — remote-to-junction leg quota"),
            ("WL",   "Generic WL"),
            ("PQWL", "PQWL — point-to-point short trip"),
            ("TQWL", "TQWL — Tatkal quota WL (very low odds)"),
            ("RSWL", "RSWL — roadside station (near-zero odds)"),
        ]
        for val, label in wl_options:
            if _ask_yn(f"    Allow {label}?", default=(val == "GNWL")):
                allowed_wl_types.append(val)

    buffer = _ask_int(
        "  Borderline buffer (pause if within N of your limit)", 0, 10, default=2
    )
    return BookingThresholds(
        max_rac=max_rac,
        max_wl=max_wl,
        borderline_buffer=buffer,
        allowed_wl_types=allowed_wl_types,
    )


# ── Main entry point ───────────────────────────────────────────────────────────

def gather_info_interactive() -> tuple[BookingConfig, time | None]:
    """
    Run the full interactive questionnaire and return
    (BookingConfig, window_time_override).

    window_time_override is None to use the auto-detected time (10:00 AC /
    11:00 non-AC), or a datetime.time to override it.
    """
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("    TATKAL AGENT — Booking Setup")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Credentials stay in memory only — never written to disk.\n")

    print("━━━ IRCTC Credentials ━━━")
    username = _ask("Username")
    manual_login = _ask_yn(
        "Log in yourself when the browser opens, instead of the agent typing "
        "your password? (Recommended — automated login can get blocked by "
        "IRCTC's bot detection)",
        default=True,
    )
    password = "" if manual_login else _ask_secret("Password")

    journey = _gather_journey()
    classes = _gather_class_priority()
    window_time_override = _gather_window_time(classes)

    print("\n━━━ Passengers ━━━")
    num_pax = _ask_int("Number of passengers", 1, 4, default=1)
    passengers = [_gather_passenger(n + 1) for n in range(num_pax)]

    print("\n━━━ Contact ━━━")
    mobile = _ask("Mobile number (10 digits, for booking SMS)")

    payment = _gather_payment()
    thresholds = _gather_thresholds()

    # first class in priority list is the initial travel_class
    try:
        initial_class = TravelClass(classes[0])
    except ValueError:
        initial_class = TravelClass.SL

    config = BookingConfig(
        username=username,
        password=password,
        train_number=journey["train_number"],
        from_station=journey["from_station"],
        to_station=journey["to_station"],
        journey_date=journey["journey_date"],
        travel_class=initial_class,
        quota=journey["quota"],
        passengers=passengers,
        mobile=mobile,
        payment=payment,
        class_priority=classes,
        thresholds=thresholds,
        manual_login=manual_login,
    )

    _print_summary(config, window_time_override)

    while not _ask_yn("\nAll details correct? Proceed to login?", default=True):
        print("Restart to re-enter details (Ctrl+C to cancel).")
        return gather_info_interactive()

    return config, window_time_override


def _print_summary(config: BookingConfig, window_time: time | None) -> None:
    ac = {"1A", "2A", "3A", "3E", "CC", "EC"}
    auto_window = "10:00:00" if any(c in ac for c in config.class_priority) else "11:00:00"
    effective_window = window_time.strftime("%H:%M:%S") if window_time else auto_window

    print("\n" + "━" * 45)
    print("  BOOKING SUMMARY")
    print("━" * 45)
    print(f"  Login    {'Manual (you log in yourself)' if config.manual_login else 'Automated'}")
    print(f"  Train    {config.train_number}  {config.from_station} → {config.to_station}")
    print(f"  Date     {config.journey_date}  Quota: {config.quota}")
    print(f"  Classes  {' → '.join(config.class_priority)} (tries in order)")
    print(f"  Window   {effective_window}")
    print(f"  PAX      {len(config.passengers)}")
    for p in config.passengers:
        print(f"           {p.name}, {p.age}y, {p.gender.value}, {p.berth_preference.value}")
    print(f"  Payment  {config.payment.method.value}")
    t = config.thresholds
    if t.max_rac is None and t.max_wl is None:
        print("  Policy   Confirmed seats only (default)")
    else:
        parts = []
        if t.max_rac is not None:
            parts.append(f"RAC≤{t.max_rac}")
        if t.max_wl is not None:
            wl_types = ", ".join(t.allowed_wl_types) or "all types"
            parts.append(f"WL≤{t.max_wl} ({wl_types})")
        print(f"  Policy   {', '.join(parts)}")
    print("━" * 45)
