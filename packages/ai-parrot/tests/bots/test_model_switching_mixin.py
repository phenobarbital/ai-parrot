"""Unit tests for ModelSwitchingMixin.

Mirrors the pattern used by test_identity_mixin.py: extract the REAL, unbound
``AbstractBot.get_client`` / ``AbstractBot.execute_llm_call`` hooks and mix
them into a minimal fake base class, so ModelSwitchingMixin is exercised
against the actual framework logic it chains into (via ``super()``) rather
than a hand-rolled stand-in. Fake LLM clients — no network.
"""
import asyncio
import sys
from unittest.mock import MagicMock

import pytest

from parrot.bots.mixins import ModelSwitchingMixin, ModelSwitchMode
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

_RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot
_get_client = _RealAbstractBot.get_client
_execute_llm_call = _RealAbstractBot.execute_llm_call


def make_message(text: str, provider: str, model: str, **kwargs) -> AIMessage:
    """Build a minimal real AIMessage."""
    return AIMessage(
        input="question",
        output=text,
        response=text,
        model=model,
        provider=provider,
        usage=CompletionUsage(
            prompt_tokens=kwargs.pop("prompt_tokens", 10),
            completion_tokens=kwargs.pop("completion_tokens", 5),
            total_tokens=kwargs.pop("total_tokens", 15),
        ),
        **kwargs,
    )


class FakeClient:
    """AbstractClient-shaped stub: async context manager + ask()."""

    def __init__(self, name: str, model: str, *, answer=None, error=None):
        self.client_name = name
        self.model = model
        self.answer = answer
        self.error = error
        self.ask_calls = []
        self.entered = 0
        self.exited = 0
        self.closed = False

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1
        return False

    async def ask(self, **kwargs):
        self.ask_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.answer

    async def close(self):
        self.closed = True


class FakeBase:
    """Minimal stand-in exposing the AbstractBot seams the mixin needs."""

    # Real framework hooks — the mixin's super() chain lands here.
    get_client = _get_client
    execute_llm_call = _execute_llm_call

    def __init__(self, **kwargs):
        self.name = kwargs.pop("name", "TestBot")
        self._llm = kwargs.pop("primary_client", None)
        self.logger = MagicMock()
        self.events_triggered = []
        self.post_configure_chained = False
        self.configure_llm_calls = []
        self._configure_llm_result = kwargs.pop("configure_llm_result", None)

    async def post_configure(self):
        self.post_configure_chained = True

    def configure_llm(self, **kwargs):
        self.configure_llm_calls.append(kwargs)
        if self._configure_llm_result is None:
            raise ValueError("no secondary available")
        return self._configure_llm_result

    def _trigger_event(self, event_name, **kwargs):
        self.events_triggered.append((event_name, kwargs))

    async def cleanup(self):
        self.base_cleanup_ran = True


class SwitchingBot(ModelSwitchingMixin, FakeBase):
    """Bot under test."""


def make_bot(mode, primary, secondary, **kwargs):
    bot = SwitchingBot(
        primary_client=primary,
        model_switch_mode=mode,
        secondary_llm="stub:secondary" if secondary is not None else None,
        **kwargs,
    )
    bot._secondary_client = secondary
    return bot


PRIMARY_OK = lambda: make_message("primary answer", "google", "gemini-x")  # noqa: E731
SECONDARY_OK = lambda: make_message("secondary answer", "anthropic", "claude-y")  # noqa: E731


# ── 1. Default hooks (no mixin) ─────────────────────────────────────────────

class TestDefaultHooks:
    def test_get_client_returns_primary(self):
        primary = FakeClient("google", "gemini-x")
        base = FakeBase(primary_client=primary)
        assert base.get_client() is primary

    @pytest.mark.asyncio
    async def test_execute_llm_call_delegates_to_client(self):
        msg = PRIMARY_OK()
        primary = FakeClient("google", "gemini-x", answer=msg)
        base = FakeBase(primary_client=primary)
        result = await base.execute_llm_call(primary, "ask", prompt="hi")
        assert result is msg
        assert primary.ask_calls == [{"prompt": "hi"}]
        # No annotation is added by the default hook
        assert "model_switching" not in result.metadata


# ── 2–5. Fallback mode ──────────────────────────────────────────────────────

