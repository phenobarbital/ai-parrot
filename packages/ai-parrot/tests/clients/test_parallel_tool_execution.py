"""Tests for parallel tool execution gated by `parallel_tool_execution`
(FEAT-416, TASK-2148 — spec §3 Module 4).

Exercised via ``NovaAudio.stream_voice()`` (mock harness established by
``test_nova_tool_result.py``): two ``toolUse``/``contentEnd(TOOL)`` pairs
arrive back-to-back before the turn's ``completionEnd``, each backed by a
mocked ``_execute_tool`` that sleeps ~100ms, to measure real wall-clock
concurrency rather than asserting on mocked call counts alone.
"""
import asyncio
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.nova import NovaClient

TOOL_A_USE = {"toolUse": {"toolName": "tool_a", "toolUseId": "tu_a",
                          "content": '{"which": "a"}'}}
TOOL_B_USE = {"toolUse": {"toolName": "tool_b", "toolUseId": "tu_b",
                          "content": '{"which": "b"}'}}
TOOL_END = {"contentEnd": {"type": "TOOL"}}
END = {"completionEnd": {}}

TWO_TOOLS_FRAMES = [TOOL_A_USE, TOOL_END, TOOL_B_USE, TOOL_END, END]


def _client():
    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
        return NovaClient(model="nova-2-sonic", region="us-east-1")


async def _run(frames, execute, **stream_voice_kwargs):
    """Feed already-unwrapped frames through stream_voice() (mirrors
    ``test_nova_tool_result.py``'s ``_run`` helper)."""
    client = _client()
    sent = []

    async def capture(_stream, event):
        sent.append(event)

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
         patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=capture), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=AsyncMock()), \
         patch.object(client, "_execute_tool", new=execute):
        out = [r async for r in client.stream_voice(audio(), **stream_voice_kwargs)]
    return out, sent


async def _sleep_100ms(_name, args):
    await asyncio.sleep(0.1)
    return f"result-for-{args.get('which')}"


class TestParallelToolExecution:
    @pytest.mark.asyncio
    async def test_parallel_faster_than_sequential(self):
        """Two 100ms tools execute in < 150ms with parallel=True."""
        execute = AsyncMock(side_effect=_sleep_100ms)
        start = time.monotonic()
        out, sent = await _run(
            TWO_TOOLS_FRAMES, execute, parallel_tool_execution=True,
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 150, f"expected < 150ms, took {elapsed_ms:.1f}ms"
        assert execute.await_count == 2
        results = [tc.result for r in out for tc in r.tool_calls]
        assert "result-for-a" in results
        assert "result-for-b" in results

    @pytest.mark.asyncio
    async def test_sequential_default(self):
        """Two 100ms tools take ~200ms with parallel=False (default)."""
        execute = AsyncMock(side_effect=_sleep_100ms)
        start = time.monotonic()
        out, sent = await _run(TWO_TOOLS_FRAMES, execute)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms >= 180, f"expected >= 180ms (sequential), took {elapsed_ms:.1f}ms"
        assert execute.await_count == 2
        results = [tc.result for r in out for tc in r.tool_calls]
        assert "result-for-a" in results
        assert "result-for-b" in results

    @pytest.mark.asyncio
    async def test_parallel_error_isolation(self):
        """One failing tool doesn't prevent the other from completing."""
        async def _one_fails(name, args):
            if args.get("which") == "a":
                raise RuntimeError("tool_a blew up")
            await asyncio.sleep(0.05)
            return "result-for-b"

        execute = AsyncMock(side_effect=_one_fails)
        out, sent = await _run(
            TWO_TOOLS_FRAMES, execute, parallel_tool_execution=True,
        )

        tool_calls = [tc for r in out for tc in r.tool_calls]
        errored = [tc for tc in tool_calls if tc.error]
        succeeded = [tc for tc in tool_calls if not tc.error]
        assert len(errored) == 1
        assert "tool_a blew up" in errored[0].error
        assert len(succeeded) == 1
        assert succeeded[0].result == "result-for-b"
        # Both results must still be sent back to the model.
        tool_results = [e["event"]["toolResult"] for e in sent if "toolResult" in e.get("event", {})]
        assert len(tool_results) == 2

    @pytest.mark.asyncio
    async def test_all_tool_results_sent_before_completion(self):
        """Both toolResult frames are sent before the final completionEnd
        response is yielded — the Nova Sonic protocol requirement that all
        results reach the model before it resumes."""
        execute = AsyncMock(side_effect=_sleep_100ms)
        out, sent = await _run(
            TWO_TOOLS_FRAMES, execute, parallel_tool_execution=True,
        )
        assert out[-1].is_complete is True
        assert len(out[-1].tool_calls) == 2
        tool_results = [e["event"]["toolResult"] for e in sent if "toolResult" in e.get("event", {})]
        assert len(tool_results) == 2
