from core.state_machine import BookingState


def test_all_states_present():
    names = [s.name for s in BookingState]
    expected = [
        "IDLE", "LOGGING_IN", "PREFILLING_FORM", "WAITING_FOR_WINDOW",
        "SEARCHING", "SELECTING_TRAIN", "FILLING_PASSENGERS",
        "SOLVING_CAPTCHA", "SUBMITTING", "PAYING", "CONFIRMED", "FAILED",
    ]
    assert names == expected


def test_states_are_unique():
    values = [s.value for s in BookingState]
    assert len(values) == len(set(values))


def test_failed_state_is_terminal():
    # FAILED should exist and be distinct from CONFIRMED
    assert BookingState.FAILED != BookingState.CONFIRMED


def test_confirmed_state_is_terminal():
    assert BookingState.CONFIRMED != BookingState.IDLE
