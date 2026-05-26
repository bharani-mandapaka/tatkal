from core.models import (
    BookingConfig, TravelClass, TravelClass, Passenger,
    PaymentConfig, PaymentMethod, Gender, BerthPreference, IDType,
)


def _make_config(cls: TravelClass) -> BookingConfig:
    return BookingConfig(
        username="x", password="x", train_number="12951",
        from_station="NDLS", to_station="MAS",
        journey_date="27-05-2026", travel_class=cls,
        passengers=[], mobile="9999999999",
        payment=PaymentConfig(method=PaymentMethod.UPI, upi_id="x@upi"),
    )


def test_passenger_name_truncated_at_15():
    p = Passenger(
        name="Subrahmanyam Venkataraman",
        age=30,
        gender=Gender.MALE,
        berth_preference=BerthPreference.LOWER,
        id_type=IDType.AADHAAR,
        id_number="1234-5678-9012",
    )
    assert len(p.name) == 15
    assert p.name == "Subrahmanyam Ve"


def test_passenger_name_within_limit_unchanged():
    p = Passenger(
        name="Bharani",
        age=33,
        gender=Gender.MALE,
        berth_preference=BerthPreference.LOWER,
        id_type=IDType.AADHAAR,
        id_number="1234-5678-9012",
    )
    assert p.name == "Bharani"


def test_ac_classes_detected():
    ac_classes = [
        TravelClass.ONE_A, TravelClass.TWO_A, TravelClass.THREE_A,
        TravelClass.THREE_E, TravelClass.CC, TravelClass.EC,
    ]
    for cls in ac_classes:
        assert _make_config(cls).is_ac_class, f"{cls} should be AC"


def test_non_ac_classes_detected():
    non_ac = [TravelClass.SL, TravelClass.TWO_S]
    for cls in non_ac:
        assert not _make_config(cls).is_ac_class, f"{cls} should NOT be AC"


def test_payment_clear_sensitive_zeroes_fields():
    pc = PaymentConfig(
        method=PaymentMethod.CARD,
        card_cvv="123",
        wallet_mpin="4321",
    )
    pc.clear_sensitive()
    assert pc.card_cvv == ""
    assert pc.wallet_mpin == ""


def test_payment_clear_sensitive_upi_is_noop():
    pc = PaymentConfig(method=PaymentMethod.UPI, upi_id="me@upi")
    pc.clear_sensitive()
    assert pc.upi_id == "me@upi"  # unchanged — not sensitive in same way
