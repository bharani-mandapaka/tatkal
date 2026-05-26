from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


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
        if len(self.name) > 15:
            self.name = self.name[:15]


@dataclass
class PaymentConfig:
    method: PaymentMethod
    upi_id: Optional[str] = None
    wallet_mpin: Optional[str] = None
    card_number: Optional[str] = None
    card_expiry: Optional[str] = None  # MM/YY
    card_cvv: Optional[str] = None

    def clear_sensitive(self):
        """Zero sensitive fields after payment attempt."""
        if self.wallet_mpin:
            self.wallet_mpin = ""
        if self.card_cvv:
            self.card_cvv = ""


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
    captcha_api_key: Optional[str] = None
    quota: str = "TATKAL"  # "TATKAL", "PREMIUM TATKAL", "GENERAL", "LADIES", etc.

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
