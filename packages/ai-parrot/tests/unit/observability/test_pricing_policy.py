"""FEAT-783 AC-13 — subscription seat reports $0 + equivalent_usd."""

from __future__ import annotations

import pytest

from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models.claude import ClaudeCodeDispatchProfile
from parrot.observability.cost.policy import PricingPolicy
from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _CapturingRecorder(AbstractLogger):
    """Recorder that retains usage records for assertions."""

    name = "capture"

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        """Retain one usage record.

        Args:
            record: Normalized usage record emitted by the subscriber.
        """
        self.records.append(record)


def test_subscription_zeroes_usd_and_keeps_list_price() -> None:
    """Subscription usage reports no spend and retains its list-price equivalent."""
    assert PricingPolicy(kind="subscription").apply(1.25) == (0.0, 1.25)
    assert PricingPolicy(kind="subscription").apply(None) == (0.0, None)


def test_billed_and_estimate_passthrough() -> None:
    """Billed and estimated costs pass through without an equivalent value."""
    assert PricingPolicy(kind="billed").apply(1.25) == (1.25, None)
    assert PricingPolicy(kind="estimate").apply(1.25) == (1.25, None)


def test_unknown_policy_falls_back_to_billed(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown labels fail safe to billed and emit one diagnostic log."""
    with caplog.at_level("DEBUG", logger="parrot.observability.cost.policy"):
        policy = PricingPolicy.from_label("unexpected")

    assert policy.kind == "billed"
    assert policy.apply(1.25) == (1.25, None)
    assert len(caplog.records) == 1


@pytest.mark.asyncio
async def test_subscriber_cumulative_excludes_subscription_cost() -> None:
    """Subscriber cumulative spend uses the post-policy subscription value."""
    recorder = _CapturingRecorder()
    subscriber = UsageRecordingSubscriber(recorders=[recorder])
    registry = EventRegistry(forward_to_global=False)
    registry.add_provider(subscriber)
    event = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cost_usd=1.25,
        pricing_policy="subscription",
        source_type="dispatcher",
        source_name="claude-code",
    )

    await registry.emit(event)

    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert record.cost_usd == 0.0
    assert record.equivalent_usd == 1.25
    assert record.pricing_policy == "subscription"
    assert record.cumulative_cost_usd == 0.0


@pytest.mark.parametrize(
    ("dispatch_env", "parent_key", "expected"),
    [
        ({"ANTHROPIC_API_KEY": ""}, None, "subscription"),
        ({}, "api-key", "billed"),
        ({}, None, None),
    ],
)
def test_claude_pricing_policy_is_derived_from_effective_auth(
    monkeypatch: pytest.MonkeyPatch,
    dispatch_env: dict[str, str],
    parent_key: str | None,
    expected: str | None,
) -> None:
    """Claude usage policy follows the effective child authentication path."""
    dispatcher = ClaudeCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    monkeypatch.setattr(dispatcher, "_resolve_dispatch_env", lambda: dispatch_env)
    if parent_key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", parent_key)

    assert dispatcher._claude_pricing_policy(ClaudeCodeDispatchProfile()) == expected
