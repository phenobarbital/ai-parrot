"""Unit tests for CrewRegistry."""
import asyncio

import pytest
from datetime import datetime, timezone

from parrot.integrations.telegram.crew.registry import CrewRegistry
from parrot.integrations.telegram.crew.agent_card import AgentCard


@pytest.fixture
def registry():
    return CrewRegistry()


@pytest.fixture
def sample_card():
    return AgentCard(
        agent_id="agent1",
        agent_name="DataAgent",
        telegram_username="data_bot",
        telegram_user_id=111,
        model="gpt-4",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


def _make_card(i: int) -> AgentCard:
    return AgentCard(
        agent_id=f"agent_{i}",
        agent_name=f"Agent{i}",
        telegram_username=f"bot_{i}",
        telegram_user_id=i,
        model="test",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestCrewRegistry:
    @pytest.mark.asyncio
    async def test_register_unregister(self, registry, sample_card):
        await registry.register(sample_card)
        assert registry.get("data_bot") is not None
        removed = await registry.unregister("data_bot")
        assert removed.agent_id == "agent1"
        assert registry.get("data_bot") is None

    @pytest.mark.asyncio
    async def test_unregister_unknown(self, registry):
        removed = await registry.unregister("nonexistent")
        assert removed is None

    @pytest.mark.asyncio
    async def test_update_status(self, registry, sample_card):
        await registry.register(sample_card)
        await registry.update_status("data_bot", "busy", "processing Q2")
        card = registry.get("data_bot")
        assert card.status == "busy"
        assert card.current_task == "processing Q2"

    @pytest.mark.asyncio
    async def test_update_status_updates_last_seen(self, registry, sample_card):
        await registry.register(sample_card)
        old_last_seen = sample_card.last_seen
        await registry.update_status("data_bot", "busy")
        card = registry.get("data_bot")
        assert card.last_seen >= old_last_seen

    @pytest.mark.asyncio
    async def test_update_status_unknown_agent(self, registry):
        # Should not raise, just log warning
        await registry.update_status("nonexistent", "busy")

    def test_get_with_at_prefix(self, registry, sample_card):
        registry._agents["data_bot"] = sample_card
        assert registry.get("@data_bot") is not None
        assert registry.get("@data_bot").agent_id == "agent1"

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None

    def test_resolve_by_username(self, registry, sample_card):
        registry._agents["data_bot"] = sample_card
        assert registry.resolve("data_bot") is not None
        assert registry.resolve("@data_bot") is not None

    def test_resolve_by_name(self, registry, sample_card):
        registry._agents["data_bot"] = sample_card
        assert registry.resolve("DataAgent") is not None
        assert registry.resolve("dataagent") is not None
        assert registry.resolve("DATAAGENT") is not None

    def test_resolve_not_found(self, registry):
        assert registry.resolve("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_active(self, registry, sample_card):
        await registry.register(sample_card)
        active = registry.list_active()
        assert len(active) == 1
        assert active[0].agent_id == "agent1"

    @pytest.mark.asyncio
    async def test_list_active_excludes_offline(self, registry, sample_card):
        await registry.register(sample_card)
        await registry.update_status("data_bot", "offline")
        active = registry.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_list_active_includes_busy(self, registry, sample_card):
        await registry.register(sample_card)
        await registry.update_status("data_bot", "busy", "working")
        active = registry.list_active()
        assert len(active) == 1

    @pytest.mark.asyncio
    async def test_thread_safety(self, registry):
        cards = [_make_card(i) for i in range(10)]
        await asyncio.gather(*[registry.register(c) for c in cards])
        assert len(registry.list_active()) == 10

    @pytest.mark.asyncio
    async def test_concurrent_register_unregister(self, registry):
        cards = [_make_card(i) for i in range(5)]
        # Register all
        await asyncio.gather(*[registry.register(c) for c in cards])
        assert len(registry.list_active()) == 5
        # Unregister all concurrently
        await asyncio.gather(*[registry.unregister(f"bot_{i}") for i in range(5)])
        assert len(registry.list_active()) == 0

    @pytest.mark.asyncio
    async def test_unregister_with_at_prefix(self, registry, sample_card):
        await registry.register(sample_card)
        removed = await registry.unregister("@data_bot")
        assert removed is not None
        assert removed.agent_id == "agent1"
