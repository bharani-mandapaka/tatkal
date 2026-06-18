from core.availability_parser import parse_availability, evaluate_threshold, AvailabilityResult
from core.models import BookingThresholds


# ── parse_availability ────────────────────────────────────────────────────────

def test_available_with_count():
    r = parse_availability("AVAILABLE-4")
    assert r.status_type == "AVAILABLE"
    assert r.is_bookable is True
    assert r.confirmed_count == 4


def test_available_no_count():
    r = parse_availability("AVAILABLE")
    assert r.status_type == "AVAILABLE"
    assert r.is_bookable is True
    assert r.confirmed_count is None


def test_curr_avbl():
    r = parse_availability("CURR_AVBL")
    assert r.status_type == "CURR_AVBL"
    assert r.is_bookable is True


def test_curr_avbl_with_count():
    r = parse_availability("CURR_AVBL-3")
    assert r.status_type == "CURR_AVBL"
    assert r.confirmed_count == 3


def test_rac():
    r = parse_availability("RAC 7")
    assert r.status_type == "RAC"
    assert r.is_bookable is True
    assert r.rac_number == 7


def test_gnwl():
    r = parse_availability("GNWL 45/WL 30")
    assert r.status_type == "GNWL"
    assert r.is_bookable is True
    assert r.wl_total == 45
    assert r.wl_position == 30


def test_rlwl():
    r = parse_availability("RLWL 5/WL 3")
    assert r.status_type == "RLWL"
    assert r.wl_total == 5
    assert r.wl_position == 3


def test_tqwl():
    r = parse_availability("TQWL 3/WL 2")
    assert r.status_type == "TQWL"
    assert r.wl_position == 2


def test_pqwl():
    r = parse_availability("PQWL 12/WL 8")
    assert r.status_type == "PQWL"


def test_rswl():
    r = parse_availability("RSWL 1/WL 1")
    assert r.status_type == "RSWL"


def test_regret():
    r = parse_availability("REGRET")
    assert r.status_type == "REGRET"
    assert r.is_bookable is False


def test_not_available():
    r = parse_availability("NOT AVAILABLE")
    assert r.status_type == "NOT_AVAILABLE"
    assert r.is_bookable is False


def test_train_cancelled():
    r = parse_availability("TRAIN CANCELLED")
    assert r.status_type == "TRAIN_CANCELLED"
    assert r.is_bookable is False


def test_empty_string():
    r = parse_availability("")
    assert r.is_bookable is False


# ── evaluate_threshold — confirmed-only defaults ──────────────────────────────

def _default_thresholds() -> BookingThresholds:
    return BookingThresholds()   # max_rac=None, max_wl=None


def test_available_always_books():
    assert evaluate_threshold(parse_availability("AVAILABLE-4"), _default_thresholds()) == "book"


def test_curr_avbl_always_books():
    assert evaluate_threshold(parse_availability("CURR_AVBL"), _default_thresholds()) == "book"


def test_rac_skipped_by_default():
    assert evaluate_threshold(parse_availability("RAC 2"), _default_thresholds()) == "skip"


def test_gnwl_skipped_by_default():
    assert evaluate_threshold(parse_availability("GNWL 10/WL 5"), _default_thresholds()) == "skip"


def test_regret_skipped():
    assert evaluate_threshold(parse_availability("REGRET"), _default_thresholds()) == "skip"


# ── evaluate_threshold — with thresholds ─────────────────────────────────────

def _rac_threshold(max_rac: int, buffer: int = 2) -> BookingThresholds:
    return BookingThresholds(max_rac=max_rac, borderline_buffer=buffer)


def test_rac_within_limit_no_buffer_books():
    # buffer=0 means no pause zone — any position at or below max goes straight to book
    t = _rac_threshold(max_rac=5, buffer=0)
    assert evaluate_threshold(parse_availability("RAC 3"), t) == "book"
    assert evaluate_threshold(parse_availability("RAC 5"), t) == "book"


def test_rac_beyond_limit_skips():
    t = _rac_threshold(max_rac=5, buffer=0)
    assert evaluate_threshold(parse_availability("RAC 6"), t) == "skip"


def test_rac_borderline_pauses():
    # buffer=2: pause if max_rac - rac < 2, i.e. diff is 0 or 1 → RAC 4 and RAC 5 pause
    t = _rac_threshold(max_rac=5, buffer=2)
    assert evaluate_threshold(parse_availability("RAC 4"), t) == "pause"  # diff=1 < 2
    assert evaluate_threshold(parse_availability("RAC 5"), t) == "pause"  # diff=0 < 2
    assert evaluate_threshold(parse_availability("RAC 3"), t) == "book"   # diff=2, not < 2


def test_wl_allowed_type_books():
    t = BookingThresholds(max_wl=20, allowed_wl_types=["GNWL"])
    assert evaluate_threshold(parse_availability("GNWL 10/WL 8"), t) == "book"


def test_wl_disallowed_type_skips():
    t = BookingThresholds(max_wl=20, allowed_wl_types=["GNWL"])
    assert evaluate_threshold(parse_availability("TQWL 3/WL 2"), t) == "skip"


def test_wl_beyond_max_skips():
    t = BookingThresholds(max_wl=10, allowed_wl_types=["GNWL"])
    assert evaluate_threshold(parse_availability("GNWL 30/WL 15"), t) == "skip"


def test_wl_borderline_pauses():
    # buffer=2: pause if max_wl - wl_pos < 2, i.e. diff is 0 or 1 → WL 9,10 pause
    t = BookingThresholds(max_wl=10, borderline_buffer=2, allowed_wl_types=["GNWL"])
    assert evaluate_threshold(parse_availability("GNWL 20/WL 9"), t) == "pause"   # diff=1 < 2
    assert evaluate_threshold(parse_availability("GNWL 20/WL 10"), t) == "pause"  # diff=0 < 2
    assert evaluate_threshold(parse_availability("GNWL 20/WL 8"), t) == "book"    # diff=2, not < 2
