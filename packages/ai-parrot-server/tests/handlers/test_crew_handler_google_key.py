"""CrewHandler applies CREW_AI_KEY to handler-built crews (FEAT-575, TASK-3456)."""
import pytest

from parrot.handlers.crew.handler import CrewHandler
from parrot.models.crew_definition import AgentDefinition, CrewDefinition


class _StubAgent:
    """Constructed-but-unconfigured agent stub, mirroring AbstractBot's contract."""

    _default_llm = "google"

    def __init__(self, name=None, tools=None, llm=None, llm_kwargs=None, **kwargs):
        self.name = name
        self._llm_raw = llm
        # abstract.py:516 assigns BY REFERENCE — reproduce that exactly.
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.system_prompt = None


class _StubBotManager:
    """Minimal `bot_manager` contract: resolve agent classes, no shared tools."""

    def get_bot_class(self, agent_class):
        return _StubAgent

    def get_tool(self, tool_name):
        return None


class _StubHandler:
    """Drives `CrewHandler._create_crew_from_definition` without aiohttp/navigator."""

    def __init__(self):
        import logging

        self.logger = logging.getLogger("test.CrewHandler")
        self.bot_manager = _StubBotManager()


class _FakeAgentCrew:
    """Records the kwargs `AgentCrew(...)` was constructed with."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)
        self.name = kwargs.get("name")
        self.agents = kwargs.get("agents")


def _crew_def():
    return CrewDefinition(
        name="test-crew",
        agents=[
            AgentDefinition(
                agent_id="google-agent",
                agent_class="StubAgent",
                config={"llm": "google"},
            ),
            AgentDefinition(
                agent_id="openai-agent",
                agent_class="StubAgent",
                config={"llm": "openai"},
            ),
        ],
    )


@pytest.fixture
def crew_key(monkeypatch):
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"


@pytest.mark.asyncio
async def test_handler_create_crew_applies_crew_key(crew_key, monkeypatch):
    """Google agent w/o credential gets CREW_AI_KEY; OpenAI agent untouched; crew gets kwarg."""
    monkeypatch.setattr("parrot.handlers.crew.handler.AgentCrew", _FakeAgentCrew)

    handler = _StubHandler()
    crew_def = _crew_def()

    crew = await CrewHandler._create_crew_from_definition(handler, crew_def)

    google_agent, openai_agent = crew.agents
    assert google_agent._llm_kwargs["api_key"] == crew_key
    assert "api_key" not in openai_agent._llm_kwargs
    assert _FakeAgentCrew.last_kwargs.get("google_api_key") == crew_key


@pytest.mark.asyncio
async def test_handler_does_not_write_key_into_definition(crew_key, monkeypatch):
    """CREW_AI_KEY never leaks into the persisted/returned CrewDefinition."""
    monkeypatch.setattr("parrot.handlers.crew.handler.AgentCrew", _FakeAgentCrew)

    handler = _StubHandler()
    crew_def = _crew_def()

    await CrewHandler._create_crew_from_definition(handler, crew_def)

    assert crew_key not in str(crew_def.model_dump())


@pytest.mark.asyncio
async def test_handler_without_key_is_unchanged(monkeypatch):
    """CREW_AI_KEY unset -> no agent gains an api_key and AgentCrew gets google_api_key=None."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", None, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    monkeypatch.setattr("parrot.handlers.crew.handler.AgentCrew", _FakeAgentCrew)

    handler = _StubHandler()
    crew_def = _crew_def()

    crew = await CrewHandler._create_crew_from_definition(handler, crew_def)

    for agent in crew.agents:
        assert "api_key" not in agent._llm_kwargs
    assert _FakeAgentCrew.last_kwargs.get("google_api_key") is None
