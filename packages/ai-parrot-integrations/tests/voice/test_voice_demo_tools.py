"""Unit tests for FEAT-536 TASK-2948 — the Voice demo's shared
dual-output tool (``examples/clients/voice/server.py``'s
``VoiceDemoWeatherTool``).

``examples/clients/voice/server.py`` is a standalone script, not part of
any installed package — imported here via ``importlib.util`` from its
file path (same pattern as TASK-2943's ``test_voice_demo_assets.py``).

The real ``aws_sdk_bedrock_runtime`` package (Pre-Alpha, requires Python
>= 3.12) is not installed in this sandbox — ``sys.modules`` is stubbed
before each module (re)load, the same trick
``packages/ai-parrot/tests/clients/test_nova_dual_output.py`` and
``packages/ai-parrot/tests/voice/conftest.py`` already use, so
``make_nova_bot()`` can be exercised for real (``NovaClient`` constructs
fine without the SDK — only its first ``stream_voice()`` call needs it,
never called here) instead of being skipped entirely.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.tools.abstract import ToolResult

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_PATH = _REPO_ROOT / "examples" / "clients" / "voice" / "server.py"


def _load_server_module():
    """Import examples/clients/voice/server.py by file path.

    A fresh module object per call (not cached under a fixed name across
    tests) so each test can safely rely on its own env-var/NOVA_AVAILABLE
    state without leaking into other tests.
    """
    spec = importlib.util.spec_from_file_location("voice_demo_server_tools_under_test", _SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_module(monkeypatch):
    # Stubbed BEFORE the module loads — server.py's NOVA_AVAILABLE is
    # computed once at import time via a real `import
    # aws_sdk_bedrock_runtime` attempt.
    monkeypatch.setitem(sys.modules, "aws_sdk_bedrock_runtime", MagicMock())
    module = _load_server_module()
    yield module
    sys.modules.pop("voice_demo_server_tools_under_test", None)


# ── test_voice_demo_factories_do_not_share_tools ──────────────────────────


class TestVoiceDemoFactoriesDoNotShareTools:
    def test_voice_demo_factories_do_not_share_tools(self, server_module):
        bot_gemini_1 = server_module.make_gemini_bot()
        bot_gemini_2 = server_module.make_gemini_bot()
        bot_nova = server_module.make_nova_bot()

        tool_gemini_1 = bot_gemini_1.tool_manager.get_tool("get_weather")
        tool_gemini_2 = bot_gemini_2.tool_manager.get_tool("get_weather")
        tool_nova = bot_nova.tool_manager.get_tool("get_weather")

        # Every factory call constructs its OWN fresh tool object — never
        # a shared module-level singleton, even across two calls to the
        # SAME factory.
        assert tool_gemini_1 is not tool_gemini_2
        assert tool_gemini_1 is not tool_nova
        assert tool_gemini_2 is not tool_nova

        # ... while sharing the identical definition/behavior (same
        # class, same name/description) — comparable across providers.
        for t in (tool_gemini_1, tool_gemini_2, tool_nova):
            assert isinstance(t, server_module.VoiceDemoWeatherTool)
            assert t.name == "get_weather"
            assert t.description == tool_gemini_1.description

    def test_mutating_one_instance_does_not_affect_another(self, server_module):
        """Per-instance mutable state (the resolved demo delay) proves
        isolation concretely, not just object identity."""
        tool_a = server_module.VoiceDemoWeatherTool()
        tool_b = server_module.VoiceDemoWeatherTool()
        tool_a._delay_seconds = 7.5
        assert tool_b._delay_seconds != 7.5


# ── test_voice_demo_tool_returns_speech_and_display ───────────────────────


class TestVoiceDemoToolReturnsSpeechAndDisplay:
    @pytest.mark.asyncio
    async def test_voice_demo_tool_returns_speech_and_display(self, server_module):
        tool = server_module.VoiceDemoWeatherTool()

        result = await tool.execute(location="Miami")

        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.success is True
        assert result.voice_text == "It's sunny and 25 degrees Celsius in Miami."
        assert result.display_data == {
            "kind": "weather",
            "location": "Miami",
            "condition": "sunny",
            "temp_c": 25,
            "demo_fixture": True,
        }
        # Structured result stays available alongside the spoken/visual
        # fields (spec §3 Module 6: "a deterministic AbstractTool
        # returning a ToolResult with a short spoken sentence, a nested
        # JSON visual object").
        assert result.result == {"location": "Miami", "condition": "sunny", "temp_c": 25}

    @pytest.mark.asyncio
    async def test_missing_location_falls_back_to_generic_label(self, server_module):
        tool = server_module.VoiceDemoWeatherTool()
        result = await tool.execute()
        assert "your area" in result.voice_text
        assert result.display_data["location"] == "your area"

    @pytest.mark.asyncio
    async def test_gemini_and_nova_bots_get_semantically_identical_output(self, server_module):
        """Both provider bots' fresh tool instances produce the SAME
        spoken/visual output for the same input — directly comparable
        across providers (spec §3 Module 12 Key Constraints)."""
        bot_gemini = server_module.make_gemini_bot()
        bot_nova = server_module.make_nova_bot()

        tool_gemini = bot_gemini.tool_manager.get_tool("get_weather")
        tool_nova = bot_nova.tool_manager.get_tool("get_weather")

        result_gemini = await tool_gemini.execute(location="Austin")
        result_nova = await tool_nova.execute(location="Austin")

        assert result_gemini.voice_text == result_nova.voice_text
        assert result_gemini.display_data == result_nova.display_data


# ── test_voice_demo_slow_tool_is_bounded ──────────────────────────────────


class TestVoiceDemoSlowToolIsBounded:
    def test_default_delay_is_zero(self, server_module, monkeypatch):
        monkeypatch.delenv(server_module.VoiceDemoWeatherTool._DELAY_ENV_VAR, raising=False)
        tool = server_module.VoiceDemoWeatherTool()
        assert tool._delay_seconds == 0.0

    def test_invalid_env_value_disables_delay(self, server_module, monkeypatch):
        monkeypatch.setenv(server_module.VoiceDemoWeatherTool._DELAY_ENV_VAR, "not-a-number")
        tool = server_module.VoiceDemoWeatherTool()
        assert tool._delay_seconds == 0.0

    def test_delay_is_clamped_to_the_documented_maximum(self, server_module, monkeypatch):
        monkeypatch.setenv(server_module.VoiceDemoWeatherTool._DELAY_ENV_VAR, "999")
        tool = server_module.VoiceDemoWeatherTool()
        assert tool._delay_seconds == server_module.VoiceDemoWeatherTool._MAX_DEMO_DELAY_SECONDS

    def test_negative_delay_clamps_to_zero(self, server_module, monkeypatch):
        monkeypatch.setenv(server_module.VoiceDemoWeatherTool._DELAY_ENV_VAR, "-5")
        tool = server_module.VoiceDemoWeatherTool()
        assert tool._delay_seconds == 0.0

    @pytest.mark.asyncio
    async def test_slow_tool_actually_awaits_the_bounded_delay(self, server_module, monkeypatch):
        """The configured (and clamped) delay is genuinely awaited before
        the tool answers — proving the real-live interruption scenario
        (spec §4) has time to actually interrupt it. asyncio.sleep is
        replaced with an instrumented stand-in (not skipped) so this test
        does not need to wait 30 real seconds."""
        monkeypatch.setenv(server_module.VoiceDemoWeatherTool._DELAY_ENV_VAR, "999")
        tool = server_module.VoiceDemoWeatherTool()
        assert tool._delay_seconds == server_module.VoiceDemoWeatherTool._MAX_DEMO_DELAY_SECONDS

        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with patch("asyncio.sleep", new=_fake_sleep):
            result = await tool.execute(location="Denver")

        assert sleep_calls == [server_module.VoiceDemoWeatherTool._MAX_DEMO_DELAY_SECONDS]
        assert result.success is True

    @pytest.mark.asyncio
    async def test_zero_delay_never_calls_sleep(self, server_module, monkeypatch):
        monkeypatch.delenv(server_module.VoiceDemoWeatherTool._DELAY_ENV_VAR, raising=False)
        tool = server_module.VoiceDemoWeatherTool()

        with patch("asyncio.sleep", new=AsyncMock()) as fake_sleep:
            await tool.execute(location="Denver")

        fake_sleep.assert_not_awaited()
