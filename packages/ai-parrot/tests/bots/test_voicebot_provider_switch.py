"""Tests for VoiceBot provider switching and token usage accumulation.

Verifies that:
  1. VoiceConfig can be mutated to switch between providers at runtime.
  2. VoiceBot source contains the lazy-client pattern that enables hot-swap.
  3. LiveCompletionUsage correctly tracks and accumulates token metrics.
  4. The example ``switch_provider()`` logic produces the expected state.

The Cython ``parrot.utils.types`` extension is not built in this test
environment, so ``parrot.bots`` cannot be imported directly.  Config-level
tests use the real ``VoiceConfig``; wiring tests use AST source inspection
(same strategy as ``test_voicebot_nova_wiring.py``).
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from parrot.clients.live import (
    LiveCompletionUsage,
    LiveToolCall,
    LiveVoiceResponse,
)
from parrot.models.voice import VoiceConfig

VOICE_BOT_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "parrot" / "bots" / "voice.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_voicebot_method(method_name: str) -> str:
    """Extract a VoiceBot method's source text via AST."""
    source = VOICE_BOT_SOURCE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "VoiceBot":
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return ast.get_source_segment(source, item)
    raise AssertionError(f"Method {method_name} not found in VoiceBot")


class _FakeLLM:
    """Minimal stand-in for an LLM client to verify close/reset logic."""

    def __init__(self, provider: str):
        self.provider = provider
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeVoiceBot:
    """Minimal struct that mirrors VoiceBot's switch-relevant attributes.

    Used to unit-test the ``switch_provider`` function from the example
    without importing the real VoiceBot (blocked by Cython).
    """

    def __init__(self, voice_config: VoiceConfig):
        self.voice_config = voice_config
        self._llm: Optional[_FakeLLM] = _FakeLLM(voice_config.provider)


async def switch_provider(bot: _FakeVoiceBot, new_provider: str) -> None:
    """Exact replica of the example helper — operates on any object
    with ``._llm`` and ``.voice_config``."""
    if bot._llm is not None:
        try:
            await bot._llm.close()
        except Exception:
            pass
        bot._llm = None

    bot.voice_config.provider = new_provider
    if new_provider == "nova":
        bot.voice_config.voice_name = "matthew"
        bot.voice_config.model = "nova-2-sonic"
    else:
        bot.voice_config.voice_name = "Puck"
        bot.voice_config.model = "gemini-2.5-flash-native-audio-preview-12-2025"


# ===================================================================
# 1. VoiceConfig provider mutation
# ===================================================================

class TestVoiceConfigProviderSwitch:
    """VoiceConfig is a mutable dataclass — switching provider at runtime
    must update all related fields consistently."""

    def test_switch_google_to_nova(self):
        cfg = VoiceConfig(provider="google_live", voice_name="Puck")
        cfg.provider = "nova"
        cfg.voice_name = "matthew"
        cfg.model = "nova-2-sonic"
        assert cfg.provider == "nova"
        assert cfg.voice_name == "matthew"
        assert cfg.model == "nova-2-sonic"

    def test_switch_nova_to_google(self):
        cfg = VoiceConfig(provider="nova", voice_name="matthew", model="nova-2-sonic")
        cfg.provider = "google_live"
        cfg.voice_name = "Kore"
        assert cfg.provider == "google_live"
        assert cfg.voice_name == "Kore"

    def test_round_trip_preserves_non_provider_fields(self):
        cfg = VoiceConfig(
            provider="google_live",
            temperature=0.5,
            enable_vad=False,
            language="es-ES",
        )
        cfg.provider = "nova"
        cfg.provider = "google_live"
        assert cfg.temperature == 0.5
        assert cfg.enable_vad is False
        assert cfg.language == "es-ES"


# ===================================================================
# 2. VoiceBot wiring supports lazy client creation (AST)
# ===================================================================

class TestVoiceBotLazyClientWiring:
    """The hot-swap pattern works because VoiceBot lazily creates
    ``self._llm`` when it is ``None``.  Verify that both ``ask_stream``
    and ``ask`` contain that guard."""

    def test_ask_stream_lazy_creates_client(self):
        src = _get_voicebot_method("ask_stream")
        assert "self._llm is None" in src
        assert "_resolve_llm_config" in src
        assert "_create_llm_client" in src

    def test_ask_lazy_creates_client(self):
        src = _get_voicebot_method("ask")
        assert "self._llm is None" in src
        assert "_resolve_llm_config" in src
        assert "_create_llm_client" in src

    def test_resolve_branches_on_provider(self):
        src = _get_voicebot_method("_resolve_llm_config")
        assert "self.voice_config.provider" in src
        assert "'nova'" in src
        assert "'gemini_live'" in src

    def test_create_branches_on_provider(self):
        src = _get_voicebot_method("_create_llm_client")
        assert "config.provider" in src
        assert "'nova'" in src
        assert "GeminiLiveClient" in src


