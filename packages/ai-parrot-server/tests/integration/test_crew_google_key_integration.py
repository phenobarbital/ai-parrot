"""End-to-end: a handler-built Google agent's client uses CREW_AI_KEY (FEAT-575, TASK-3457).

Unit tests stop at ``agent._llm_kwargs["api_key"]``. This module proves the kwarg
survives ``AbstractBot.configure()``'s resolution chain and lands on the constructed
Google client — the three hops FEAT-575 deliberately does not modify:

    ``configure()`` -> ``_resolve_llm_config(**self._llm_kwargs)`` -> ``_apply_llm_params``
    (``config.extra.update(kwargs)``) -> ``_create_llm_client`` (``**config.extra``) ->
    ``GoogleGenAIClient.__init__`` (``kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))``).

Note on the fallback path: ``GoogleGenAIClient.__init__`` (``client.py:189``) reads its
default from the *live* ``navconfig`` ``config`` singleton imported directly into the
client module — it never consults ``parrot.conf.GOOGLE_API_KEY`` (a frozen copy taken
once at ``parrot.conf`` import time). Monkeypatching the frozen copy alone would leave
the real fallback resolving to whatever ``GOOGLE_API_KEY`` happens to be set to in the
environment, which is neither controlled nor separable from ``CREW_AI_KEY`` here. This
module instead patches ``config.get`` on the client module's own ``config`` object,
scoped to the ``GOOGLE_API_KEY`` key, so the fallback sentinel is actually observed by
the line under test.
"""

from __future__ import annotations

import logging

import pytest

from parrot.bots.agent import BasicAgent
from parrot.handlers.crew.handler import CrewHandler
from parrot.models.crew_definition import AgentDefinition, CrewDefinition

CREW_SENTINEL = "crew-key-sentinel"
GLOBAL_SENTINEL = "global-google-key-sentinel"

# AC3: skip the whole module cleanly when the satellite (or its SDK extra) is absent.
google_client_module = pytest.importorskip("parrot.clients.google.client")
if not google_client_module._GOOGLE_SDK_AVAILABLE:
    pytest.skip("google-genai SDK not installed", allow_module_level=True)

from parrot.clients.factory import SUPPORTED_CLIENTS  # noqa: E402 — after importorskip


class _RecordingGoogleClient(google_client_module.GoogleGenAIClient):
    """A real ``GoogleGenAIClient`` subclass that never reaches the network.

    Subclasses (rather than replaces) the real client so the actual
    credential-resolution line (``client.py:189``) runs unmodified — the whole
    point of this test. ``__init__`` never opens a network client on its own
    (no SDK client is built there), so no override is needed for that; the
    ``get_client()`` guard below is defense-in-depth against exercising it by
    accident (e.g. a future ``ask()``/``invoke()`` call added to this test).
    """

    async def get_client(self):  # pragma: no cover - defensive guard
        raise AssertionError("must not open a network client in this test")


class _StubBotManager:
    """Minimal `bot_manager` contract: resolve a real BasicAgent, no shared tools."""

    def get_bot_class(self, agent_class):
        return BasicAgent

    def get_tool(self, tool_name):
        return None


class _StubHandler:
    """Drives `CrewHandler._create_crew_from_definition` without aiohttp/navigator."""

    def __init__(self):
        self.logger = logging.getLogger("test.CrewHandler")
        self.bot_manager = _StubBotManager()


def _crew_def() -> CrewDefinition:
    return CrewDefinition(
        name="test-crew",
        agents=[
            AgentDefinition(
                agent_id="google-agent",
                agent_class="BasicAgent",
                config={"llm": "google:gemini-3.5-flash"},
            ),
        ],
    )


def _patch_google_api_key_fallback(monkeypatch, value):
    """Patch the exact source `GoogleGenAIClient.__init__` reads its fallback from.

    ``config`` here is the shared ``navconfig`` singleton imported directly into
    ``parrot.clients.google.client`` — not ``parrot.conf``. Only the
    ``GOOGLE_API_KEY`` key is overridden; every other key still resolves through
    the real ``get()`` so unrelated config (e.g. ``VERTEX_REGION``) is unaffected.
    """
    real_get = google_client_module.config.get

    def _fake_get(key, *args, **kwargs):
        if key == "GOOGLE_API_KEY":
            return value
        return real_get(key, *args, **kwargs)

    monkeypatch.setattr(google_client_module.config, "get", _fake_get)


@pytest.fixture
def both_keys(monkeypatch):
    """Distinct sentinels for CREW_AI_KEY and GOOGLE_API_KEY, so they are separable."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", CREW_SENTINEL, raising=False)
    monkeypatch.setattr("parrot.conf.GOOGLE_API_KEY", GLOBAL_SENTINEL, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    _patch_google_api_key_fallback(monkeypatch, GLOBAL_SENTINEL)


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "Pre-existing bug (predates FEAT-575, not introduced by TASK-3451..3456): "
        "GoogleGenAIClient.__init__ (client.py:189) does "
        "`self.api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))` BEFORE "
        "`super().__init__(**kwargs)`, and AbstractClient.__init__ (base.py:448) "
        "unconditionally does `self.api_key = kwargs.get('api_key', None)` — since "
        "'api_key' was already popped, this always resets self.api_key to None. "
        "GoogleGenAIClient.api_key is None after construction regardless of any kwarg "
        "or config fallback. Sibling GeminiOpenAICompatClient works around this by "
        "re-setting self.api_key AFTER super().__init__() (openai_compat.py:37); "
        "GoogleGenAIClient never does. See ledger issue for the fix task."
    ),
    strict=True,
)
async def test_handler_built_google_agent_client_uses_crew_key(both_keys, monkeypatch):
    """AC1: a handler-built Google agent's configured client uses CREW_AI_KEY."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _RecordingGoogleClient)

    handler = _StubHandler()
    crew_def = _crew_def()

    crew = await CrewHandler._create_crew_from_definition(handler, crew_def)
    agent = crew.agents["google-agent"]
    assert agent._llm_kwargs["api_key"] == CREW_SENTINEL

    await agent.configure()

    client = agent._llm
    assert isinstance(client, _RecordingGoogleClient)
    assert client.api_key == CREW_SENTINEL
    assert client.api_key != GLOBAL_SENTINEL


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "Same pre-existing GoogleGenAIClient.api_key clobber bug as "
        "test_handler_built_google_agent_client_uses_crew_key above (client.py:189 "
        "pops api_key before super().__init__ resets it to None) — the fallback path "
        "is equally clobbered, not just the CREW_AI_KEY injection path. See ledger "
        "issue for the fix task."
    ),
    strict=True,
)
async def test_handler_built_google_agent_falls_back_when_unset(monkeypatch):
    """AC6: with CREW_AI_KEY unset, the constructed client falls back to GOOGLE_API_KEY."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", None, raising=False)
    monkeypatch.setattr("parrot.conf.GOOGLE_API_KEY", GLOBAL_SENTINEL, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    _patch_google_api_key_fallback(monkeypatch, GLOBAL_SENTINEL)
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _RecordingGoogleClient)

    handler = _StubHandler()
    crew_def = _crew_def()

    crew = await CrewHandler._create_crew_from_definition(handler, crew_def)
    agent = crew.agents["google-agent"]
    assert "api_key" not in agent._llm_kwargs

    await agent.configure()

    client = agent._llm
    assert isinstance(client, _RecordingGoogleClient)
    assert client.api_key == GLOBAL_SENTINEL
