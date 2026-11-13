"""Behavioral acceptance tests for common configuration and FEAT-571 scope handoff."""

from datetime import UTC, datetime

import pytest

from parrot.memory.agent_memory import (
    AgentMemoryConfig,
    ChatStorageEvidenceRef,
    MemoryEvent,
    MemoryRequestScope,
    MemoryWriteReceipt,
)


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


def _scope(**overrides: str | None) -> MemoryRequestScope:
    values = {
        "tenant_id": "tenant-1",
        "agent_id": "agent-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "identity_provenance": "server_resolved",
    }
    values.update(overrides)
    return MemoryRequestScope(**values)


def test_response_event_id_is_deterministic_function_of_turn_identity() -> None:
    """Verify a retried turn yields the same event ID and any identity change yields another (spec F3)."""
    base = _scope().response_event_id()

    assert base == _scope(tenant_id="tenant-2", room_id="room-1").response_event_id()
    for field, other in (
        ("agent_id", "agent-2"),
        ("user_id", "user-2"),
        ("session_id", "session-2"),
        ("turn_id", "turn-2"),
    ):
        assert _scope(**{field: other}).response_event_id() != base
    assert _scope(user_id=None).response_event_id() != base
    assert _scope(user_id=None).response_event_id() != _scope(session_id=None).response_event_id()
    # Field boundaries cannot be shifted to forge a collision.
    assert (
        _scope(agent_id="a", user_id="bc").response_event_id() != _scope(agent_id="ab", user_id="c").response_event_id()
    )


def test_chat_storage_evidence_ref_carries_tenant() -> None:
    """Verify ChatStorage evidence refs round-trip with tenant and reject tenant-less refs (spec F7)."""
    ref = ChatStorageEvidenceRef(
        tenant_id="tenant-1", agent_name="agent/1", user_id="user-1", session_id="session-1", turn_id="turn-1"
    )
    rendered = ref.to_reference()

    assert ChatStorageEvidenceRef.parse(rendered) == ref
    with pytest.raises(ValueError, match="tenant, agent, user, session and turn"):
        ChatStorageEvidenceRef.parse("chatstorage/v1/agent-1/user-1/session-1/turn-1")
    with pytest.raises(ValueError, match="non-blank"):
        ChatStorageEvidenceRef(tenant_id=" ", agent_name="a", user_id="u", session_id="s", turn_id="t")

    scope = _scope()
    event = MemoryEvent(
        event_id=scope.response_event_id(),
        kind="response",
        scope=scope,
        observed_at=datetime(2026, 11, 13, tzinfo=UTC),
        evidence_refs=(rendered,),
    )
    assert event.evidence_refs == (rendered,)
    with pytest.raises(ValueError, match="tenant, agent, user, session and turn"):
        MemoryEvent(
            event_id="event-4",
            kind="response",
            scope=scope,
            observed_at=datetime(2026, 11, 13, tzinfo=UTC),
            evidence_refs=("chatstorage/v1/agent-1/user-1/session-1/turn-1",),
        )
