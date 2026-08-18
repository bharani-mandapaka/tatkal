"""
Tests for chat_ui.py's conversation_script() — the pure, Tkinter-free
generator that drives the chat window. Driven the same way ChatApp does:
alternating `.send(answer)` calls, asserting the Step it yields back and the
final BookingConfig once it returns (via StopIteration.value).

This is what makes the chat UI testable without a display: all the
branching/validation logic lives in the generator, not in Tkinter callbacks.
"""
import pytest

from chat_ui import conversation_script, Step
from core.models import PaymentMethod
from scheduler import TATKAL_QUOTAS


def _send(script, value):
    """Send one answer, then auto-advance through any 'info' steps (which
    the real ChatApp driver resumes with None automatically) — mirrors
    _drive() but returns after the next REAL question, for tests that need
    to inspect intermediate steps."""
    step = script.send(value)
    while step.kind == "info":
        step = script.send(None)
    return step


def _drive(script, answers):
    """Send each answer in order, skipping over 'info' steps (which the
    real driver auto-advances with None). Returns (final_config, steps_seen)."""
    steps_seen = []
    step = script.send(None)  # prime
    steps_seen.append(step)
    i = 0
    while True:
        if step.kind == "info":
            try:
                step = script.send(None)
            except StopIteration as stop:
                return stop.value, steps_seen
            steps_seen.append(step)
            continue
        answer = answers[i]
        i += 1
        try:
            step = script.send(answer)
        except StopIteration as stop:
            return stop.value, steps_seen
        steps_seen.append(step)


def _happy_path_answers(quota="TATKAL", policy="CONFIRMED_ONLY"):
    """One passenger, UPI payment, confirmed-only policy, single class.
    Values that come from an Entry widget (text/number/date) are strings,
    matching what Tkinter's entry.get() actually returns — only choice/
    multi_choice/confirm answers are Python-native (str/list/bool), matching
    what button callbacks send."""
    answers = [
        "lavanya59",                    # username
        "17644",                        # train number
        "MAS",                          # from
        "CGL",                          # to
        "27-05-2099",                   # journey date (far future, always valid)
        quota,                          # quota (choice)
        ["SL"],                         # class priority (multi_choice)
        "1",                            # num passengers
        "Bharani M",                    # passenger 1 name
        "35",                           # age
        "M",                            # gender (choice)
        "LB",                           # berth (choice)
        "AADHAAR CARD",                 # id type (choice)
        "713341395482",                 # id number
        "9962820205",                   # mobile
        "UPI",                          # payment method (choice)
        "test@upi",                     # upi id
        policy,                         # booking policy (choice)
    ]
    return answers


# ── Happy path ────────────────────────────────────────────────────────────────

def test_happy_path_builds_correct_config():
    config, _ = _drive(conversation_script(), _happy_path_answers() + [True])  # confirm=True

    assert config is not None
    assert config.username == "lavanya59"
    assert config.train_number == "17644"
    assert config.from_station == "MAS"
    assert config.to_station == "CGL"
    assert config.quota == "TATKAL"
    assert config.class_priority == ["SL"]
    assert len(config.passengers) == 1
    assert config.passengers[0].name == "Bharani M"
    assert config.passengers[0].age == 35
    assert config.mobile == "9962820205"
    assert config.payment.method == PaymentMethod.UPI
    assert config.payment.upi_id == "test@upi"
    assert config.thresholds.max_rac is None
    assert config.thresholds.max_wl is None


def test_manual_login_always_true_and_password_empty():
    """The chat UI never collects a password — automated login is confirmed
    blocked, so manual_login is forced on, matching the recommended default."""
    config, _ = _drive(conversation_script(), _happy_path_answers() + [True])
    assert config.manual_login is True
    assert config.password == ""


