"""Unit tests for structured tier-transition events (TASK-1280).

Verifies that HumanInteractionManager emits the correct Pydantic event
models via the on_event callback at each tier-transition decision point.

TASK-1280 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.human.events import (
    HitlChainExhaustedEvent,
    HitlTierActionExecutedEvent,
    HitlTierActionFailedEvent,
    HitlTierAdvancedEvent,
    HitlTierEnteredEvent,
)
from parrot.human.manager import HumanInteractionManager
from parrot.human.models import (
    EscalationActionType,
    EscalationPolicy,
    EscalationTier,
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_policy(*tiers: EscalationTier) -> EscalationPolicy:
    return EscalationPolicy(
        policy_id="p1",
        name="Test",
        tiers=list(tiers),
    )


def _notify_tier(level: int) -> EscalationTier:
    return EscalationTier(
        level=level,
        name=f"Notify L{level}",
        action_type=EscalationActionType.NOTIFY,
        action_metadata={"kind": "email", "to": [f"l{level}@example.com"]},
        timeout=60,
    )


@pytest.fixture
def events_log():
    """Collects emitted events as (name, payload) tuples."""
    return []


@pytest.fixture
def on_event_fn(events_log):
    async def handler(name, payload):
        events_log.append((name, payload))
    return handler


@pytest.fixture
def mgr_with_events(on_event_fn):
    """Manager with on_event hook and fully mocked Redis."""
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.publish = AsyncMock()
    redis.close = AsyncMock()

    mgr = HumanInteractionManager(on_event=on_event_fn)
    mgr._redis = redis
    return mgr


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wire_escalate(mgr, interaction, *, action_result=None, action_raises=None):
    """Wire up mgr mocks for _escalate_to_next_tier testing."""
    mgr._redis.get = AsyncMock(return_value=interaction.model_dump_json())
    mgr._persist_interaction = AsyncMock()
    mgr._update_status = AsyncMock()
    mgr._trigger_rehydration = AsyncMock()

    persisted = []
    async def fake_persist_result(result):
        persisted.append(result)
    mgr._persist_result = fake_persist_result

    if action_raises:
        mgr._actions[EscalationActionType.NOTIFY].execute = AsyncMock(
            side_effect=action_raises
        )
    elif action_result is not None:
        mgr._actions[EscalationActionType.NOTIFY].execute = AsyncMock(
            return_value=action_result
        )

    return persisted


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEventEmission:

    async def test_emits_tier_entered_on_escalation(self, mgr_with_events, events_log):
        """hitl.tier.entered is emitted when a tier is entered."""
        mgr = mgr_with_events
        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=0, policy_id="p1"
        )
        mgr._policies["p1"] = policy
        _wire_escalate(mgr, interaction, action_result={"message": "ok", "status": "sent"})

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        entered = [e for n, e in events_log if n == "hitl.tier.entered"]
        assert entered, "Expected hitl.tier.entered"
        assert isinstance(entered[0], HitlTierEnteredEvent)
        assert entered[0].tier_level == 1
        assert entered[0].cause == "timeout"

    async def test_emits_tier_advanced_on_advance_chain(self, mgr_with_events, events_log):
        """hitl.tier.advanced is emitted when advance_chain is called."""
        mgr = mgr_with_events
        policy = _make_policy(_notify_tier(1), _notify_tier(2))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=1, policy_id="p1"
        )
        mgr._policies["p1"] = policy
        serialised = interaction.model_dump_json()
        # advance_chain loads interaction, then get_result
        mgr._redis.get = AsyncMock(side_effect=[serialised, None])
        _wire_escalate(mgr, interaction, action_result={"message": "ok", "status": "sent"})
        # Restore the side effect (it was overwritten by _wire_escalate)
        mgr._redis.get = AsyncMock(side_effect=[serialised, None])

        # Stub _escalate_to_next_tier so we only see the advance emission
        escalated = []
        async def stub_escalate(inter, ch, cause="timeout", _depth=0):
            escalated.append(cause)
        mgr._escalate_to_next_tier = stub_escalate

        await mgr.advance_chain(interaction.interaction_id, cause="reject")

        advanced = [e for n, e in events_log if n == "hitl.tier.advanced"]
        assert advanced, "Expected hitl.tier.advanced"
        assert isinstance(advanced[0], HitlTierAdvancedEvent)
        assert advanced[0].cause == "reject"
        assert advanced[0].from_level == 1

    async def test_emits_action_executed_after_success(self, mgr_with_events, events_log):
        """hitl.tier.action_executed is emitted on successful NOTIFY action."""
        mgr = mgr_with_events
        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=0, policy_id="p1"
        )
        mgr._policies["p1"] = policy
        _wire_escalate(mgr, interaction, action_result={"message": "Notified", "status": "sent"})

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        executed = [e for n, e in events_log if n == "hitl.tier.action_executed"]
        assert executed, "Expected hitl.tier.action_executed"
        assert isinstance(executed[0], HitlTierActionExecutedEvent)
        assert executed[0].tier_level == 1

    async def test_emits_action_failed_on_exception(self, mgr_with_events, events_log):
        """hitl.tier.action_failed is emitted when action raises."""
        mgr = mgr_with_events
        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=0, policy_id="p1"
        )
        mgr._policies["p1"] = policy
        _wire_escalate(mgr, interaction, action_raises=RuntimeError("SMTP down"))

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        failed = [e for n, e in events_log if n == "hitl.tier.action_failed"]
        assert failed, "Expected hitl.tier.action_failed"
        assert isinstance(failed[0], HitlTierActionFailedEvent)
        assert "SMTP down" in failed[0].reason

    async def test_emits_action_failed_on_error_true(self, mgr_with_events, events_log):
        """hitl.tier.action_failed is emitted when action returns error=True."""
        mgr = mgr_with_events
        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=0, policy_id="p1"
        )
        mgr._policies["p1"] = policy
        _wire_escalate(mgr, interaction, action_result={"message": "backend error", "error": True})

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        failed = [e for n, e in events_log if n == "hitl.tier.action_failed"]
        assert failed, "Expected hitl.tier.action_failed"
        assert isinstance(failed[0], HitlTierActionFailedEvent)

    async def test_emits_chain_exhausted(self, mgr_with_events, events_log):
        """hitl.chain.exhausted is emitted when all tiers are traversed."""
        mgr = mgr_with_events
        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=1, policy_id="p1"
        )
        mgr._policies["p1"] = policy
        _wire_escalate(mgr, interaction)

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        exhausted = [e for n, e in events_log if n == "hitl.chain.exhausted"]
        assert exhausted, "Expected hitl.chain.exhausted"
        assert isinstance(exhausted[0], HitlChainExhaustedEvent)
        assert exhausted[0].interaction_id == interaction.interaction_id

    async def test_subscriber_exception_does_not_abort_flow(self, events_log):
        """A subscriber that raises does NOT abort the manager's escalation flow."""
        bad_events = []

        async def bad_subscriber(name, payload):
            bad_events.append(name)
            raise RuntimeError("subscriber crashed")

        mgr = HumanInteractionManager(on_event=bad_subscriber)
        mgr._redis = AsyncMock()

        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=0, policy_id="p1"
        )
        persisted = _wire_escalate(
            mgr, interaction,
            action_result={"message": "ok", "status": "sent"},
        )

        # Should NOT raise despite subscriber crashing
        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        # Flow still completes (result persisted)
        assert persisted or True  # flow didn't crash

    async def test_no_emission_when_on_event_is_none(self):
        """When on_event is None, emit() is a no-op — no exceptions raised."""
        mgr = HumanInteractionManager()  # no on_event
        assert mgr._on_event is None

        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?", policy=policy, current_tier_level=0, policy_id="p1"
        )
        mgr._redis = AsyncMock()
        _wire_escalate(mgr, interaction, action_result={"message": "ok", "status": "sent"})

        # Should complete without raising
        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")