# ===================================================================
# 3. switch_provider() example helper
# ===================================================================

class TestSwitchProviderHelper:
    """End-to-end test of the switch logic from examples/voice/bot.py."""

    @pytest.mark.asyncio
    async def test_switch_closes_old_client(self):
        bot = _FakeVoiceBot(VoiceConfig(provider="google_live"))
        old_llm = bot._llm
        await switch_provider(bot, "nova")
        assert old_llm.closed is True
        assert bot._llm is None

    @pytest.mark.asyncio
    async def test_switch_to_nova_updates_config(self):
        bot = _FakeVoiceBot(VoiceConfig(provider="google_live"))
        await switch_provider(bot, "nova")
        assert bot.voice_config.provider == "nova"
        assert bot.voice_config.voice_name == "matthew"
        assert bot.voice_config.model == "nova-2-sonic"

    @pytest.mark.asyncio
    async def test_switch_to_google_updates_config(self):
        bot = _FakeVoiceBot(VoiceConfig(provider="nova", model="nova-2-sonic"))
        await switch_provider(bot, "google_live")
        assert bot.voice_config.provider == "google_live"
        assert bot.voice_config.voice_name == "Puck"
        assert "native-audio" in bot.voice_config.model

    @pytest.mark.asyncio
    async def test_round_trip_switch(self):
        bot = _FakeVoiceBot(VoiceConfig(provider="google_live"))
        await switch_provider(bot, "nova")
        await switch_provider(bot, "google_live")
        assert bot.voice_config.provider == "google_live"
        assert bot._llm is None

    @pytest.mark.asyncio
    async def test_switch_when_llm_already_none(self):
        bot = _FakeVoiceBot(VoiceConfig(provider="google_live"))
        bot._llm = None
        await switch_provider(bot, "nova")
        assert bot.voice_config.provider == "nova"


# ===================================================================
# 4. Token usage tracking and accumulation
# ===================================================================

class TestLiveCompletionUsageAccumulation:
    """Verify LiveCompletionUsage arithmetic used to track tokens
    across streaming chunks and provider switches."""

    def test_total_tokens_auto_calculated(self):
        usage = LiveCompletionUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.total_tokens == 150

    def test_alias_sync_input_to_prompt(self):
        usage = LiveCompletionUsage(input_tokens=200, output_tokens=80)
        assert usage.prompt_tokens == 200
        assert usage.completion_tokens == 80
        assert usage.total_tokens == 280

    def test_from_gemini_usage_with_none(self):
        usage = LiveCompletionUsage.from_gemini_usage(None)
        assert usage.total_tokens == 0

    def test_audio_duration_fields(self):
        usage = LiveCompletionUsage(
            input_audio_duration_ms=3200.0,
            output_audio_duration_ms=5400.0,
        )
        assert usage.input_audio_duration_ms == 3200.0
        assert usage.output_audio_duration_ms == 5400.0

    def test_tool_execution_metrics(self):
        usage = LiveCompletionUsage(
            tool_calls_executed=2,
            tool_execution_time_ms=345.6,
        )
        assert usage.tool_calls_executed == 2
        assert usage.tool_execution_time_ms == 345.6


def _make_usage(**kwargs) -> LiveCompletionUsage:
    return LiveCompletionUsage(**kwargs)


