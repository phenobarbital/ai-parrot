"""Behavioral acceptance tests for common configuration and FEAT-571 scope handoff."""

from datetime import UTC, datetime

import pytest

from parrot.memory.agent_memory import AgentMemoryConfig, MemoryEvent, MemoryRequestScope, MemoryWriteReceipt


def test_capability_matrix_and_brain_implication() -> None:
    """Verify independent capability combinations and brain's episodic implication."""
    matrix = {
        (False, False): False,
        (False, True): True,
        (True, False): False,
        (True, True): True,
    }

    for (enable_user_memory, enable_episodic_memory), expected_episodic in matrix.items():
        config = AgentMemoryConfig(
            enable_user_memory=enable_user_memory,
            enable_episodic_memory=enable_episodic_memory,
        )
        assert config.enable_user_memory is enable_user_memory
        assert config.enable_episodic_memory is enable_episodic_memory
        assert config.effective_episodic_memory is expected_episodic

    brain_config = AgentMemoryConfig(enable_brain=True)
    assert brain_config.effective_episodic_memory is True
    assert brain_config.enable_user_memory is False


def test_constructor_precedence_and_legacy_flag_error() -> None:
    """Verify explicit values override defaults and legacy flags name replacements."""
    config = AgentMemoryConfig(max_context_tokens=512, include_relevant_skills=True)

    assert config.max_context_tokens == 512
    assert config.include_relevant_skills is True
    assert AgentMemoryConfig().max_context_tokens == 2000

    with pytest.raises(ValueError, match="enable_episodic_memory and/or enable_user_memory"):
        AgentMemoryConfig(enable_long_term_memory=True)

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        AgentMemoryConfig(unknown_flag=True)


def test_frozen_scope_and_bounded_event() -> None:
    """Verify immutable trusted scopes and bounded UTC event payloads."""
    scope = MemoryRequestScope(
        tenant_id="tenant-1",
        agent_id="agent-1",
        turn_id="turn-1",
        identity_provenance="server_resolved",
    )

    with pytest.raises(ValueError):
        scope.user_id = "another-user"
    with pytest.raises(ValueError, match="identity_provenance"):
        MemoryRequestScope(
            tenant_id="tenant-1",
            agent_id="agent-1",
            turn_id="turn-1",
            identity_provenance="caller_supplied",
        )

    event = MemoryEvent(
        event_id="event-1",
        kind="response",
        scope=scope,
        observed_at=datetime(2026, 11, 13, tzinfo=UTC),
        payload={"response": "accepted"},
    )
    receipt = MemoryWriteReceipt(event_id=event.event_id, scope=scope, status="applied", failures=("review deferred",))

    assert event.observed_at.utcoffset() is not None
    assert receipt.failures == ("review deferred",)

    with pytest.raises(ValueError, match="aware UTC"):
        MemoryEvent(
            event_id="event-2",
            kind="tool",
            scope=scope,
            observed_at=datetime(2026, 11, 13),
        )
    with pytest.raises(ValueError):
        MemoryEvent(
            event_id="event-3",
            kind="tool",
            scope=scope,
            observed_at=datetime(2026, 11, 13, tzinfo=UTC),
            payload={str(index): index for index in range(33)},
        )
