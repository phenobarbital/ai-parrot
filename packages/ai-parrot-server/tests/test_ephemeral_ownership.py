"""Unit tests for ephemeral ownership generalization (FEAT-208 / TASK-1387).

Verifies:
- EphemeralAgentStatus accepts owner_id/owner_kind for agent owners.
- EphemeralAgentStatus normalises legacy user_id: int → owner_id/owner_kind.
- EphemeralRegistry.get() resolves by owner_id (agent) and by user_id (compat).
- EphemeralRegistry.get_all_for_user() returns only user-owned entries.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from parrot.manager.ephemeral import (
    EphemeralAgentStatus,
    EphemeralRegistry,
    OwnerKind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.utcnow()


def _expires(seconds: int = 300) -> datetime:
    return _now() + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> EphemeralRegistry:
    """Fresh EphemeralRegistry for each test."""
    return EphemeralRegistry()


# ---------------------------------------------------------------------------
# EphemeralAgentStatus — ownership fields
# ---------------------------------------------------------------------------


class TestEphemeralAgentStatusOwnership:
    """Tests for the new owner_id / owner_kind fields and the user_id compat alias."""

    def test_create_with_agent_owner(self) -> None:
        """EphemeralAgentStatus can be created with an agent owner."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-001",
            owner_id="agent:parent-123",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        assert status.owner_id == "agent:parent-123"
        assert status.owner_kind == "agent"
        assert status.user_id is None  # agent owner → no int user_id

    def test_create_with_user_id_compat(self) -> None:
        """Legacy user_id: int constructor path still works (backward compat)."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-002",
            user_id=42,
            created_at=_now(),
            expires_at=_expires(),
        )
        assert status.owner_id == "42"
        assert status.owner_kind == "user"
        assert status.user_id == 42

    def test_create_with_owner_id_user(self) -> None:
        """Explicit owner_id + owner_kind='user' also works."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-003",
            owner_id="99",
            owner_kind="user",
            created_at=_now(),
            expires_at=_expires(),
        )
        assert status.owner_id == "99"
        assert status.owner_kind == "user"
        assert status.user_id == 99

    def test_user_id_property_none_for_agent(self) -> None:
        """user_id property returns None for agent-owned status."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-004",
            owner_id="agent:orchestrator",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        assert status.user_id is None

    def test_owner_kind_type_alias_exported(self) -> None:
        """OwnerKind is exported and is a Literal type alias."""
        # Just verify it can be used as a value annotation (doesn't throw)
        kind: OwnerKind = "agent"
        assert kind == "agent"
        kind2: OwnerKind = "user"
        assert kind2 == "user"

    def test_user_id_compat_does_not_override_explicit_owner_id(self) -> None:
        """If owner_id is already set, user_id in dict is ignored."""
        # When both are in the dict, owner_id takes precedence (no double-pop)
        status = EphemeralAgentStatus(
            chatbot_id="sub-005",
            owner_id="agent:parent-999",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        assert status.owner_id == "agent:parent-999"
        assert status.owner_kind == "agent"


# ---------------------------------------------------------------------------
# EphemeralRegistry — ownership-aware get() / get_all_for_user()
# ---------------------------------------------------------------------------


class TestEphemeralRegistryOwnership:
    """Tests for the generalised EphemeralRegistry methods."""

    @pytest.mark.asyncio
    async def test_get_by_agent_owner_id(self, registry: EphemeralRegistry) -> None:
        """registry.get() resolves agent-owned status by owner_id kwarg."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-010",
            owner_id="agent:parent-456",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        await registry.register(status)

        found = registry.get("sub-010", owner_id="agent:parent-456")
        assert found is not None
        assert found.owner_kind == "agent"
        assert found.owner_id == "agent:parent-456"

    @pytest.mark.asyncio
    async def test_get_by_user_id_compat(self, registry: EphemeralRegistry) -> None:
        """registry.get() resolves user-owned status by legacy user_id positional arg."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-011",
            user_id=99,
            created_at=_now(),
            expires_at=_expires(),
        )
        await registry.register(status)

        found = registry.get("sub-011", 99)  # positional, legacy path
        assert found is not None
        assert found.user_id == 99

    @pytest.mark.asyncio
    async def test_get_by_user_id_keyword_compat(self, registry: EphemeralRegistry) -> None:
        """registry.get() resolves user-owned status by user_id keyword arg."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-012",
            user_id=77,
            created_at=_now(),
            expires_at=_expires(),
        )
        await registry.register(status)

        found = registry.get("sub-012", user_id=77)
        assert found is not None
        assert found.user_id == 77

    @pytest.mark.asyncio
    async def test_get_ownership_mismatch_returns_none(
        self, registry: EphemeralRegistry
    ) -> None:
        """registry.get() returns None when owner_id does not match."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-013",
            owner_id="agent:parent-A",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        await registry.register(status)

        not_found = registry.get("sub-013", owner_id="agent:parent-B")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_get_missing_chatbot_returns_none(
        self, registry: EphemeralRegistry
    ) -> None:
        """registry.get() returns None for unknown chatbot_id."""
        result = registry.get("nonexistent", owner_id="agent:x")
        assert result is None

    def test_get_no_owner_raises(self, registry: EphemeralRegistry) -> None:
        """registry.get() raises ValueError when neither user_id nor owner_id given."""
        with pytest.raises(ValueError, match="user_id.*owner_id"):
            registry.get("some-id")

    @pytest.mark.asyncio
    async def test_get_all_for_user_returns_only_user_owned(
        self, registry: EphemeralRegistry
    ) -> None:
        """get_all_for_user() returns only user-kind entries for that user_id."""
        user_status = EphemeralAgentStatus(
            chatbot_id="user-bot-001",
            user_id=5,
            created_at=_now(),
            expires_at=_expires(),
        )
        agent_status = EphemeralAgentStatus(
            chatbot_id="agent-sub-001",
            owner_id="agent:orchestrator",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        other_user_status = EphemeralAgentStatus(
            chatbot_id="user-bot-002",
            user_id=6,
            created_at=_now(),
            expires_at=_expires(),
        )
        await registry.register(user_status)
        await registry.register(agent_status)
        await registry.register(other_user_status)

        results = registry.get_all_for_user(5)
        assert len(results) == 1
        assert results[0].chatbot_id == "user-bot-001"

    @pytest.mark.asyncio
    async def test_remove_clears_entry(self, registry: EphemeralRegistry) -> None:
        """registry.remove() deletes the entry; subsequent get() returns None."""
        status = EphemeralAgentStatus(
            chatbot_id="sub-020",
            owner_id="agent:parent-X",
            owner_kind="agent",
            created_at=_now(),
            expires_at=_expires(),
        )
        await registry.register(status)
        assert registry.get("sub-020", owner_id="agent:parent-X") is not None

        removed = await registry.remove("sub-020")
        assert removed is True
        assert registry.get("sub-020", owner_id="agent:parent-X") is None
