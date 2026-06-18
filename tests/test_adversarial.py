"""
Runnable adversarial tests, driven by tests/fixtures_adversarial.py.

Covers the confident-batch fixes from the stress-test pass:
  - AVAILABLE-0 / short-count guard in evaluate_threshold
  - parser robustness against messy real-world badge strings
Passenger-validation cases are xfail (not yet implemented — see TASKS.md 🟡).
"""
import pytest

from core.availability_parser import (
    parse_availability,
    evaluate_threshold,
    AvailabilityResult,
)
from core.models import BookingThresholds, Passenger, Gender, BerthPreference, IDType

from tests.fixtures_adversarial import (
    AVAILABILITY_BADGES,
    THRESHOLD_CASES,
)


# ── 1. Parser robustness against messy badge strings ─────────────────────────
@pytest.mark.parametrize(
    "raw,expected_status,note",
    AVAILABILITY_BADGES,
    ids=[b[0] or "<empty>" for b in AVAILABILITY_BADGES],
)
def test_parse_badge_status(raw, expected_status, note):
    assert parse_availability(raw).status_type == expected_status, note


# ── 2. Threshold decisions, incl. the AVAILABLE-0 fix ────────────────────────
@pytest.mark.parametrize(
    "status_type,result_kwargs,thr_kwargs,expected,note",
    THRESHOLD_CASES,
    ids=[c[4][:40] for c in THRESHOLD_CASES],
)
def test_threshold_decision(status_type, result_kwargs, thr_kwargs, expected, note):
    result = AvailabilityResult(
        raw="x", status_type=status_type, is_bookable=True, **result_kwargs
    )
    thr = BookingThresholds(**thr_kwargs)
    assert evaluate_threshold(result, thr) == expected, note


# ── 3. The verified AVAILABLE-0 bug — explicit regression guards ─────────────
def test_available_zero_seats_skips():
    """AVAILABLE-0 (zero confirmed seats) must never book."""
    assert evaluate_threshold(parse_availability("AVAILABLE-0"), BookingThresholds()) == "skip"


def test_available_fewer_seats_than_passengers_pauses():
    """AVAILABLE-1 with 2 passengers → pause (would split the party)."""
    r = parse_availability("AVAILABLE-1")
    assert evaluate_threshold(r, BookingThresholds(), passenger_count=2) == "pause"


def test_available_enough_seats_books():
    r = parse_availability("AVAILABLE-4")
    assert evaluate_threshold(r, BookingThresholds(), passenger_count=2) == "book"


def test_passenger_count_ignored_when_count_unknown():
    """CURR_AVBL with no number → can't compare, still books."""
    r = parse_availability("CURR_AVBL")
    assert evaluate_threshold(r, BookingThresholds(), passenger_count=4) == "book"


# ── 4. Passenger input validation — documented gaps (not yet implemented) ─────
def _passenger(name="Test", age=30):
    return Passenger(
        name=name, age=age, gender=Gender.MALE,
        berth_preference=BerthPreference.LOWER,
        id_type=IDType.AADHAAR, id_number="123456789012",
    )


@pytest.mark.xfail(reason="age validation not yet implemented — TASKS.md 🟡", strict=False)
def test_passenger_rejects_negative_age():
    with pytest.raises((ValueError, AssertionError)):
        _passenger(age=-1)


@pytest.mark.xfail(reason="age validation not yet implemented — TASKS.md 🟡", strict=False)
def test_passenger_rejects_absurd_age():
    with pytest.raises((ValueError, AssertionError)):
        _passenger(age=150)


@pytest.mark.xfail(reason="empty-name validation not yet implemented — TASKS.md 🟡", strict=False)
def test_passenger_rejects_empty_name():
    with pytest.raises((ValueError, AssertionError)):
        _passenger(name="")
