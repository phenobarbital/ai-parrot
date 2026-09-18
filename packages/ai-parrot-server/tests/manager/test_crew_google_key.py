"""BotManager passes CREW_AI_KEY to AgentCrew.from_definition (FEAT-575, TASK-3455)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot.manager.manager import BotManager
from parrot.models.crew_definition import CrewDefinition


@pytest.fixture
def crew_key(monkeypatch):
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"


def _stub_manager() -> BotManager:
    """A BotManager stub exposing only what `_create_crew_from_definition` needs."""
    bm = BotManager.__new__(BotManager)
    bm.get_bot_class = MagicMock(name="get_bot_class")
    return bm


@pytest.mark.asyncio
async def test_manager_create_crew_passes_crew_key(crew_key, monkeypatch):
    """CREW_AI_KEY set -> forwarded as `google_api_key` to `from_definition`."""
    recorded = {}

    def _fake_from_definition(crew_def, **kwargs):
        recorded.update(kwargs)
        return MagicMock(name="AgentCrew-instance")

    monkeypatch.setattr(
        "parrot.manager.manager.AgentCrew.from_definition",
        _fake_from_definition,
    )

    manager = _stub_manager()
    crew_def = MagicMock(spec=CrewDefinition)

    result = await manager._create_crew_from_definition(crew_def)

    assert result is not None
    assert recorded.get("class_resolver") is manager.get_bot_class
    assert recorded.get("google_api_key") == crew_key


@pytest.mark.asyncio
async def test_manager_create_crew_without_key_passes_none(monkeypatch):
    """CREW_AI_KEY unset -> forwarded `google_api_key` is None (today's behaviour)."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", None, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)

    recorded = {}

    def _fake_from_definition(crew_def, **kwargs):
        recorded.update(kwargs)
        return MagicMock(name="AgentCrew-instance")

    monkeypatch.setattr(
        "parrot.manager.manager.AgentCrew.from_definition",
        _fake_from_definition,
    )

    manager = _stub_manager()
    crew_def = MagicMock(spec=CrewDefinition)

    await manager._create_crew_from_definition(crew_def)

    assert recorded.get("google_api_key") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
