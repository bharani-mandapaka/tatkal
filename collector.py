"""Interactive CLI to collect and encrypt booking details."""
import questionary
from questionary import Style

from core.models import TravelClass, Gender, BerthPreference, IDType, PaymentMethod
from config import save_config

_STYLE = Style([
    ("qmark", "fg:#673ab7 bold"),
    ("question", "bold"),
    ("answer", "fg:#f44336 bold"),
    ("pointer", "fg:#673ab7 bold"),
    ("highlighted", "fg:#673ab7 bold"),
    ("selected", "fg:#cc5454"),
    ("instruction", "fg:#858585"),
])


def collect() -> None:
    print("\nTatkal Agent — Data Collector")
    print("─" * 40)
    print("Run this once before booking day.\n")

    # ── IRCTC credentials ──────────────────────────────────────────────────────
    username = questionary.text("IRCTC Username:", style=_STYLE).ask()
    password = questionary.password("IRCTC Password:", style=_STYLE).ask()

    # ── Journey details ────────────────────────────────────────────────────────
    train_number = questionary.text("Train number (e.g. 12951):", style=_STYLE).ask()
    from_station = questionary.text("From station code (e.g. NDLS):", style=_STYLE).ask().upper()
    to_station = questionary.text("To station code (e.g. MAS):", style=_STYLE).ask().upper()
    journey_date = questionary.text("Date of journey (DD-MM-YYYY):", style=_STYLE).ask()

    travel_class = questionary.select(
        "Travel class:",
        choices=[c.value for c in TravelClass],
        style=_STYLE,
    ).ask()

    boarding_point = (
        questionary.text(
            f"Boarding point (leave blank for {from_station}):", style=_STYLE
        ).ask().upper()
        or from_station
    )

    # ── Passengers ────────────────────────────────────────────────────────────
    num = int(
        questionary.select("Number of passengers:", choices=["1", "2", "3", "4"], style=_STYLE).ask()
    )
    passengers = []
    for i in range(num):
        print(f"\n  Passenger {i + 1}")
        name = questionary.text("  Full name (max 15 chars):", style=_STYLE).ask()
        if len(name) > 15:
            print(f"  ⚠  Name truncated to: {name[:15]}")
            name = name[:15]

        age = int(questionary.text("  Age:", style=_STYLE).ask())

        gender = questionary.select(
            "  Gender:",
            choices=[g.value for g in Gender],
            style=_STYLE,
        ).ask()

        berth = questionary.select(
            "  Berth preference:",
            choices=[b.value for b in BerthPreference],
            style=_STYLE,
        ).ask()

        id_type = questionary.select(
            "  ID type (mandatory for Tatkal):",
            choices=[t.value for t in IDType],
            style=_STYLE,
        ).ask()

        id_number = questionary.text("  ID number:", style=_STYLE).ask()

        passengers.append({
            "name": name,
            "age": age,
            "gender": gender,
            "berth_preference": berth,
            "id_type": id_type,
            "id_number": id_number,
        })

    # ── Contact ────────────────────────────────────────────────────────────────
    mobile = questionary.text("Mobile number (for SMS):", style=_STYLE).ask()

    # ── Payment ────────────────────────────────────────────────────────────────
    payment_method = questionary.select(
        "Payment method:",
        choices=[
            questionary.Choice("IRCTC e-Wallet (fully automated)", PaymentMethod.EWALLET.value),
            questionary.Choice("UPI (approve on phone)", PaymentMethod.UPI.value),
            questionary.Choice("Credit/Debit Card (OTP via terminal)", PaymentMethod.CARD.value),
        ],
        style=_STYLE,
    ).ask()

    payment: dict = {"method": payment_method}
    if payment_method == PaymentMethod.UPI.value:
        payment["upi_id"] = questionary.text("UPI ID (e.g. name@upi):", style=_STYLE).ask()
    elif payment_method == PaymentMethod.EWALLET.value:
        payment["wallet_mpin"] = questionary.password("IRCTC Wallet MPIN:", style=_STYLE).ask()
    elif payment_method == PaymentMethod.CARD.value:
        payment["card_number"] = questionary.text("Card number:", style=_STYLE).ask()
        payment["card_expiry"] = questionary.text("Expiry (MM/YY):", style=_STYLE).ask()
        payment["card_cvv"] = questionary.password("CVV:", style=_STYLE).ask()

    # ── Options ────────────────────────────────────────────────────────────────
    book_only_if_confirmed = questionary.confirm(
        "Book only if confirmed seats available? (Recommended: Yes)",
        default=True,
        style=_STYLE,
    ).ask()

    captcha_api_key = questionary.text(
        "2captcha API key (leave blank for manual CAPTCHA):",
        style=_STYLE,
    ).ask() or None

    # ── Passphrase + save ──────────────────────────────────────────────────────
    print()
    passphrase = questionary.password(
        "Set passphrase to encrypt your config:", style=_STYLE
    ).ask()
    confirm = questionary.password("Confirm passphrase:", style=_STYLE).ask()

    if passphrase != confirm:
        print("\n✗ Passphrases do not match — run collector again.\n")
        return

    save_config(
        {
            "username": username,
            "password": password,
            "train_number": train_number,
            "from_station": from_station,
            "to_station": to_station,
            "journey_date": journey_date,
            "travel_class": travel_class,
            "boarding_point": boarding_point,
            "passengers": passengers,
            "mobile": mobile,
            "payment": payment,
            "book_only_if_confirmed": book_only_if_confirmed,
            "captcha_api_key": captcha_api_key,
        },
        passphrase,
    )

    print("\n✅ Config saved to booking_config.enc")
    print("   Run 'python main.py check' to verify everything is ready.")
    print("   Run 'python main.py run' the morning before your journey date.\n")
