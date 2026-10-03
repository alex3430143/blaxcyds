import pytest

from blaxcy.brain import registry as _reg  # noqa: F401  (ensure package import path)
from blaxcy.models import Action, ActionKind, RiskClass, TrustLevel
from blaxcy.policy import Policy, classify


def test_default_classification_by_kind():
    assert classify(Action(kind=ActionKind.MOUSE_MOVE)) is RiskClass.LOW
    assert classify(Action(kind=ActionKind.CLICK)) is RiskClass.MEDIUM
    assert classify(Action(kind=ActionKind.APP_LAUNCH)) is RiskClass.HIGH


def test_destructive_and_auth_markers_escalate():
    assert classify(Action(kind=ActionKind.TERMINAL_RUN,
                           params={"command": "rm -rf /"})) is RiskClass.DESTRUCTIVE
    assert classify(Action(kind=ActionKind.TERMINAL_RUN,
                           params={"command": "sudo apt install x"})) is RiskClass.AUTH_BOUNDARY


def test_emergency_stop_pause_takeover_block(policy: Policy):
    action = Action(kind=ActionKind.CLICK)
    policy.emergency_stop()
    assert not policy.check(action).allowed
    policy.clear_emergency_stop()
    policy.pause()
    assert not policy.check(action).allowed
    policy.resume()
    policy.request_takeover()
    assert not policy.check(action).allowed
    policy.clear_takeover()
    assert policy.check(action).allowed


def test_high_risk_requires_confirmation_until_approved(policy: Policy):
    action = Action(kind=ActionKind.APP_LAUNCH, params={"command": "gedit"})
    decision = policy.check(action)
    assert not decision.allowed and decision.requires_confirmation
    policy.approve(action.action_id)
    assert policy.check(action).allowed


def test_auth_boundary_escalates_to_user(policy: Policy):
    action = Action(kind=ActionKind.TERMINAL_RUN, params={"command": "sudo reboot"})
    decision = policy.check(action)
    assert not decision.allowed
    assert decision.escalate_to_user
    assert decision.risk is RiskClass.AUTH_BOUNDARY


def test_max_risk_gate(policy: Policy):
    policy.max_risk = RiskClass.SAFE
    assert not policy.check(Action(kind=ActionKind.CLICK)).allowed


def test_input_is_simulated_when_real_input_disabled(policy: Policy):
    decision = policy.check(Action(kind=ActionKind.TYPE_TEXT, params={"text": "hi"}))
    assert decision.allowed and decision.simulated

    policy.real_input_enabled = True
    assert not policy.check(Action(kind=ActionKind.TYPE_TEXT, params={"text": "hi"})).simulated


def test_untrusted_instructions_are_not_followed(policy: Policy):
    assert policy.may_follow_instructions(TrustLevel.TRUSTED)
    assert policy.may_follow_instructions(TrustLevel.DERIVED)
    assert not policy.may_follow_instructions(TrustLevel.UNTRUSTED)
