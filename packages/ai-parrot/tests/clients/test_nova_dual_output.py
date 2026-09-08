"""Unit tests for FEAT-536 TASK-2939 — Nova voice tool adapter.

Maps complete ``ToolResult`` envelopes (via
``ToolManager.execute_tool(..., return_tool_result=True)``, TASK-2937/2938)
onto Nova's spoken/visual dual-output contract (spec §2 "Nova
tool-to-voice mapping"). Uses a real ``ToolManager`` + real
``AbstractTool``/``ToolDefinition`` tools for every test that exercises
tool execution — only the Bedrock SDK/transport is stubbed (same
``sys.modules`` trick ``test_nova_tool_result.py`` uses); tool execution
itself, the manager, and ``ToolManager.execute_tool`` are never mocked.

Test names below are the task's required target tests (§ Test
Specification, TASK-2939); each is implemented as a class grouping the
scenarios that make up that behavioral guarantee.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from parrot.clients.amazon.nova import NovaClient
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.tools.decorators import tool
from parrot.tools.manager import ToolManager


class _WeatherArgs(AbstractToolArgsSchema):
    """Declares the accepted kwargs — AbstractTool.execute() drops any
    kwarg not declared on args_schema (validate_args()/_shallow_dump()),
    so a bare AbstractTool subclass with no custom schema would silently
    lose both the model-supplied `location` and the injected trusted
    context fields."""

    location: str = ""


class _EchoContextArgs(AbstractToolArgsSchema):
    session_id: str | None = None
    user_id: str | None = None
    turn_id: str | None = None


def _make_client() -> NovaClient:
    """Construct a NovaClient with the Pre-Alpha voice SDK stubbed out.

    Mirrors ``test_nova_tool_result.py``'s ``_run()`` helper — only the
    ``aws_sdk_bedrock_runtime`` import guard is patched; nothing about tool
    execution is mocked here.
    """
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        return NovaClient(model="nova-2-sonic", region="us-east-1")


class _VoiceAwareTool(AbstractTool):
    """Real AbstractTool returning a full dual-output envelope."""

    name = "get_weather"
    description = "Return the weather for a location, with a chart."
    args_schema = _WeatherArgs

    async def _execute(self, location: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            status="success",
            result={"temp_f": 78, "location": location},
            voice_text=f"It's sunny in {location}.",
            display_data={"chart": "weather", "location": location},
        )


class _EchoContextTool(AbstractTool):
    """Echoes back whatever session_id/user_id/turn_id it actually
    received — used to prove trusted context wins over model-supplied
    values with the same key names."""

    name = "echo_context"
    description = "Echoes back the session_id/user_id/turn_id it received."
    args_schema = _EchoContextArgs

    async def _execute(self, session_id=None, user_id=None, turn_id=None, **kwargs) -> ToolResult:
        return ToolResult(
            status="success",
            result={"session_id": session_id, "user_id": user_id, "turn_id": turn_id},
        )


class _ErrorTool(AbstractTool):
    name = "error_tool"
    description = "Always fails."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=False, status="error", result=None, error="boom")


# ── test_nova_dual_output_from_real_tool ──────────────────────────────────


class TestNovaDualOutputFromRealTool:
    """A real tool and the real manager (via ``_execute_tool_full``) yield
    the intended Nova spoken payload and exact visual object — no mock of
    their execution."""

    @pytest.mark.asyncio
    async def test_nova_dual_output_from_real_tool(self):
        client = _make_client()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_VoiceAwareTool())
        client.tool_manager = tm

        result = await client._execute_tool_full(
            "get_weather",
            {"location": "Miami"},
            session_id="sess-1",
            user_id="user-1",
            turn_id="turn-1",
            permission_context=None,
        )
        assert isinstance(result, ToolResult)

        provider_result, display_data, tool_status = client._map_tool_result_to_nova(result)

        assert provider_result == {"output": "It's sunny in Miami."}
        assert display_data == {"chart": "weather", "location": "Miami"}
        assert tool_status == "success"
        # The visual object is exact — not a stringified/re-encoded copy.
        assert display_data is result.display_data

    @pytest.mark.asyncio
    async def test_flush_pending_tools_delivers_dual_output_via_real_tool(self):
        """End-to-end through _flush_pending_tools(): one streamed tool
        delta carries the mapped spoken payload plus metadata["tool_status"]
        and metadata["display_data"] — via LiveToolCall/LiveVoiceResponse."""
        from parrot.models.voice import LiveCompletionUsage, LiveToolCall

        client = _make_client()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_VoiceAwareTool())
        client.tool_manager = tm

        sent = []

        async def capture(_stream, event):
            sent.append(event)

        pending = LiveToolCall(id="tu_1", name="get_weather", arguments={})
        usage = LiveCompletionUsage()
        tool_calls_list = []

        with patch.object(client, "_send_event", new=capture):
            responses = await client._flush_pending_tools(
                stream=object(),
                prompt_name="p1",
                pending_tools=[(pending, '{"location": "Miami"}')],
                tool_calls_list=tool_calls_list,
                usage=usage,
                session_id="sess-1",
                turn_id="turn-1",
                user_id="user-1",
                parallel_tool_execution=False,
                permission_context=None,
            )

        assert len(responses) == 1
        resp = responses[0]
        assert resp.metadata["tool_status"] == "success"
        assert resp.metadata["display_data"] == {"chart": "weather", "location": "Miami"}
        assert pending.result == {"output": "It's sunny in Miami."}
        assert pending.error is None
        assert usage.tool_calls_executed == 1
        assert tool_calls_list == [pending]

        tool_result_frames = [e["event"]["toolResult"] for e in sent if "toolResult" in e.get("event", {})]
        assert len(tool_result_frames) == 1
        assert tool_result_frames[0]["content"] == '{"output": "It\'s sunny in Miami."}'


# ── test_nova_context_overrides_model_identity ────────────────────────────


class TestNovaContextOverridesModelIdentity:
    """Trusted IDs win; tools without context parameters still work;
    reserved kwargs cannot be injected from provider arguments."""

    @pytest.mark.asyncio
    async def test_trusted_ids_win_over_model_supplied_values(self):
        client = _make_client()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_EchoContextTool())
        client.tool_manager = tm

        # The model hallucinated its own identity values as tool "arguments".
        model_args = {"session_id": "fake-sess", "user_id": "fake-user", "turn_id": "fake-turn"}

        result = await client._execute_tool_full(
            "echo_context",
            model_args,
            session_id="real-sess",
            user_id="real-user",
            turn_id="real-turn",
            permission_context=None,
        )

        assert result.result == {
            "session_id": "real-sess",
            "user_id": "real-user",
            "turn_id": "real-turn",
        }

    @pytest.mark.asyncio
    async def test_tools_without_context_params_still_work(self):
        client = _make_client()
        tm = ToolManager(include_search_tool=False)

        @tool
        def add(x: int, y: int) -> int:
            """Add two numbers."""
            return x + y

        tm.register_tool(add)
        client.tool_manager = tm

        result = await client._execute_tool_full(
            "add",
            {"x": 2, "y": 3},
            session_id="s",
            user_id="u",
            turn_id="t",
            permission_context=None,
        )
        # session_id/user_id/turn_id are NOT accepted by add()'s signature
        # (a ToolDefinition — real signature-based filtering applies) and
        # are therefore never injected; the tool still executes correctly.
        assert result.result == 5

    def test_reserved_kwargs_stripped_before_merge(self):
        client = _make_client()
        tm = ToolManager(include_search_tool=False)
        client.tool_manager = tm

        merged = client._build_trusted_tool_arguments(
            "irrelevant",
            {
                "_permission_context": "attacker-supplied",
                "_resolver": "attacker-supplied",
                "_broker": "attacker-supplied",
                "_cred_channel": "attacker-supplied",
                "_cred_user_id": "attacker-supplied",
                "real_arg": 1,
            },
            session_id="s",
            user_id=None,
            turn_id=None,
        )

        assert "_permission_context" not in merged
        assert "_resolver" not in merged
        assert "_broker" not in merged
        assert "_cred_channel" not in merged
        assert "_cred_user_id" not in merged
        assert merged["real_arg"] == 1
        assert merged["session_id"] == "s"

    @pytest.mark.asyncio
    async def test_two_concurrent_streams_do_not_exchange_identity(self):
        """Two concurrent full-mode executions on the SAME tool instance,
        with different trusted contexts, never see each other's IDs —
        each call is request-local (own merged-args dict; the manager's
        per-instance lock, TASK-2938, serializes AbstractTool dispatch)."""
        client = _make_client()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_EchoContextTool())
        client.tool_manager = tm

        import asyncio

        results = await asyncio.gather(
            client._execute_tool_full(
                "echo_context", {}, session_id="s-A", user_id="u-A", turn_id="t-A", permission_context=None
            ),
            client._execute_tool_full(
                "echo_context", {}, session_id="s-B", user_id="u-B", turn_id="t-B", permission_context=None
            ),
        )

        observed = {r.result["session_id"] for r in results}
        assert observed == {"s-A", "s-B"}
        for r in results:
            if r.result["session_id"] == "s-A":
                assert r.result == {"session_id": "s-A", "user_id": "u-A", "turn_id": "t-A"}
            else:
                assert r.result == {"session_id": "s-B", "user_id": "u-B", "turn_id": "t-B"}


# ── test_nova_mapping_plain_error_and_empty_values ────────────────────────


class TestNovaMappingPlainErrorAndEmptyValues:
    """Plain returns, zero, empty visual dict, non-serializable visual
    payload and non-success envelopes follow spec §2's mapping table."""

    def test_nonempty_voice_text_wins(self):
        client = _make_client()
        result = ToolResult(status="success", result={"raw": "data"}, voice_text="spoken answer")
        provider_result, display_data, status = client._map_tool_result_to_nova(result)
        assert provider_result == {"output": "spoken answer"}
        assert status == "success"

    def test_dict_result_without_voice_override_stays_dict(self):
        client = _make_client()
        result = ToolResult(status="success", result={"a": 1, "b": 2})
        provider_result, _, _ = client._map_tool_result_to_nova(result)
        assert provider_result == {"a": 1, "b": 2}

    def test_string_result_becomes_output(self):
        client = _make_client()
        result = ToolResult(status="success", result="plain string")
        provider_result, _, _ = client._map_tool_result_to_nova(result)
        assert provider_result == {"output": "plain string"}

    def test_none_result_maps_to_success(self):
        client = _make_client()
        result = ToolResult(status="success", result=None)
        provider_result, _, _ = client._map_tool_result_to_nova(result)
        assert provider_result == {"output": "Success"}

    def test_falsy_scalars_survive_are_not_confused_with_missing(self):
        client = _make_client()
        for value in (False, 0, 0.0):
            result = ToolResult(status="success", result=value)
            provider_result, _, _ = client._map_tool_result_to_nova(result)
            assert provider_result == {"output": str(value)}
            assert provider_result != {"output": "Success"}

    def test_error_status_no_success_visual(self):
        client = _make_client()
        result = ToolResult(success=False, status="error", result="ignored", error="boom", display_data={"x": 1})
        provider_result, display_data, status = client._map_tool_result_to_nova(result)
        assert provider_result == {"error": "boom", "status": "error"}
        assert display_data is None  # non-success -> never a visual event
        assert status == "error"

    def test_pending_status_is_non_success_no_visual(self):
        client = _make_client()
        result = ToolResult(success=False, status="pending", result=None, display_data={"x": 1})
        provider_result, display_data, status = client._map_tool_result_to_nova(result)
        assert display_data is None
        assert status == "pending"
        assert "error" in provider_result

    def test_empty_display_data_dict_stays_suppressed(self):
        client = _make_client()
        result = ToolResult(status="success", result="ok", display_data={})
        _, display_data, _ = client._map_tool_result_to_nova(result)
        assert display_data is None

    def test_non_serializable_display_data_omits_visual_keeps_speech(self):
        client = _make_client()
        result = ToolResult(status="success", result="ok", voice_text="the answer", display_data={"bad": object()})
        provider_result, display_data, status = client._map_tool_result_to_nova(result)
        assert display_data is None  # omitted, not raised/forwarded raw
        assert provider_result == {"output": "the answer"}  # spoken result still reaches Nova
        assert status == "success"

    @pytest.mark.asyncio
    async def test_real_tool_error_status_produces_no_success_hooks_or_visual(self):
        client = _make_client()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_ErrorTool())
        client.tool_manager = tm

        result = await client._execute_tool_full(
            "error_tool", {}, session_id="s", user_id="u", turn_id="t", permission_context=None
        )
        provider_result, display_data, status = client._map_tool_result_to_nova(result)

        assert status == "error"
        assert display_data is None
        assert provider_result == {"error": "boom", "status": "error"}
