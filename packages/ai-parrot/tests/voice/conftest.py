"""Shared provider test doubles for the voice conformance kit (FEAT-418,
TASK-2176 — spec §3 Module 9).

Mocks at the provider-SDK boundary (google-genai's Live WebSocket session
for Gemini; the thin ``_open_stream``/``_send_event``/``_iter_events``
wrappers for Nova) rather than ``stream_voice()`` itself, so each client's
own translation logic (role normalization, voice validation, reconnect
signal mapping, etc.) is actually exercised — mocking ``stream_voice()``
would test nothing about drop-in parity.

Adding a third provider costs exactly one entry in ``PROVIDER_BUILDERS``
plus a scenario-event builder pair, mirroring this module's shape.
"""

import asyncio
import sys
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.clients.google.live import GeminiLiveClient
from parrot.clients.amazon.nova import NovaClient
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.tools.manager import ToolManager


async def empty_audio_iterator() -> AsyncIterator[bytes]:
    """An audio iterator that ends immediately — every scenario here drives
    the response side only; the (already-tested elsewhere) sender task
    just needs to not hang."""
    return
    yield  # pragma: no cover — makes this an async generator


# ---------------------------------------------------------------------
# Dual-output conformance (FEAT-536 TASK-2946) — the SAME deterministic
# real voice-aware AbstractTool registered on both providers, so
# test_provider_dual_output_conformance can compare semantic spoken and
# visual output without mocking stream_voice, _execute_tool, or
# ToolManager.execute_tool.
# ---------------------------------------------------------------------


class _DualOutputArgs(AbstractToolArgsSchema):
    topic: str = ""


class VoiceAwareEchoTool(AbstractTool):
    """Deterministic real tool returning both spoken and visual output —
    shared by the Gemini and Nova tool-call scenarios below so a
    dual-output conformance assertion compares the SAME tool definition/
    behavior (spec §3 Module 6: "Instantiate tools per bot factory; share
    their definition/behavior rather than mutable invocation state")."""

    name = "voice_echo"
    description = "Echo a topic back with spoken text and a visual chart."
    args_schema = _DualOutputArgs

    async def _execute(self, topic: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            status="success",
            result={"topic": topic},
            voice_text=f"Echo: {topic}",
            display_data={"topic": topic, "kind": "echo"},
        )


def make_tool_manager(tool: Optional[AbstractTool] = None) -> ToolManager:
    """A real ToolManager with one real tool registered — never mocked."""
    tm = ToolManager(include_search_tool=False)
    tm.register_tool(tool or VoiceAwareEchoTool())
    return tm


def gated_nova_iter_events(pre_gate_events: list, gate: "asyncio.Event", post_gate_events: list):
    """A CAUSALLY-GATED Nova ``_iter_events`` replacement — not a single
    preloaded array. Yields *pre_gate_events*, then suspends on *gate*
    before yielding *post_gate_events*, so a test can deterministically
    control whether a provider event (e.g. ``completionEnd``) arrives
    before or after some other real, independently-timed event (e.g. a
    slow tool execution) — the same causal-gate pattern
    ``test_nova_tool_progress.py`` uses in place of timing-sensitive
    sleeps.
    """

    async def _iter_events(_stream):
        for event in pre_gate_events:
            yield event
        await gate.wait()
        for event in post_gate_events:
            yield event

    return _iter_events


# ---------------------------------------------------------------------
# Gemini — mock at the google-genai Live WebSocket session boundary
# ---------------------------------------------------------------------


class _FakeGeminiSession:
    """Minimal stand-in for the google-genai Live WebSocket session."""

    def __init__(self, responses):
        self._responses = responses
        self.send_realtime_input = AsyncMock()
        self.send_tool_response = AsyncMock()
        self.send = AsyncMock()

    async def receive(self):
        for response in self._responses:
            yield response


