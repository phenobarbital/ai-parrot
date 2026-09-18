"""AgentCrew.from_definition credential injection (FEAT-575, TASK-3454)."""
import pytest

from parrot.bots.flows.crew import AgentCrew
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.models.crew_definition import AgentDefinition, CrewDefinition


class _StubAgent:
    """Constructed-but-unconfigured agent stub, mirroring AbstractBot's contract."""

    _default_llm = "google"

    # abstract.py:228-231 — AgentCrew.add_agent() subscribes to these
    # unconditionally, so the stub must declare them to survive from_definition().
    EVENT_STATUS_CHANGED = "status_changed"
    EVENT_TASK_STARTED = "task_started"
    EVENT_TASK_COMPLETED = "task_completed"
    EVENT_TASK_FAILED = "task_failed"

    def __init__(self, name=None, tools=None, llm=None, llm_kwargs=None, **kwargs):
        self.name = name
        self._llm_raw = llm
        # abstract.py:516 assigns BY REFERENCE — reproduce that exactly.
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.system_prompt = None

    def add_event_listener(self, event_name, callback):
        """No-op — abstract.py:1080's real listener registry is out of scope here."""

    async def invoke(self, prompt, **kwargs):
        """No-op — satisfies the AgentLike runtime_checkable Protocol only."""
        raise NotImplementedError


class _FakeClient:
    """Records the kwargs it was constructed with; avoids a real Google client."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


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


def test_from_definition_injects_google_agents(monkeypatch):
    # A unique, non-substring-colliding secret (plain "k" false-positives on
    # "wiki" fields in the dump — execution_wiki_path/enable_execution_wiki).
    secret = "unique-crew-ai-key-782x"
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    crew_def = _crew_def()
    crew = AgentCrew.from_definition(
        crew_def,
        class_resolver=lambda _: _StubAgent,
        google_api_key=secret,
    )
    google_agent = crew.agents["google-agent"]
    openai_agent = crew.agents["openai-agent"]
    assert google_agent._llm_kwargs["api_key"] == secret
    assert "api_key" not in openai_agent._llm_kwargs
    assert secret not in str(crew_def.model_dump())


def test_from_definition_default_none_unchanged(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    crew_def = _crew_def()
    crew = AgentCrew.from_definition(
        crew_def,
        class_resolver=lambda _: _StubAgent,
    )
    for agent in crew.agents.values():
        assert "api_key" not in agent._llm_kwargs


def test_from_definition_forwards_key_to_crew(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    crew_def = _crew_def()
    crew = AgentCrew.from_definition(
        crew_def,
        class_resolver=lambda _: _StubAgent,
        google_api_key="k",
    )
    assert crew._google_api_key == "k"


def test_from_definition_respects_agent_own_credential(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    crew_def = CrewDefinition(
        name="test-crew",
        agents=[
            AgentDefinition(
                agent_id="google-agent",
                agent_class="StubAgent",
                config={"llm": "google", "llm_kwargs": {"api_key": "own"}},
            ),
        ],
    )
    crew = AgentCrew.from_definition(
        crew_def,
        class_resolver=lambda _: _StubAgent,
        google_api_key="k",
    )
    google_agent = crew.agents["google-agent"]
    assert google_agent._llm_kwargs["api_key"] == "own"