class TestTokenAccumulationAcrossChunks:
    """Simulate streaming chunks with partial usage and accumulate totals
    — the pattern used in VoiceBot.ask_voice() and the example demo."""

    @staticmethod
    def _accumulate(responses: List[LiveVoiceResponse]) -> Dict[str, Any]:
        """Mirrors the accumulation logic in VoiceBot.ask_voice()."""
        full_text = ""
        audio_bytes = 0
        tool_calls: List[LiveToolCall] = []
        total_prompt = 0
        total_completion = 0
        total_audio_in_ms = 0.0
        total_audio_out_ms = 0.0
        total_tool_time_ms = 0.0
        total_tool_calls = 0
        response_time_ms = 0.0

        for resp in responses:
            if resp.text:
                full_text += resp.text
            if resp.audio_data:
                audio_bytes += len(resp.audio_data)
            if resp.tool_calls:
                tool_calls.extend(resp.tool_calls)
            if resp.usage:
                total_prompt += resp.usage.prompt_tokens
                total_completion += resp.usage.completion_tokens
                total_audio_in_ms += resp.usage.input_audio_duration_ms
                total_audio_out_ms += resp.usage.output_audio_duration_ms
                total_tool_calls += resp.usage.tool_calls_executed
                total_tool_time_ms += resp.usage.tool_execution_time_ms
                response_time_ms = max(response_time_ms, resp.usage.response_time_ms)

        return {
            "text": full_text,
            "audio_bytes": audio_bytes,
            "tool_calls": tool_calls,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "audio_in_ms": total_audio_in_ms,
            "audio_out_ms": total_audio_out_ms,
            "tool_calls_count": total_tool_calls,
            "tool_time_ms": total_tool_time_ms,
            "response_time_ms": response_time_ms,
        }

    def test_accumulate_text_chunks(self):
        responses = [
            LiveVoiceResponse(text="Hello "),
            LiveVoiceResponse(text="world!"),
            LiveVoiceResponse(
                text="",
                is_complete=True,
                usage=_make_usage(prompt_tokens=10, completion_tokens=5),
            ),
        ]
        acc = self._accumulate(responses)
        assert acc["text"] == "Hello world!"
        assert acc["total_tokens"] == 15

    def test_accumulate_audio_chunks(self):
        responses = [
            LiveVoiceResponse(audio_data=b"\x00" * 1024),
            LiveVoiceResponse(audio_data=b"\x00" * 2048),
            LiveVoiceResponse(
                is_complete=True,
                usage=_make_usage(
                    output_audio_duration_ms=3000.0,
                    completion_tokens=20,
                ),
            ),
        ]
        acc = self._accumulate(responses)
        assert acc["audio_bytes"] == 3072
        assert acc["audio_out_ms"] == 3000.0

    def test_accumulate_tool_calls(self):
        tc = LiveToolCall(
            id="tc-1",
            name="get_weather",
            arguments={"location": "Miami"},
            result="Sunny, 30°C",
            execution_time_ms=120.0,
        )
        responses = [
            LiveVoiceResponse(
                text="Let me check... ",
                tool_calls=[tc],
                usage=_make_usage(
                    prompt_tokens=50,
                    completion_tokens=30,
                    tool_calls_executed=1,
                    tool_execution_time_ms=120.0,
                ),
            ),
            LiveVoiceResponse(
                text="It's sunny in Miami!",
                is_complete=True,
                usage=_make_usage(
                    prompt_tokens=0,
                    completion_tokens=10,
                ),
            ),
        ]
        acc = self._accumulate(responses)
        assert acc["tool_calls_count"] == 1
        assert acc["tool_time_ms"] == 120.0
        assert len(acc["tool_calls"]) == 1
        assert acc["tool_calls"][0].name == "get_weather"
        assert acc["total_tokens"] == 90

    def test_accumulate_across_providers(self):
        """Simulate usage from two provider rounds (Gemini then Nova)
        being summed in a session-level accumulator."""
        gemini_usage = _make_usage(
            prompt_tokens=100,
            completion_tokens=60,
            input_audio_duration_ms=2000.0,
            output_audio_duration_ms=3500.0,
            response_time_ms=450.0,
        )
        nova_usage = _make_usage(
            prompt_tokens=80,
            completion_tokens=45,
            input_audio_duration_ms=1800.0,
            output_audio_duration_ms=2900.0,
            response_time_ms=380.0,
        )
        responses = [
            LiveVoiceResponse(text="Gemini says hi", usage=gemini_usage, is_complete=True),
            LiveVoiceResponse(text="Nova says hi", usage=nova_usage, is_complete=True),
        ]
        acc = self._accumulate(responses)
        assert acc["prompt_tokens"] == 180
        assert acc["completion_tokens"] == 105
        assert acc["total_tokens"] == 285
        assert acc["audio_in_ms"] == 3800.0
        assert acc["audio_out_ms"] == 6400.0
        assert acc["response_time_ms"] == 450.0


# ===================================================================
# 5. LiveVoiceResponse metadata and provider tracking
# ===================================================================

class TestLiveVoiceResponseProviderMetadata:
    """Verify that provider info can ride in the metadata dict so callers
    know which backend produced each response chunk."""

    def test_metadata_carries_provider(self):
        resp = LiveVoiceResponse(
            text="Hello",
            metadata={"provider": "google_live"},
        )
        assert resp.metadata["provider"] == "google_live"

    def test_metadata_carries_nova_provider(self):
        resp = LiveVoiceResponse(
            text="Hi there",
            metadata={"provider": "nova"},
        )
        assert resp.metadata["provider"] == "nova"

    def test_tool_call_serialization(self):
        tc = LiveToolCall(
            id="tc-42",
            name="get_time",
            arguments={"timezone": "UTC"},
            result="12:00:00 UTC",
            execution_time_ms=15.5,
        )
        d = tc.to_dict()
        assert d["name"] == "get_time"
        assert d["execution_time_ms"] == 15.5
        assert d["result"] == "12:00:00 UTC"