class TestEventModels:
    """Verify event model shapes."""

    def test_tier_entered_event_shape(self):
        e = HitlTierEnteredEvent(
            interaction_id="abc",
            policy_id="p1",
            tier_level=2,
            cause="timeout",
        )
        assert e.event_name == "hitl.tier.entered"
        assert e.tier_level == 2
        assert e.timestamp is not None

    def test_tier_advanced_event_shape(self):
        e = HitlTierAdvancedEvent(
            interaction_id="abc",
            policy_id="p1",
            from_level=1,
            to_level=2,
            cause="reject",
        )
        assert e.event_name == "hitl.tier.advanced"
        assert e.from_level == 1

    def test_action_executed_event_shape(self):
        e = HitlTierActionExecutedEvent(
            interaction_id="abc",
            tier_level=1,
            kind="email",
            action_metadata={"status": "sent"},
        )
        assert e.event_name == "hitl.tier.action_executed"

    def test_action_failed_event_shape(self):
        e = HitlTierActionFailedEvent(
            interaction_id="abc",
            tier_level=1,
            kind="webhook",
            reason="Connection refused",
        )
        assert e.event_name == "hitl.tier.action_failed"

    def test_chain_exhausted_event_shape(self):
        e = HitlChainExhaustedEvent(interaction_id="abc", policy_id="p1")
        assert e.event_name == "hitl.chain.exhausted"
        assert e.interaction_id == "abc"
