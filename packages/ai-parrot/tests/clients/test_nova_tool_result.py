import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient
from parrot.tools.abstract import ToolResult

TOOL_USE = {"toolUse": {"toolName": "get_weather", "toolUseId": "tu_1", "content": '{"location": "Miami"}'}}
TOOL_END = {"contentEnd": {"type": "TOOL"}}
TEXT_END = {"contentEnd": {"type": "TEXT"}}
END = {"completionEnd": {}}


async def _run(frames, execute=None):
    """Feed already-unwrapped frames through stream_voice().

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run, so ``sys.modules['aws_sdk_bedrock_runtime']`` is
    stubbed for the duration (mirrors ``test_nova.py``'s ``nova_client``
    fixture) — this exercises protocol logic only, on both Python 3.11 (SDK
    absent) and 3.13 (SDK present).

    FEAT-536 TASK-2940: Nova tool execution now goes through
    ``_execute_tool_full()`` (TASK-2939 — the manager's opt-in
    complete-result mode via ``ToolManager.execute_tool(...,
    return_tool_result=True)``), NOT the reducing ``_execute_tool()`` this
    helper used to patch — so that is what's mocked here now.
    ``execute`` (when supplied) must be an ``AsyncMock`` returning a
    ``ToolResult`` — the raw-value return shape the old ``_execute_tool``
    mock used no longer applies, since ``_map_tool_result_to_nova()``
    (TASK-2939) reads ``ToolResult`` fields (``status``/``success``/
    ``voice_text``/``result``) directly, before the mapped payload ever
    reaches ``_send_tool_result()``.
    """
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
    sent = []

    async def capture(_stream, event):
        sent.append(event)

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    execute = execute or AsyncMock(return_value=ToolResult(status="success", result="Sunny, 25C"))
    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=capture),
        patch.object(client, "_iter_events", new=iter_events),
        patch.object(client, "_close_stream", new=AsyncMock()),
        patch.object(client, "_execute_tool_full", new=execute),
    ):
        out = [r async for r in client.stream_voice(audio())]
    return out, sent, execute


def _frames(sent, name):
    return [e["event"][name] for e in sent if name in e.get("event", {})]


class TestToolTiming:
    @pytest.mark.asyncio
    async def test_not_executed_on_tool_use_frame(self):
        _, _, execute = await _run([TOOL_USE])
        execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_executed_on_tool_content_end(self):
        _, _, execute = await _run([TOOL_USE, TOOL_END, END])
        execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_text_content_end_does_not_execute(self):
        _, _, execute = await _run([TOOL_USE, TEXT_END])
        execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_content_end_without_pending_tool_is_ignored(self):
        out, _, execute = await _run([TOOL_END, END])
        execute.assert_not_called()
        assert out[-1].is_complete is True


class TestToolArguments:
    @pytest.mark.asyncio
    async def test_json_string_content_parsed_to_kwargs(self):
        _, _, execute = await _run([TOOL_USE, TOOL_END, END])
        name, args = execute.await_args[0]
        assert name == "get_weather"
        assert args == {"location": "Miami"}

    @pytest.mark.asyncio
    async def test_malformed_content_reported_as_tool_error(self):
        bad = {"toolUse": {"toolName": "get_weather", "toolUseId": "tu_1", "content": "not json{"}}
        out, sent, execute = await _run([bad, TOOL_END, END])
        execute.assert_not_called()
        errored = [tc for r in out for tc in r.tool_calls if tc.error]
        assert errored, "expected a LiveToolCall with an error set"
        assert _frames(sent, "toolResult"), "must still send a result envelope"


class TestToolResultEnvelope:
    @pytest.mark.asyncio
    async def test_three_frames_in_order(self):
        _, sent, _ = await _run([TOOL_USE, TOOL_END, END])
        names = [n for e in sent for n in e.get("event", {})]
        i = names.index("toolResult")
        assert names[i - 1] == "contentStart"
        assert names[i + 1] == "contentEnd"

    @pytest.mark.asyncio
    async def test_tool_use_id_on_content_start_not_tool_result(self):
        _, sent, _ = await _run([TOOL_USE, TOOL_END, END])
        result = _frames(sent, "toolResult")[0]
        assert "toolUseId" not in result
        assert "contentName" in result
        tool_starts = [c for c in _frames(sent, "contentStart") if c.get("type") == "TOOL"]
        assert tool_starts[0]["toolResultInputConfiguration"]["toolUseId"] == "tu_1"
        assert tool_starts[0]["role"] == "TOOL"
        assert tool_starts[0]["interactive"] is False

    @pytest.mark.asyncio
    async def test_content_name_matches_across_three_frames(self):
        _, sent, _ = await _run([TOOL_USE, TOOL_END, END])
        tool_start = [c for c in _frames(sent, "contentStart") if c.get("type") == "TOOL"][0]
        result = _frames(sent, "toolResult")[0]
        assert result["contentName"] == tool_start["contentName"]

    @pytest.mark.asyncio
    async def test_non_json_serializable_result_does_not_abort_turn(self):
        """Regression guard (code review): a tool can legitimately return a
        non-JSON-serializable object (e.g. a DataFrame) as ``ToolResult.result``.
        json.dumps() on it must not escape _send_tool_result() and abort the
        whole turn.

        FEAT-536 TASK-2939/2940: ``_map_tool_result_to_nova()`` now maps any
        non-dict/non-str successful ``result`` through ``str()`` into
        ``{"output": <str>}`` BEFORE it ever reaches ``_send_tool_result()``
        — so the wire content is that (always-serializable) wrapper dict's
        JSON encoding, not the bare stringified repr the old reducing route
        produced.
        """

        class NotJsonSerializable:
            def __str__(self):
                return "not-json-serializable-repr"

        execute = AsyncMock(return_value=ToolResult(status="success", result=NotJsonSerializable()))
        out, sent, _ = await _run([TOOL_USE, TOOL_END, END], execute=execute)
        assert out[-1].is_complete is True
        result = _frames(sent, "toolResult")[0]
        assert result["content"] == '{"output": "not-json-serializable-repr"}'

    @pytest.mark.asyncio
    async def test_arguments_recorded_even_when_execution_fails(self):
        """Regression guard (code review): LiveToolCall.arguments must
        reflect what was actually attempted even when execution itself
        raises — not just on the success path."""
        execute = AsyncMock(side_effect=RuntimeError("tool blew up"))
        out, _, _ = await _run([TOOL_USE, TOOL_END, END], execute=execute)
        errored = [tc for r in out for tc in r.tool_calls if tc.error]
        assert errored, "expected a LiveToolCall with an error set"
        assert errored[0].arguments == {"location": "Miami"}