class TestFallbackMode:
    @pytest.mark.asyncio
    async def test_primary_success_no_switch(self):
        primary = FakeClient("google", "gemini-x", answer=PRIMARY_OK())
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        result = await bot.execute_llm_call(primary, "ask", prompt="hi")

        assert result.output == "primary answer"
        ms = result.metadata["model_switching"]
        assert ms["mode"] == "fallback"
        assert ms["switched"] is False
        assert ms["served_by"] == {"provider": "google", "model": "gemini-x"}
        assert secondary.ask_calls == []

    @pytest.mark.asyncio
    async def test_primary_error_switches_to_secondary(self):
        primary = FakeClient(
            "google", "gemini-x", error=RuntimeError("provider down")
        )
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        result = await bot.execute_llm_call(primary, "ask", prompt="hi")

        assert result.output == "secondary answer"
        ms = result.metadata["model_switching"]
        assert ms["switched"] is True
        assert ms["primary"]["provider"] == "google"
        assert ms["primary"]["error_type"] == "RuntimeError"
        assert "provider down" in ms["primary"]["error"]
        assert ms["served_by"] == {"provider": "anthropic", "model": "claude-y"}
        # Secondary context was entered and exited by the mixin
        assert secondary.entered == 1
        assert secondary.exited == 1
        # Same kwargs forwarded
        assert secondary.ask_calls == [{"prompt": "hi"}]
        # Event emitted
        assert bot.events_triggered
        event_name, payload = bot.events_triggered[0]
        assert event_name == ModelSwitchingMixin.EVENT_MODEL_SWITCHED
        assert payload["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_both_fail_raises_primary_error(self):
        primary_err = RuntimeError("primary down")
        primary = FakeClient("google", "gemini-x", error=primary_err)
        secondary = FakeClient(
            "anthropic", "claude-y", error=ValueError("secondary down")
        )
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        with pytest.raises(RuntimeError, match="primary down") as excinfo:
            await bot.execute_llm_call(primary, "ask", prompt="hi")
        assert isinstance(excinfo.value.__cause__, ValueError)

    @pytest.mark.asyncio
    async def test_should_switch_on_veto(self):
        class PickyBot(SwitchingBot):
            def should_switch_on(self, error):
                return False

        primary = FakeClient("google", "gemini-x", error=RuntimeError("boom"))
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = PickyBot(
            primary_client=primary,
            model_switch_mode=ModelSwitchMode.FALLBACK,
            secondary_llm="stub:secondary",
        )
        bot._secondary_client = secondary

        with pytest.raises(RuntimeError, match="boom"):
            await bot.execute_llm_call(primary, "ask", prompt="hi")
        assert secondary.ask_calls == []

    @pytest.mark.asyncio
    async def test_cancellation_never_switches(self):
        primary = FakeClient(
            "google", "gemini-x", error=asyncio.CancelledError()
        )
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        with pytest.raises(asyncio.CancelledError):
            await bot.execute_llm_call(primary, "ask", prompt="hi")
        assert secondary.ask_calls == []


# ── 6–7. Contrastive mode ───────────────────────────────────────────────────

class TestContrastiveMode:
    @pytest.mark.asyncio
    async def test_both_succeed_combined_output(self):
        primary = FakeClient("google", "gemini-x", answer=PRIMARY_OK())
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(ModelSwitchMode.CONTRASTIVE, primary, secondary)

        result = await bot.execute_llm_call(primary, "ask", prompt="hi")

        # Combined labeled markdown
        assert "### google:gemini-x (primary)" in result.output
        assert "primary answer" in result.output
        assert "### anthropic:claude-y (secondary)" in result.output
        assert "secondary answer" in result.output
        # Attribution metadata
        ms = result.metadata["model_switching"]
        assert ms["mode"] == "contrastive"
        roles = {e["role"]: e for e in ms["responses"]}
        assert roles["primary"]["provider"] == "google"
        assert roles["primary"]["output"] == "primary answer"
        assert roles["secondary"]["provider"] == "anthropic"
        assert roles["secondary"]["output"] == "secondary answer"
        assert roles["primary"]["usage"]["prompt_tokens"] == 10
        # Both clients were actually called with the same kwargs
        assert primary.ask_calls == [{"prompt": "hi"}]
        assert secondary.ask_calls == [{"prompt": "hi"}]
        # Aggregated usage on the carrier message
        assert result.usage.prompt_tokens == 20
        assert result.usage.completion_tokens == 10
        assert result.usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_one_side_fails_returns_survivor(self):
        primary = FakeClient("google", "gemini-x", error=RuntimeError("down"))
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(ModelSwitchMode.CONTRASTIVE, primary, secondary)

        result = await bot.execute_llm_call(primary, "ask", prompt="hi")

        assert result.output == "secondary answer"
        ms = result.metadata["model_switching"]
        roles = {e["role"]: e for e in ms["responses"]}
        assert roles["primary"]["error_type"] == "RuntimeError"
        assert roles["secondary"]["output"] == "secondary answer"

    @pytest.mark.asyncio
    async def test_both_fail_raises_primary_error(self):
        primary = FakeClient("google", "gemini-x", error=RuntimeError("p-down"))
        secondary = FakeClient("anthropic", "claude-y", error=ValueError("s-down"))
        bot = make_bot(ModelSwitchMode.CONTRASTIVE, primary, secondary)

        with pytest.raises(RuntimeError, match="p-down"):
            await bot.execute_llm_call(primary, "ask", prompt="hi")

    @pytest.mark.asyncio
    async def test_structured_output_keeps_primary_output(self):
        primary = FakeClient("google", "gemini-x", answer=PRIMARY_OK())
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(ModelSwitchMode.CONTRASTIVE, primary, secondary)

        result = await bot.execute_llm_call(
            primary, "ask", prompt="hi", structured_output=object()
        )

        # Output NOT rewritten for structured calls; attribution still present
        assert result.output == "primary answer"
        assert result.metadata["model_switching"]["mode"] == "contrastive"


# ── 8. Passthrough ──────────────────────────────────────────────────────────

class TestPassthrough:
    @pytest.mark.asyncio
    async def test_disabled_is_pure_passthrough(self):
        primary = FakeClient("google", "gemini-x", answer=PRIMARY_OK())
        secondary = FakeClient("anthropic", "claude-y", answer=SECONDARY_OK())
        bot = make_bot(
            ModelSwitchMode.FALLBACK, primary, secondary,
            enable_model_switching=False,
        )

        result = await bot.execute_llm_call(primary, "ask", prompt="hi")
        assert result.output == "primary answer"
        assert "model_switching" not in result.metadata
        assert secondary.ask_calls == []

    @pytest.mark.asyncio
    async def test_no_secondary_is_pure_passthrough(self):
        primary = FakeClient("google", "gemini-x", answer=PRIMARY_OK())
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, None)

        result = await bot.execute_llm_call(primary, "ask", prompt="hi")
        assert result.output == "primary answer"
        assert "model_switching" not in result.metadata

    @pytest.mark.asyncio
    async def test_non_ask_method_is_passthrough(self):
        primary = FakeClient("google", "gemini-x", answer=PRIMARY_OK())
        secondary = FakeClient("anthropic", "claude-y", error=RuntimeError("x"))
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        async def other(**kwargs):
            return "other-result"

        primary.other = other
        result = await bot.execute_llm_call(primary, "other", prompt="hi")
        assert result == "other-result"
        assert secondary.ask_calls == []

    def test_get_client_still_returns_primary(self):
        primary = FakeClient("google", "gemini-x")
        secondary = FakeClient("anthropic", "claude-y")
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)
        assert bot.get_client() is primary