class _FakeConnectCM:
    """Async context manager returned by ``client.aio.live.connect()``."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class _FakeGeminiLiveNamespace:
    def __init__(self, session, captured_configs):
        self._session = session
        self._captured_configs = captured_configs

    def connect(self, model=None, config=None):
        # Record the per-call LiveConnectConfig so tests can assert
        # temperature/max_output_tokens/top_p were honored (spec §3
        # Module 9: "options honored" is a conformance requirement).
        self._captured_configs.append(config)
        return _FakeConnectCM(self._session)


class _FakeGeminiAio:
    def __init__(self, session, captured_configs):
        self.live = _FakeGeminiLiveNamespace(session, captured_configs)


class _FakeGeminiSdkClient:
    def __init__(self, session, captured_configs):
        self.aio = _FakeGeminiAio(session, captured_configs)


def _gemini_event(**overrides) -> SimpleNamespace:
    """A LiveServerMessage-shaped event with every top-level field
    defaulted to falsy/None, overridden per scenario."""
    defaults: dict = {
        "server_content": None,
        "tool_call": None,
        "usage_metadata": None,
        "go_away": None,
        "session_resumption_update": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def gemini_basic_turn_events() -> list:
    """One user transcription frame, then one assistant text chunk."""
    return [
        _gemini_event(
            server_content=SimpleNamespace(
                input_transcription=SimpleNamespace(text="what's the weather"),
            ),
        ),
        _gemini_event(
            server_content=SimpleNamespace(
                model_turn=SimpleNamespace(parts=[SimpleNamespace(text="It's sunny.", inline_data=None)]),
            ),
        ),
        _gemini_event(
            server_content=SimpleNamespace(turn_complete=True),
        ),
    ]


def gemini_reconnect_events() -> list:
    """A GoAway event — Gemini's session-limit signal."""
    return [
        _gemini_event(go_away=SimpleNamespace(time_left="5s")),
    ]


def gemini_tool_call_events(tool_name: str = "voice_echo", tool_id: str = "fc_1", args: Optional[dict] = None) -> list:
    """A single ``tool_call`` event (one function call), then turn_complete
    — the google-genai ``LiveServerMessage`` shape ``GeminiLiveClient.
    stream_voice()`` reads at ``response.tool_call.function_calls``."""
    return [
        _gemini_event(
            tool_call=SimpleNamespace(
                function_calls=[SimpleNamespace(name=tool_name, id=tool_id, args=args or {"topic": "weather"})]
            ),
        ),
        _gemini_event(server_content=SimpleNamespace(turn_complete=True)),
    ]


def build_gemini_client(monkeypatch, scenario: str, *, tool_manager: Optional[ToolManager] = None) -> GeminiLiveClient:
    kwargs: dict = {"voice_name": "Puck"}
    if tool_manager is not None:
        kwargs.update(tool_manager=tool_manager, use_tools=True)
    client = GeminiLiveClient(**kwargs)
    if scenario == "basic_turn":
        events = gemini_basic_turn_events()
    elif scenario == "tool_call":
        events = gemini_tool_call_events()
    else:
        events = gemini_reconnect_events()
    session = _FakeGeminiSession(events)
    captured_configs: list = []
    fake_sdk_client = _FakeGeminiSdkClient(session, captured_configs)
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=fake_sdk_client))
    # Exposed for TestOptionsHonored — the per-call LiveConnectConfig(s)
    # this client actually sent to the (fake) Live WebSocket connection.
    client.captured_configs = captured_configs
    return client


# ---------------------------------------------------------------------
# Nova — mock at the thin SDK-wrapper boundary
# ---------------------------------------------------------------------


def nova_basic_turn_events() -> list:
    """One user transcription frame, then one assistant text chunk."""
    return [
        {"contentStart": {"role": "USER"}},
        {"textOutput": {"content": "what's the weather"}},
        {"contentStart": {"role": "ASSISTANT"}},
        {"textOutput": {"content": "It's sunny."}},
        {"completionEnd": {}},
    ]


def nova_reconnect_events() -> list:
    """Nova signals its session limit via elapsed wall-clock time inside
    stream_voice() (``_CONNECTION_LIMIT_SECONDS``), not a discrete event —
    the reconnect fixture patches that constant to 0 instead (see
    ``build_nova_client``)."""
    return [
        {"contentStart": {"role": "ASSISTANT"}},
        {"textOutput": {"content": "..."}},
    ]


