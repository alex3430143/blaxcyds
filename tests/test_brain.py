from blaxcy.brain.registry import (
    PLANNING,
    REASONING,
    VISION,
    DeterministicProvider,
    ModelSpec,
    Registry,
    UnavailableProvider,
)
from blaxcy.brain.router import FailureKind, Need, Router, classify_error


class FailingProvider:
    def __init__(self, name, exc):
        self.name = name
        self.exc = exc

    def is_available(self):
        return True

    def complete(self, prompt, **kwargs):
        raise self.exc


def test_unavailable_provider_is_excluded_from_available():
    reg = Registry()
    reg.register(ModelSpec(name="ghost", provider="ghost"), UnavailableProvider("ghost"))
    assert reg.available() == []
    assert reg.status()[0]["available"] is False


def test_router_selects_deterministic_for_reasoning():
    reg = Registry()
    reg.register(ModelSpec(name="det", provider="det", capabilities=[REASONING, PLANNING]),
                 DeterministicProvider())
    completion = Router(reg).complete("hi", Need(capability=REASONING))
    assert completion.ok and completion.model == "det"


def test_router_falls_back_when_first_provider_fails():
    reg = Registry()
    reg.register(ModelSpec(name="flaky", provider="flaky", capabilities=[REASONING], priority=1),
                 FailingProvider("flaky", TimeoutError("timed out")))
    reg.register(ModelSpec(name="det", provider="det", capabilities=[REASONING], priority=99),
                 DeterministicProvider())
    completion = Router(reg).complete("plan this", Need(capability=REASONING))
    assert completion.ok and completion.model == "det"
    assert completion.attempts[0]["ok"] is False
    assert completion.attempts[0]["kind"] == FailureKind.TIMEOUT.value


def test_router_reports_failure_when_all_fail():
    reg = Registry()
    reg.register(ModelSpec(name="a", provider="a", capabilities=[REASONING], priority=1),
                 FailingProvider("a", RuntimeError("rate limit exceeded 429")))
    completion = Router(reg).complete("x", Need(capability=REASONING))
    assert not completion.ok
    assert completion.error_kind is FailureKind.RATE_LIMIT
    assert completion.model == ""


def test_capability_mismatch_is_explicit():
    reg = Registry()
    reg.register(ModelSpec(name="text-only", provider="t", capabilities=[REASONING]),
                 DeterministicProvider())
    completion = Router(reg).complete("describe", Need(capability=VISION))
    assert not completion.ok
    assert completion.error_kind is FailureKind.CAPABILITY_MISMATCH


def test_classify_error_variants():
    assert classify_error(TimeoutError()) is FailureKind.TIMEOUT
    assert classify_error(RuntimeError("quota exceeded")) is FailureKind.QUOTA
    assert classify_error(RuntimeError("429 rate limit")) is FailureKind.RATE_LIMIT
    assert classify_error(RuntimeError("provider unavailable")) is FailureKind.UNAVAILABLE