def test_general_quota_is_accepted_and_stored():
    config, _ = _drive(conversation_script(), _happy_path_answers(quota="GENERAL") + [True])
    assert config.quota == "GENERAL"
    assert config.quota not in TATKAL_QUOTAS


# ── Cancellation ─────────────────────────────────────────────────────────────

def test_declining_final_confirm_returns_none():
    config, _ = _drive(conversation_script(), _happy_path_answers() + [False])
    assert config is None


# ── Validation retry loops ──────────────────────────────────────────────────

def test_invalid_age_reprompts_before_accepting_valid_one():
    script = conversation_script()
    step = script.send(None)   # welcome (info)
    step = _send(script, None)                 # -> username question
    step = _send(script, "lavanya59")           # -> train number
    step = _send(script, "17644")               # -> from station
    step = _send(script, "MAS")                 # -> to station
    step = _send(script, "CGL")                 # -> journey date
    step = _send(script, "27-05-2099")          # -> quota
    step = _send(script, "TATKAL")              # (auto-skips quota-info) -> class priority
    assert step.kind == "multi_choice"
    step = _send(script, ["SL"])                # -> num passengers
    assert step.kind == "number"
    step = _send(script, "1")                   # (auto-skips "Passenger 1 of 1") -> name
    assert step.kind == "text"
    step = _send(script, "Bharani M")            # -> age
    assert step.kind == "number"

    # Feed an out-of-range age (string, as the real Entry widget would send)
    # — must re-prompt with the SAME kind, not crash.
    step = script.send("999")
    assert step.kind == "number"
    assert "between" in step.message.lower()

    # Now a valid age proceeds to the next question (gender).
    step = script.send("35")
    assert step.kind == "choice"


def test_invalid_date_reprompts():
    script = conversation_script()
    step = script.send(None)   # welcome (info)
    step = _send(script, None)          # -> username
    step = _send(script, "lavanya59")   # -> train number
    step = _send(script, "17644")       # -> from station
    step = _send(script, "MAS")         # -> to station
    step = _send(script, "CGL")         # -> journey date
    assert step.kind == "date"

    # Bad date format — genuinely unparseable, must re-prompt without crashing
    step = script.send("not-a-date")
    assert step.kind == "date"
    assert "didn't catch that" in step.message.lower()
    # Past date
    step = script.send("01-01-2000")
    assert step.kind == "date"
    assert "past" in step.message.lower()
    # Valid date proceeds to quota
    step = script.send("27-05-2099")
    assert step.kind == "choice"


# ── Payment method branching ─────────────────────────────────────────────────

def test_card_payment_collects_card_fields_not_upi():
    answers = [
        "lavanya59", "17644", "MAS", "CGL", "27-05-2099", "GENERAL",
        ["SL"], "1", "Bharani M", "35", "M", "LB", "AADHAAR CARD", "713341395482",
        "9962820205",
        "CARD", "4111111111111111", "12/28", "123",
        "CONFIRMED_ONLY", True,
    ]
    config, _ = _drive(conversation_script(), answers)
    assert config.payment.method == PaymentMethod.CARD
    assert config.payment.card_number == "4111111111111111"
    assert config.payment.card_cvv == "123"
    assert config.payment.upi_id is None


def test_rac_wl_policy_collects_thresholds():
    answers = [
        "lavanya59", "17644", "MAS", "CGL", "27-05-2099", "GENERAL",
        ["SL"], "1", "Bharani M", "35", "M", "LB", "AADHAAR CARD", "713341395482",
        "9962820205", "UPI", "test@upi",
        "ALLOW_RAC_WL",
        True, "5",          # allow RAC -> max_rac=5
        True, "20", ["GNWL", "RLWL"],   # allow WL -> max_wl=20, types
        True,
    ]
    config, _ = _drive(conversation_script(), answers)
    assert config.thresholds.max_rac == 5
    assert config.thresholds.max_wl == 20
    assert config.thresholds.allowed_wl_types == ["GNWL", "RLWL"]
