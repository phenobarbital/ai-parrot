"""AgentCrew default-Google-client credential wiring (FEAT-575, TASK-3453)."""

import pytest

from parrot.bots.flows.crew import AgentCrew
from parrot.clients import AbstractClient
from parrot.clients.factory import SUPPORTED_CLIENTS


class _FakeClient:
    """Records the kwargs it was constructed with."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


def test_crew_default_llm_gets_key(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    AgentCrew(google_api_key="k")
    assert _FakeClient.last_kwargs["api_key"] == "k"


def test_crew_default_llm_without_key_unchanged(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    _FakeClient.last_kwargs = {}
    AgentCrew()
    assert "api_key" not in _FakeClient.last_kwargs


def test_crew_explicit_api_key_kwarg_wins(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    AgentCrew(google_api_key="k", api_key="explicit")
    assert _FakeClient.last_kwargs["api_key"] == "explicit"


def test_crew_llm_instance_untouched():
    class _FakeClientInstance(AbstractClient):
        """Minimal concrete AbstractClient stand-in for a live instance."""

        def __init__(self):
            # super().__init__() intentionally skipped: this stand-in only
            # needs to satisfy AbstractClient's abstract-method contract.
            pass

        async def get_client(self):
            return self

        async def ask(self, *args, **kwargs):
            raise NotImplementedError

        async def ask_stream(self, *args, **kwargs):
            raise NotImplementedError
            yield  # pragma: no cover - never reached, satisfies async generator shape

        async def resume(self, *args, **kwargs):
            raise NotImplementedError

        async def invoke(self, *args, **kwargs):
            raise NotImplementedError

    instance = _FakeClientInstance()
    crew = AgentCrew(llm=instance, google_api_key="k")
    assert crew._llm is instance


def test_crew_non_google_llm_string_gets_no_key(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, "openai", _FakeClient)
    _FakeClient.last_kwargs = {}
    AgentCrew(llm="openai", google_api_key="k")
    assert "api_key" not in _FakeClient.last_kwargs


@pytest.mark.asyncio
async def test_run_loop_and_summary_fallback_use_key(monkeypatch):
    import parrot.clients.google as google_module

    monkeypatch.setattr(google_module, "GoogleGenAIClient", _FakeClient)
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)

    crew = AgentCrew(google_api_key="k")

    # --- run_loop lazy fallback ---
    crew._llm = None
    crew.agents = {"a": object()}

    async def _raise_ready(agent):
        raise RuntimeError("stop-early-run-loop")

    monkeypatch.setattr(crew, "_ensure_agent_ready", _raise_ready)

    with pytest.raises(RuntimeError, match="stop-early-run-loop"):
        await crew.run_loop(initial_task="t", condition="done", agent_sequence=["a"])

    assert _FakeClient.last_kwargs["api_key"] == "k"

    # --- executive-summary lazy fallback ---
    _FakeClient.last_kwargs = {}
    crew._llm = None
    crew.execution_memory.results = {"dummy": object()}

    async def _raise_summary(*args, **kwargs):
        raise RuntimeError("stop-early-summary")

    monkeypatch.setattr(crew, "_generate_executive_summary", _raise_summary)

    with pytest.raises(RuntimeError, match="stop-early-summary"):
        await crew.summary(mode="executive_summary")

    assert _FakeClient.last_kwargs["api_key"] == "k"
