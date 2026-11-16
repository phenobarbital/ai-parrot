"""Integration tests for BasicAgent's built-in persistent-memory facade."""

from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from parrot.bots.agent import BasicAgent
from parrot.clients.base import AbstractClient
from parrot.memory.agent_memory import AgentMemoryMixin
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.models import AIMessage, CompletionUsage


class _Client(AbstractClient):
    """Offline client double used to configure a real BasicAgent."""

    client_type = "agent-memory-migration"
    supported_models = ["stub"]

    def __init__(self) -> None:
        """Initialize the deterministic client."""
        super().__init__(model="stub")

    async def get_client(self) -> "_Client":
        """Return the configured client."""
        return self

    async def _ensure_client(self) -> "_Client":
        """Satisfy the abstract client lifecycle."""
        return self

    async def ask(self, prompt: str, **kwargs: Any) -> AIMessage:
        """Return a deterministic response."""
        return AIMessage(
            input=prompt,
            output="reply",
            response="reply",
            model="stub",
            provider=self.client_type,
            usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def ask_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str | AIMessage]:
        """Yield one deterministic response."""
        yield await self.ask(prompt, **kwargs)

    async def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract client contract."""
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract client contract."""
        raise NotImplementedError


def _scope() -> MemoryRequestScope:
    """Build a deterministic request scope for the unconfigured path."""
    return MemoryRequestScope(
        tenant_id="default",
        agent_id="memory-agent",
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


class TestBotIntegrationHooks:
    """Verify BasicAgent owns exactly one cooperative memory facade."""

    def test_basic_agent_has_single_memory_facade(self) -> None:
        """Include AgentMemoryMixin once without requiring subclasses to repeat it."""
        assert issubclass(BasicAgent, AgentMemoryMixin)
        assert BasicAgent.__mro__.count(AgentMemoryMixin) == 1

        class ConsumerAgent(BasicAgent):
            """Representative live consumer that inherits only BasicAgent."""

        assert ConsumerAgent.__mro__.count(AgentMemoryMixin) == 1

    @pytest.mark.asyncio
    async def test_basic_agent_configures_real_memory_store(self, tmp_path: Path) -> None:
        """Run the cooperative BaseBot/AgentMemoryMixin lifecycle with SQLite persistence."""
        agent = BasicAgent(
            name="memory-agent",
            llm=_Client(),
            memory_type="memory",
            injection_detection=False,
            enable_episodic_memory=True,
            agent_memory_config={"storage_path": str(tmp_path / "agent-memory.sqlite3")},
        )

        try:
            await agent.configure()
            manager = agent._memory_manager

            assert manager is not None
            assert manager.episodic is not None
            assert manager.namespace.agent_id == agent.name
            assert manager.config.enable_episodic is True
        finally:
            await agent.cleanup()

        assert agent._memory_manager is None

    @pytest.mark.asyncio
    async def test_basic_agent_defaults_keep_memory_disabled(self) -> None:
        """Keep the unchanged no-capability path empty until flags are enabled."""
        agent = BasicAgent(name="memory-agent", llm=_Client(), injection_detection=False)

        config = agent._resolve_agent_memory_config()
        context = await agent.prepare_memory("query", scope=_scope())

        assert config.enable_episodic_memory is False
        assert config.enable_user_memory is False
        assert config.enable_brain is False
        assert context.to_prompt_string() == ""