def nova_tool_call_events(
    tool_use_id: str = "tu_1", tool_name: str = "voice_echo", args_json: str = '{"topic": "weather"}'
) -> list:
    """One ``toolUse``/``contentEnd(TOOL)`` pair (admitted-and-executed
    immediately, TASK-2940/2941), then ``completionEnd``."""
    return [
        {"contentStart": {"role": "ASSISTANT"}},
        {"toolUse": {"toolUseId": tool_use_id, "toolName": tool_name, "content": args_json}},
        {"contentEnd": {"type": "TOOL"}},
        {"completionEnd": {}},
    ]


def _fake_nova_events(events):
    async def _iter_events(_stream):
        for event in events:
            yield event

    return _iter_events


def build_nova_client(monkeypatch, scenario: str, *, tool_manager: Optional[ToolManager] = None) -> NovaClient:
    monkeypatch.setitem(sys.modules, "aws_sdk_bedrock_runtime", MagicMock())
    kwargs: dict = {"model": "nova-2-sonic", "voice_id": "matthew"}
    if tool_manager is not None:
        kwargs.update(tool_manager=tool_manager, use_tools=True)
    client = NovaClient(**kwargs)
    if scenario == "basic_turn":
        events = nova_basic_turn_events()
    elif scenario == "tool_call":
        events = nova_tool_call_events()
    else:
        events = nova_reconnect_events()
    monkeypatch.setattr(client, "_open_stream", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(client, "_send_event", AsyncMock())
    monkeypatch.setattr(client, "_iter_events", _fake_nova_events(events))
    if scenario == "reconnect":
        # Force the 8-minute connection-limit check to trip on the very
        # first event, mirroring Nova's real (time-based) reconnect signal
        # without waiting 465 real seconds.
        monkeypatch.setattr(type(client), "_CONNECTION_LIMIT_SECONDS", -1.0)
    return client


def nova_session_start_config(client) -> dict:
    """Extract the ``sessionStart`` event's ``inferenceConfiguration``
    from a Nova client's mocked ``_send_event`` calls (the Nova-side
    equivalent of Gemini's ``client.captured_configs``)."""
    for call in client._send_event.call_args_list:
        event = call.args[1] if len(call.args) > 1 else call.kwargs.get("event")
        if event and "sessionStart" in event.get("event", {}):
            return event["event"]["sessionStart"]["inferenceConfiguration"]
    raise AssertionError("No sessionStart event was sent")


def nova_prompt_start_voice_id(client) -> str:
    """Extract the ``promptStart`` event's ``voiceId`` from a Nova
    client's mocked ``_send_event`` calls."""
    for call in client._send_event.call_args_list:
        event = call.args[1] if len(call.args) > 1 else call.kwargs.get("event")
        if event and "promptStart" in event.get("event", {}):
            return event["event"]["promptStart"]["audioOutputConfiguration"]["voiceId"]
    raise AssertionError("No promptStart event was sent")


# ---------------------------------------------------------------------
# Provider registry — the single extension point (spec §3 Module 9)
# ---------------------------------------------------------------------

PROVIDER_BUILDERS = {
    "gemini": build_gemini_client,
    "nova": build_nova_client,
}

PROVIDERS = [
    pytest.param("gemini", id="gemini"),
    pytest.param("nova", id="nova"),
]


@pytest.fixture(params=PROVIDERS)
def provider(request) -> str:
    """The provider id under test — the parametrization is the contract:
    adding a provider costs one entry in PROVIDERS + PROVIDER_BUILDERS."""
    return request.param


def build_client(
    monkeypatch, provider_name: str, scenario: str = "basic_turn", *, tool_manager: Optional[ToolManager] = None
) -> Any:
    """Construct *provider_name*'s real client, mocked at its own
    provider-SDK boundary for *scenario* ("basic_turn", "reconnect" or
    "tool_call" — the latter requires *tool_manager*, TASK-2946)."""
    return PROVIDER_BUILDERS[provider_name](monkeypatch, scenario, tool_manager=tool_manager)


async def collect_responses(client, **kwargs) -> list:
    """Drain client.stream_voice() with an empty audio iterator."""
    return [r async for r in client.stream_voice(empty_audio_iterator(), **kwargs)]
