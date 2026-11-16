"""Unit tests for the unified AgentMemoryMixin facade."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from parrot.memory.agent_memory import AgentMemoryMixin
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope
from parrot.memory.unified.models import MemoryContext


class _Host:
    """Minimal cooperative lifecycle host for facade tests."""

    def __init__(self) -> None:
        """Initialize observable lifecycle state."""
        self.configure_skipped = False
        self.host_cleaned = False

    async def configure(self, app: Any = None) -> None:
        """Accept facade configuration without acquiring host resources."""
        self.configure_skipped = False

    async def cleanup(self) -> None:
        """Record cooperative host cleanup."""
        self.host_cleaned = True


class MockAgent(AgentMemoryMixin, _Host):
    """Minimal host using the replacement memory facade."""

    name = "test-agent"
    tenant_id = "test-tenant"
    enable_episodic_memory = True

    def __init__(self, storage_path: Path | None = None) -> None:
        """Initialize the host with an optional persistent store path."""
        super().__init__()
        self.agent_memory_config = {"storage_path": str(storage_path)} if storage_path is not None else None


def _scope() -> MemoryRequestScope:
    """Build one deterministic trusted request scope."""
    return MemoryRequestScope(
        tenant_id="test-tenant",
        agent_id="test-agent",
        user_id="user-1",
        session_id="session-1",
        room_id="room-1",
        turn_id="turn-1",
        identity_provenance="server_resolved",
    )


class TestAgentMemoryMixin:
    """Verify the hard-cut facade contracts formerly covered by the old mixin tests."""

    def test_capabilities_resolve_independently(self) -> None:
        """Resolve the replacement flags without a legacy master switch."""
        agent = MockAgent()
        agent.enable_user_memory = True

        config = agent._resolve_agent_memory_config()

        assert config.enable_episodic_memory is True
        assert config.enable_user_memory is True
        assert config.enable_brain is False

        agent.agent_memory_config = {"enable_long_term_memory": True}
        with pytest.raises(ValueError, match="enable_episodic_memory and/or enable_user_memory"):
            agent._resolve_agent_memory_config()

    @pytest.mark.asyncio
    async def test_configure_creates_real_manager(self, tmp_path: Path) -> None:
        """Configure and close a real task-local SQLite episodic store."""
        agent = MockAgent(tmp_path / "agent-memory.sqlite3")

        await agent.configure()
        manager = agent._memory_manager

        assert manager is not None
        assert manager.episodic is not None
        assert manager.namespace.agent_id == "test-agent"
        assert manager.namespace.tenant_id == "test-tenant"

        await agent.cleanup()
        assert agent._memory_manager is None
        assert agent.host_cleaned is True

    @pytest.mark.asyncio
    async def test_prepare_without_manager_returns_empty_context(self) -> None:
        """Return the configured budget without accessing persistence before setup."""
        agent = MockAgent()
        agent._memory_manager = None

        context = await agent.prepare_memory("query", scope=_scope())

        assert context == MemoryContext(tokens_budget=AgentMemoryConfig().max_context_tokens)

    @pytest.mark.asyncio
    async def test_prepare_and_complete_delegate_to_manager(self) -> None:
        """Delegate scoped reads and completed events to the single manager owner."""
        agent = MockAgent()
        manager = AsyncMock()
        expected = MemoryContext(episodic_warnings="remember this")
        manager.prepare_context.return_value = expected
        agent._memory_manager = manager
        scope = _scope()
        event = MemoryEvent(
            event_id="response-1",
            kind="response",
            scope=scope,
            observed_at=datetime(2026, 11, 16, tzinfo=UTC),
            payload={"query": "query", "response": "answer"},
        )

        context = await agent.prepare_memory("query", scope=scope)
        await agent.complete_memory(event)

        assert context is expected
        manager.prepare_context.assert_awaited_once_with("query", scope=scope)
        manager.record_event.assert_awaited_once_with(event)
