"""
Widget-level tests for chat_ui.ChatApp — actually instantiate Tk() and drive
real widgets (not just the pure-logic generator, see test_chat_ui_script.py),
to catch runtime widget/layout bugs and verify the Back / Start Over buttons
correctly rebuild state via replay. Requires a real display (skipped
otherwise, e.g. a headless CI box).
"""
import time
import pytest

tk = pytest.importorskip("tkinter")

from chat_ui import ChatApp


def _pump(root, seconds=0.6):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        time.sleep(0.02)


@pytest.fixture(scope="module")
def app():
    """One Tk() root and ONE ChatApp for the whole module, reset (not
    recreated) between tests. Rapid create/destroy of many Tk()/ChatApp
    instances back-to-back in one process is flaky on Windows (transient
    TclErrors, and re-instantiating ChatApp on the same root would stack a
    fresh toolbar/transcript/input_area on top of the previous one instead
    of replacing it)."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tkinter")
    a = ChatApp(root)
    _pump(root)
    yield a
    root.destroy()


@pytest.fixture(autouse=True)
def _reset_between_tests(app):
    """Every test starts from a clean conversation, without tearing down
    and rebuilding any Tk widgets."""
    app._reset()
    _pump(app.root)
    yield


def _submit_text(app, value):
    kids = app.input_area.winfo_children()
    entries = [w for w in kids if isinstance(w, tk.Entry)]
    buttons = [w for w in kids if isinstance(w, tk.Button)]
    assert entries, "expected a text Entry for this step"
    assert buttons, "expected a Send button for this step"
    entries[0].delete(0, "end")
    entries[0].insert(0, value)
    # Click the Send button directly rather than synthesizing a <Return>
    # keypress — event_generate("<Return>") depends on OS-level window
    # focus to reach the binding, which isn't reliable under a test
    # runner; invoke() calls the button's command directly, same as a
    # real click, with no focus dependency.
    buttons[0].invoke()
    _pump(app.root)


def test_back_button_starts_disabled(app):
    assert str(app.back_btn["state"]) == "disabled"


def test_back_button_enables_after_first_answer(app):
    _submit_text(app, "lavanya59")
    assert str(app.back_btn["state"]) == "normal"


def test_back_removes_last_answer_from_transcript_and_history(app):
    _submit_text(app, "lavanya59")
    _submit_text(app, "17644")
    _submit_text(app, "MAS")
    assert "MAS" in app.transcript.get("1.0", "end")
    assert len(app._history) == 3

    app.back_btn.invoke()
    _pump(app.root)

    assert "You: MAS" not in app.transcript.get("1.0", "end")
    assert len(app._history) == 2


def test_re_answering_after_back_uses_the_new_value(app):
    """The scenario that motivated this feature: user made a typo, went
    Back, and re-entered the correct value — the corrected value must be
    what ends up in history, not the original typo."""
    _submit_text(app, "lavanya59")
    _submit_text(app, "17644")
    _submit_text(app, "TYPO-STATION")  # mistake
    app.back_btn.invoke()
    _pump(app.root)
    _submit_text(app, "MAS")  # corrected

    assert app._history[-1] == "MAS"
    assert "TYPO-STATION" not in app.transcript.get("1.0", "end")


def test_repeated_back_returns_to_the_first_question(app):
    _submit_text(app, "lavanya59")
    _submit_text(app, "17644")
    _submit_text(app, "MAS")
    for _ in range(5):
        app.back_btn.invoke()
        _pump(app.root)
    assert app._history == []
    assert str(app.back_btn["state"]) == "disabled"


def test_back_on_first_question_is_a_safe_no_op(app):
    app.back_btn.invoke()
    _pump(app.root)
    assert app._history == []


def _find_start_over_button(app):
    for frame in app.root.winfo_children():
        if isinstance(frame, tk.Frame):
            for w in frame.winfo_children():
                if isinstance(w, tk.Button) and w["text"] == "Start Over":
                    return w
    return None


def test_start_over_clears_everything(app):
    _submit_text(app, "lavanya59")
    _submit_text(app, "17644")

    reset_btn = _find_start_over_button(app)
    assert reset_btn is not None, "Start Over button not found"
    reset_btn.invoke()
    _pump(app.root)

    assert app._history == []
    assert str(app.back_btn["state"]) == "disabled"
    transcript = app.transcript.get("1.0", "end")
    assert "lavanya59" not in transcript
    assert "17644" not in transcript
    assert "Hi! I'm your Tatkal booking agent" in transcript
