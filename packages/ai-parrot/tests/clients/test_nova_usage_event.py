import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient

END = {"completionEnd": {}}


async def _run(frames):
    """Feed already-unwrapped frames through stream_voice().

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run, so ``sys.modules['aws_sdk_bedrock_runtime']`` is
    stubbed for the duration (mirrors ``test_nova.py``'s ``nova_client``
    fixture) — this exercises protocol logic only, on both Python 3.11 (SDK
    absent) and 3.13 (SDK present).
    """
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=AsyncMock()),
        patch.object(client, "_iter_events", new=iter_events),
        patch.object(client, "_close_stream", new=AsyncMock()),
    ):
        return [r async for r in client.stream_voice(audio())]


def _terminal_usage(out):
    return [r for r in out if r.is_complete][-1].usage


class TestUsageEvent:
    @pytest.mark.asyncio
    async def test_populates_token_counts(self):
        out = await _run(
            [
                {"usageEvent": {"inputTokens": 12, "outputTokens": 30, "totalTokens": 42}},
                END,
            ]
        )
        usage = _terminal_usage(out)
        assert usage.prompt_tokens == 12
        assert usage.completion_tokens == 30
        assert usage.total_tokens == 42

    @pytest.mark.asyncio
    async def test_total_derived_when_absent(self):
        out = await _run([{"usageEvent": {"inputTokens": 5, "outputTokens": 7}}, END])
        assert _terminal_usage(out).total_tokens == 12

    @pytest.mark.asyncio
    async def test_unknown_shape_tolerated(self):
        """The real schema is unverified — a wrong guess must not break voice."""
        out = await _run([{"usageEvent": {"somethingElse": {"nested": True}}}, END])
        usage = _terminal_usage(out)
        assert usage.total_tokens == 0
        assert out[-1].is_complete is True

    @pytest.mark.asyncio
    async def test_raw_frame_preserved_for_schema_discovery(self):
        frame = {"inputTokens": 1, "outputTokens": 2}
        out = await _run([{"usageEvent": frame}, END])
        assert _terminal_usage(out).extra["usage_event"] == frame

    @pytest.mark.asyncio
    async def test_real_nova_sonic_schema(self):
        """The documented Nova Sonic usageEvent shape (spec §8 Q1).

        Corroborated by a live Nova 2 session on 2026-09-08: only
        ``totalTokens`` matched the original guess list, so the example UI
        showed ``tokens: 883`` next to ``in/out: 0/0``. The exact modality
        breakdown below is from the AWS schema, not from that session's log.
        """
        out = await _run(
            [
                {
                    "usageEvent": {
                        "completionId": "c-1",
                        "promptName": "p-1",
                        "sessionId": "s-1",
                        "details": {
                            "delta": {
                                "input": {"speechTokens": 40, "textTokens": 2},
                                "output": {"speechTokens": 10, "textTokens": 1},
                            },
                            "total": {
                                "input": {"speechTokens": 800, "textTokens": 12},
                                "output": {"speechTokens": 60, "textTokens": 11},
                            },
                        },
                        "totalInputTokens": 812,
                        "totalOutputTokens": 71,
                        "totalTokens": 883,
                    }
                },
                END,
            ]
        )
        usage = _terminal_usage(out)
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (812, 71, 883)

    @pytest.mark.asyncio
    async def test_modality_breakdown_used_when_top_level_totals_absent(self):
        """Falls back to details.total.input/output, summed across modalities."""
        out = await _run(
            [
                {
                    "usageEvent": {
                        "details": {
                            "delta": {"input": {"speechTokens": 1}, "output": {"speechTokens": 1}},
                            "total": {
                                "input": {"speechTokens": 800, "textTokens": 12},
                                "output": {"speechTokens": 60, "textTokens": 11},
                            },
                        }
                    }
                },
                END,
            ]
        )
        usage = _terminal_usage(out)
        # 812/71 comes from `total`, never from the smaller `delta` block.
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (812, 71, 883)

    @pytest.mark.asyncio
    async def test_alias_fields_kept_in_sync(self):
        """``__post_init__`` only syncs at construction; consumers read both.

        ``VoiceChatHandler._send_complete_voice_response()`` serializes
        ``usage.input_tokens``/``output_tokens``.
        """
        out = await _run([{"usageEvent": {"totalInputTokens": 9, "totalOutputTokens": 4}}, END])
        usage = _terminal_usage(out)
        assert (usage.input_tokens, usage.output_tokens) == (9, 4)

    @pytest.mark.asyncio
    async def test_websocket_usage_not_all_zero(self):
        out = await _run(
            [
                {"usageEvent": {"inputTokens": 3, "outputTokens": 4}},
                END,
            ]
        )
        msg = [r for r in out if r.is_complete][-1].to_websocket_message()
        assert msg["usage"]["total_tokens"] == 7


class TestTurnTiming:
    @pytest.mark.asyncio
    async def test_terminal_frame_reports_response_time(self):
        """The turn must be closed so `response_time_ms` is non-zero.

        The example UI renders its latency counter only on a truthy
        ``response_time_ms``, so a turn left open reports no latency at all.
        """
        out = await _run([{"textOutput": {"content": "hi"}}, END])
        final = [r for r in out if r.is_complete][-1]
        assert final.turn_metadata.ended_at is not None
        assert final.usage.response_time_ms > 0

    @pytest.mark.asyncio
    async def test_first_token_stamped_on_first_model_output(self):
        out = await _run(
            [
                {"contentStart": {"role": "ASSISTANT", "type": "TEXT"}},
                {"textOutput": {"content": "hello"}},
                END,
            ]
        )
        assert _terminal_usage(out).first_token_time_ms > 0