# ── 9. post_configure wiring + lifecycle ────────────────────────────────────

class TestConfiguration:
    @pytest.mark.asyncio
    async def test_post_configure_builds_secondary_and_chains_super(self):
        secondary = FakeClient("anthropic", "claude-y")
        bot = SwitchingBot(
            secondary_llm="anthropic:claude-y",
            configure_llm_result=secondary,
        )
        await bot.post_configure()

        assert bot.post_configure_chained is True
        assert bot._secondary_client is secondary
        assert bot.configure_llm_calls == [{"llm": "anthropic:claude-y"}]

    @pytest.mark.asyncio
    async def test_post_configure_dict_spec_uses_model_config(self):
        secondary = FakeClient("anthropic", "claude-y")
        spec = {"name": "anthropic", "model": "claude-y"}
        bot = SwitchingBot(
            secondary_llm=spec,
            configure_llm_result=secondary,
        )
        await bot.post_configure()
        assert bot.configure_llm_calls == [{"model_config": spec}]

    @pytest.mark.asyncio
    async def test_post_configure_resolution_failure_raises_config_error(self):
        from parrot.exceptions import ConfigError

        bot = SwitchingBot(secondary_llm="nope:nope")  # configure_llm raises
        with pytest.raises(ConfigError):
            await bot.post_configure()

    @pytest.mark.asyncio
    async def test_post_configure_noop_without_secondary(self):
        bot = SwitchingBot()
        await bot.post_configure()
        assert bot.post_configure_chained is True
        assert bot._secondary_client is None
        assert bot.configure_llm_calls == []

    def test_string_mode_kwarg_is_normalized(self):
        bot = SwitchingBot(model_switch_mode="contrastive")
        assert bot.model_switch_mode is ModelSwitchMode.CONTRASTIVE

    @pytest.mark.asyncio
    async def test_cleanup_closes_secondary_and_chains(self):
        primary = FakeClient("google", "gemini-x")
        secondary = FakeClient("anthropic", "claude-y")
        bot = make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        await bot.cleanup()
        assert secondary.closed is True
        assert bot._secondary_client is None
        assert bot.base_cleanup_ran is True
