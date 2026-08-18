"""
Tests for chat_ui._parse_natural_date() — the free-form date parser that
lets the chat window accept however someone actually types a date ('18 Aug',
'tomorrow', '18/08/2026', ...) instead of demanding one rigid format.

A wrong parse here means booking the wrong day entirely, so this gets
thorough direct coverage rather than just being exercised incidentally
through the conversation script. `today` is always passed explicitly so
these tests are not calendar-date-dependent.
"""
from datetime import date

from chat_ui import _parse_natural_date

_TODAY = date(2026, 8, 18)  # a Tuesday


def _p(raw: str) -> str | None:
    return _parse_natural_date(raw, today=_TODAY)


# ── Relative terms ──────────────────────────────────────────────────────────

def test_today():
    assert _p("today") == "18-08-2026"


def test_tomorrow():
    assert _p("tomorrow") == "19-08-2026"


def test_tomorrow_abbreviations():
    assert _p("tmrw") == "19-08-2026"
    assert _p("tmrrw") == "19-08-2026"


def test_day_after_tomorrow():
    assert _p("day after tomorrow") == "20-08-2026"
    assert _p("day after") == "20-08-2026"


def test_relative_terms_are_case_insensitive():
    assert _p("Tomorrow") == "19-08-2026"
    assert _p("TODAY") == "18-08-2026"


# ── Weekday names ────────────────────────────────────────────────────────────

def test_weekday_name_gives_next_occurrence():
    # _TODAY is a Tuesday (2026-08-18). "Friday" -> 2026-08-21.
    assert _p("friday") == "21-08-2026"


def test_weekday_name_same_as_today_means_next_week():
    assert _p("tuesday") == "25-08-2026"


def test_next_and_this_weekday_prefixes():
    assert _p("next friday") == "21-08-2026"
    assert _p("this friday") == "21-08-2026"


# ── Numeric formats — day-first throughout ──────────────────────────────────

def test_dd_mm_yyyy_dash():
    assert _p("18-08-2026") == "18-08-2026"


def test_dd_mm_yyyy_slash():
    assert _p("18/08/2026") == "18-08-2026"


def test_dd_mm_yyyy_dot():
    assert _p("18.08.2026") == "18-08-2026"


def test_dd_mm_two_digit_year():
    assert _p("18/08/26") == "18-08-2026"


def test_dd_mm_no_year_upcoming_this_year():
    # 25 Aug hasn't happened yet relative to 18 Aug -> this year
    assert _p("25/08") == "25-08-2026"


def test_dd_mm_no_year_already_passed_rolls_to_next_year():
    # 1 Jan is before 18 Aug -> must roll forward to next year, not book the past
    assert _p("01/01") == "01-01-2027"


def test_single_digit_day_and_month_no_leading_zero():
    assert _p("5/9") == "05-09-2026"


def test_iso_format():
    assert _p("2026-08-25") == "25-08-2026"


# ── Month-name formats ───────────────────────────────────────────────────────

def test_day_then_month_name_short():
    assert _p("18 aug") == "18-08-2026"


def test_day_then_month_name_long():
    assert _p("18 august") == "18-08-2026"


def test_month_name_then_day():
    assert _p("aug 18") == "18-08-2026"


def test_day_month_name_year():
    assert _p("18 aug 2026") == "18-08-2026"


def test_day_month_name_comma_year():
    assert _p("18 aug, 2026") == "18-08-2026"


def test_month_name_case_insensitive():
    assert _p("18 AUGUST") == "18-08-2026"
    assert _p("Aug 18") == "18-08-2026"


def test_month_name_no_year_rolls_to_next_year_if_passed():
    assert _p("5 jan") == "05-01-2027"


# ── Whitespace / formatting tolerance ────────────────────────────────────────

def test_extra_whitespace_tolerated():
    assert _p("  18   aug   2026  ") == "18-08-2026"


# ── Rejections — must return None, never guess ───────────────────────────────

def test_garbage_returns_none():
    assert _p("not-a-date") is None
    assert _p("") is None
    assert _p("   ") is None


def test_invalid_month_number_returns_none():
    assert _p("18/13/2026") is None


def test_invalid_day_returns_none():
    assert _p("32/08/2026") is None
    assert _p("31 feb 2026") is None


def test_unknown_month_name_returns_none():
    assert _p("18 blorptember") is None


def test_random_words_return_none():
    assert _p("whenever") is None
    assert _p("soon") is None
