"""Request timing, from core/request-policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rest_mapper.policy import (
    Budget,
    BudgetPeriod,
    PolicyConfig,
    PolicyState,
    Refusal,
    RequestPolicy,
    Status,
    UpdateMode,
    parse_retry_after,
)

START = datetime(2026, 11, 1, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def policy(
    config: PolicyConfig | None = None, state: PolicyState | None = None
) -> tuple[RequestPolicy, Clock]:
    clock = Clock()
    return RequestPolicy(config or PolicyConfig(), clock, lambda: 0.5, state), clock


def test_default_spacing() -> None:
    subject, clock = policy()
    subject.record_sent()
    assert subject.next_request_at() == clock.now + timedelta(minutes=15)


def test_pacing_to_a_monthly_limit() -> None:
    budget = Budget(2500, BudgetPeriod.MONTH)
    subject, _ = policy(PolicyConfig(budget=budget))
    assert round(subject.spacing().total_seconds() / 60) == 19


def test_interval_slower_than_the_budget() -> None:
    budget = Budget(100000, BudgetPeriod.DAY)
    subject, _ = policy(PolicyConfig(budget=budget))
    assert subject.spacing() == timedelta(minutes=15)


def test_new_period() -> None:
    budget = Budget(10, BudgetPeriod.DAY)
    subject, clock = policy(PolicyConfig(budget=budget))
    subject.record_sent()
    clock.advance(days=1)
    assert subject.used == 0


def test_reserve_reached() -> None:
    budget = Budget(10, BudgetPeriod.DAY)
    subject, clock = policy(PolicyConfig(budget=budget))
    for _ in range(9):
        subject.record_sent()
    assert subject.next_request_at() == clock.now + timedelta(days=1)
    assert subject.status() is Status.BUDGET_EXHAUSTED


def test_manual_with_reserve_left() -> None:
    budget = Budget(10, BudgetPeriod.DAY)
    subject, _ = policy(PolicyConfig(budget=budget))
    for _ in range(9):
        subject.record_sent()
    assert subject.check_manual().allowed


def test_nothing_left() -> None:
    budget = Budget(10, BudgetPeriod.DAY)
    subject, clock = policy(PolicyConfig(budget=budget))
    for _ in range(10):
        subject.record_sent()
    decision = subject.check_manual()
    assert decision.refusal is Refusal.BUDGET_EXHAUSTED
    assert decision.possible_at == clock.now + timedelta(days=1)


def test_month_end_rolls_over_a_year() -> None:
    state = PolicyState()
    clock = Clock()
    clock.now = datetime(2026, 12, 15, tzinfo=UTC)
    budget = Budget(10, BudgetPeriod.MONTH, 0)
    subject = RequestPolicy(PolicyConfig(budget=budget), clock, lambda: 0.5, state)
    for _ in range(10):
        subject.record_sent()
    assert subject.check_manual().possible_at == datetime(2027, 1, 1, tzinfo=UTC)


def test_on_demand_schedules_nothing() -> None:
    subject, clock = policy(PolicyConfig(mode=UpdateMode.ON_DEMAND))
    clock.advance(days=30)
    assert subject.next_request_at() is None
    assert not subject.is_due()
    assert subject.status() is Status.ON_DEMAND


def test_both_validators() -> None:
    subject, _ = policy()
    subject.record_fetched('W/"a"', "yesterday")
    validators = subject.validators()
    assert validators is not None
    assert (validators.etag, validators.last_modified) == ('W/"a"', "yesterday")


def test_no_validators() -> None:
    subject, _ = policy()
    subject.record_fetched(None, None)
    assert subject.validators() is None


def test_not_modified_ends_backoff() -> None:
    subject, _ = policy()
    subject.record_failure()
    subject.record_not_modified()
    assert subject.state.failures == 0


def test_validators_discarded_on_credentials_change() -> None:
    subject, _ = policy()
    subject.record_fetched("a", None)
    subject.credentials_changed()
    assert subject.validators() is None


def test_retry_after_seconds() -> None:
    subject, clock = policy()
    subject.record_sent()
    subject.record_rate_limited("3600")
    assert subject.next_request_at() == clock.now + timedelta(seconds=3600)


def test_retry_after_date() -> None:
    subject, clock = policy()
    subject.record_failure("Sun, 01 Nov 2026 06:00:00 GMT")
    assert subject.state.rate_limited_until == clock.now + timedelta(hours=6)


def test_excessive_retry_after() -> None:
    assert parse_retry_after("604800", START) == timedelta(hours=24)


def test_unreadable_or_past_retry_after() -> None:
    assert parse_retry_after("soon", START) is None
    assert parse_retry_after("Sat, 01 Nov 2025 06:00:00 GMT", START) is None
    assert parse_retry_after(None, START) is None


def test_manual_during_the_wait() -> None:
    subject, clock = policy()
    subject.record_rate_limited("86400")
    decision = subject.check_manual()
    assert decision.refusal is Refusal.RATE_LIMITED
    assert decision.possible_at == clock.now + timedelta(days=1)
    assert subject.status() is Status.RATE_LIMITED


def test_repeated_failures() -> None:
    subject, clock = policy()
    for minutes in (30, 60, 120):
        subject.record_failure()
        assert subject.state.backoff_until == clock.now + timedelta(minutes=minutes)
    assert subject.status() is Status.RETRYING


def test_backoff_ceiling() -> None:
    subject, clock = policy()
    for _ in range(40):
        subject.record_failure()
    assert subject.state.backoff_until == clock.now + timedelta(hours=6)


def test_backoff_variation() -> None:
    clock = Clock()
    subject = RequestPolicy(PolicyConfig(), clock, lambda: 1.0)
    subject.record_failure()
    assert subject.state.backoff_until == clock.now + timedelta(minutes=33)


def test_recovery() -> None:
    subject, clock = policy()
    subject.record_failure()
    subject.record_sent()
    subject.record_fetched(None, None)
    assert subject.next_request_at() == clock.now + timedelta(minutes=15)


def test_manual_allowed_after_connection_failure() -> None:
    subject, _ = policy()
    subject.record_failure()
    assert subject.check_manual().allowed


def test_authentication_stop() -> None:
    subject, _ = policy()
    subject.record_auth_failed()
    assert subject.next_request_at() is None
    assert subject.status() is Status.AUTH_FAILED
    subject.credentials_changed()
    assert subject.next_request_at() is not None


def test_restored_within_the_wait() -> None:
    subject, clock = policy()
    subject.record_rate_limited("600")
    restored = RequestPolicy(
        PolicyConfig(), clock, lambda: 0.5, PolicyState.from_data(subject.state.to_data())
    )
    assert restored.next_request_at() == clock.now + timedelta(seconds=1800)


def test_restored_in_a_later_period() -> None:
    budget = Budget(10, BudgetPeriod.MONTH)
    subject, clock = policy(PolicyConfig(budget=budget))
    subject.record_sent()
    clock.advance(days=31)
    restored = RequestPolicy(
        PolicyConfig(budget=budget),
        clock,
        lambda: 0.5,
        PolicyState.from_data(subject.state.to_data()),
    )
    assert restored.used == 0


def test_restored_before_the_next_request_is_due() -> None:
    subject, clock = policy()
    subject.record_sent()
    clock.advance(minutes=5)
    restored = RequestPolicy(
        PolicyConfig(), clock, lambda: 0.5, PolicyState.from_data(subject.state.to_data())
    )
    assert restored.next_request_at() == clock.now + timedelta(minutes=10)


def test_malformed_state_falls_back() -> None:
    state = PolicyState.from_data({"used": "x", "last_request": "nope", "auth_stopped": 1})
    assert state == PolicyState()


def test_secrets_stay_out_of_repr() -> None:
    assert "secret" not in repr(PolicyState(etag="secret"))


def test_other_failure_ends_a_rate_limit_streak() -> None:
    subject, _ = policy()
    subject.record_rate_limited(None)
    subject.record_failure()
    subject.record_rate_limited(None)
    assert subject.state.rate_limit_streak == 1
