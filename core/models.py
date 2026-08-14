from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from logger import get_logger

log = get_logger()


class TravelClass(str, Enum):
    SL = "SL"
    CC = "CC"
    EC = "EC"
    TWO_S = "2S"
    ONE_A = "1A"
    TWO_A = "2A"
    THREE_A = "3A"
    THREE_E = "3E"


class Gender(str, Enum):
    MALE = "M"
    FEMALE = "F"
    TRANSGENDER = "T"


class BerthPreference(str, Enum):
    LOWER = "LB"
    MIDDLE = "MB"
    UPPER = "UB"
    SIDE_LOWER = "SL"
    SIDE_UPPER = "SU"
    NO_PREFERENCE = "NO PREFERENCE"


class IDType(str, Enum):
    AADHAAR = "AADHAAR CARD"
    PAN = "PAN CARD"
    VOTER = "VOTER ID CARD"
    PASSPORT = "PASSPORT"
    DRIVING = "DRIVING LICENCE"


class PaymentMethod(str, Enum):
    UPI = "UPI"
    CARD = "CARD"
    EWALLET = "EWALLET"


@dataclass
class Passenger:
    name: str
    age: int
    gender: Gender
    berth_preference: BerthPreference
    id_type: IDType
    id_number: str

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("Passenger name cannot be empty")
        if not 0 <= self.age <= 125:
            raise ValueError(
                f"Passenger age {self.age} is out of range (0-125) for {self.name!r}"
            )
        if len(self.name) > 15:
            # IRCTC truncates to 15 chars silently — surface it here instead,
            # since a truncated name can fail to match the passenger's ID at
            # boarding (TTE checks name-on-ticket against the ID document).
            original = self.name
            self.name = self.name[:15]
            print(f"  [!] Passenger name truncated to fit IRCTC's 15-char limit: "
                  f"{original!r} -> {self.name!r} — verify this still matches the ID.")
            log.warning("passenger_name_truncated", original=original, truncated=self.name)


@dataclass
class PaymentConfig:
    method: PaymentMethod
    upi_id: Optional[str] = None
    wallet_mpin: Optional[str] = None
    card_number: Optional[str] = None
    card_expiry: Optional[str] = None  # MM/YY
    card_cvv: Optional[str] = None

    def clear_sensitive(self):
        """Zero all sensitive payment fields after a payment attempt."""
        if self.wallet_mpin:
            self.wallet_mpin = ""
        if self.card_cvv:
            self.card_cvv = ""
        if self.card_number:
            self.card_number = ""
        if self.card_expiry:
            self.card_expiry = ""


@dataclass
class BookingThresholds:
    """
    Controls which availability statuses the agent will book without user input.
    Defaults: only confirmed (AVAILABLE / CURR_AVBL) — no RAC, no WL.
    """
    max_rac: int | None = None              # None = never book RAC
    max_wl: int | None = None               # None = never book WL
    borderline_buffer: int = 2              # pause for user Y/N if within this many of limit
    allowed_wl_types: list = field(default_factory=list)  # e.g. ["GNWL", "RLWL"]


@dataclass
class BookingConfig:
    username: str
    password: str
    train_number: str
    from_station: str
    to_station: str
    journey_date: str  # DD-MM-YYYY
    travel_class: TravelClass
    passengers: List[Passenger] = field(default_factory=list)
    mobile: str = ""
    payment: Optional[PaymentConfig] = None
    boarding_point: Optional[str] = None
    book_only_if_confirmed: bool = True
    # Automated login can get blocked by IRCTC's anti-bot detection at the
    # auth endpoint (confirmed live 2026-08-14). When True, a human logs in
    # themselves in the browser window instead of the agent typing
    # username/password. `password` may be left empty when this is set.
    manual_login: bool = False
    captcha_api_key: Optional[str] = None
    quota: str = "TATKAL"  # "TATKAL", "PREMIUM TATKAL", "GENERAL", "LADIES", etc.

    # 5-stage workflow fields
    class_priority: list = field(default_factory=list)      # e.g. ["SL", "3A", "2A"]
    thresholds: BookingThresholds = field(default_factory=BookingThresholds)

    # Admin HITL: WhatsApp number that receives CAPTCHA images and has 10s to reply.
    # For personal use this is the same as the passenger's number.
    # For a shared service this is the operator's number.
    admin_phone: Optional[str] = None

    # Hard timeout for the admin to solve CAPTCHA via WhatsApp.
    # 2captcha (5–8s) is always attempted first; this is the fallback cutoff.
    captcha_hitl_timeout_s: int = 10

    @property
    def is_ac_class(self) -> bool:
        return self.travel_class in (
            TravelClass.ONE_A, TravelClass.TWO_A, TravelClass.THREE_A,
            TravelClass.THREE_E, TravelClass.CC, TravelClass.EC,
        )
