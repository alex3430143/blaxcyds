from conftest import StubEye, make_screen_state

from blaxcy.models import Action, ActionKind
from blaxcy.verifier import Verifier


def _action(**postcondition):
    return Action(kind=ActionKind.CLICK, expected_postcondition=postcondition)


def test_window_exists_and_title():
    eye = StubEye(make_screen_state(title="gedit — notes.txt"))
    v = Verifier(eye)
    assert v.verify_postcondition(_action(window_exists="gedit")).ok
    assert v.verify_postcondition(_action(window_title_contains="notes")).ok
    assert not v.verify_postcondition(_action(window_title_contains="chromium")).ok


def test_screen_changed_signal():
    changed = Verifier(StubEye(make_screen_state(changed=True)))
    unchanged = Verifier(StubEye(make_screen_state(changed=False)))
    assert changed.verify_postcondition(_action(screen_changed=True)).ok
    assert not unchanged.verify_postcondition(_action(screen_changed=True)).ok


def test_frame_hash_changed_requires_before():
    before = make_screen_state(hash_="a")
    after = make_screen_state(hash_="b")
    v = Verifier(StubEye(after))
    assert v.verify_postcondition(_action(frame_hash_changed=True), before=before).ok
    assert not v.verify_postcondition(_action(frame_hash_changed=True), before=after).ok


def test_unknown_postcondition_is_not_a_false_success():
    v = Verifier(StubEye(make_screen_state()))
    assert not v.verify_postcondition(_action(nonsense=True)).ok


def test_text_contains_honestly_unsupported():
    v = Verifier(StubEye(make_screen_state()))
    result = v.verify_postcondition(_action(text_contains="hello"))
    assert not result.ok
    assert "not implemented" in result.detail


def test_no_screen_state_fails_verification():
    v = Verifier(StubEye(None))
    assert not v.verify_postcondition(_action(screen_changed=True)).ok


def test_verify_criterion_parsing():
    v = Verifier(StubEye(make_screen_state(title="gedit")))
    assert v.verify_criterion("window title contains gedit").ok
    assert not v.verify_criterion("window title contains firefox").ok
    assert v.verify_criterion("desktop observed").ok
    assert not v.verify_criterion("make me a sandwich").ok
