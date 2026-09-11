"""FEAT-550 M3 — BudgetError propagation through tools, manager and model switching (spec §4 'Exception propagation')."""

from __future__ import annotations

import asyncio

import pytest

from parrot.bots.mixins import ModelSwitchingMixin, ModelSwitchMode
from parrot.core.exceptions import BudgetError, BudgetExhausted
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager

pytestmark = pytest.mark.asyncio


class _ExhaustingTool(AbstractTool):
    name = "exhaust"
    description = "raises budget exhaustion"

    async def _execute(self, **kwargs):
        raise BudgetExhausted("child out of budget")


class _PlainFailingTool(AbstractTool):
    name = "boom"
    description = "raises a plain error"

    async def _execute(self, **kwargs):
        raise RuntimeError("boom")


class _AuthTool(AbstractTool):
    name = "needs_auth"
    description = "raises AuthorizationRequired"

    async def _execute(self, **kwargs):
        from parrot.auth.exceptions import AuthorizationRequired

        raise AuthorizationRequired("needs_auth", "needs auth")


class TestToolPropagation:
    async def test_abstract_tool_execute_reraises_budget_error(self):
        with pytest.raises(BudgetExhausted):
            await _ExhaustingTool().execute()

    async def test_plain_error_still_converted(self):
        result = await _PlainFailingTool().execute()
        assert result.status != "success"

    async def test_authorization_required_still_escapes(self):
        """Prove the existing escape-hatch order is intact after the new re-raise."""
        from parrot.auth.exceptions import AuthorizationRequired

        with pytest.raises(AuthorizationRequired):
            await _AuthTool().execute()

    async def test_manager_execute_tool_call_reraises(self):
        manager = ToolManager()
        manager.register_tool(_ExhaustingTool())
        manager.register_tool(_PlainFailingTool())

        with pytest.raises(BudgetExhausted):
            await manager.execute_tool_call({"name": "exhaust", "input": {}, "id": "t1"})

        result = await manager.execute_tool_call({"name": "boom", "input": {}, "id": "t2"})
        assert result["is_error"] is True


# ── Model switching fixtures (mirrors tests/bots/test_model_switching_mixin.py) ──

import sys  # noqa: E402

_RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot
_get_client = _RealAbstractBot.get_client
_execute_llm_call = _RealAbstractBot.execute_llm_call


def _make_message(text: str, provider: str, model: str) -> AIMessage:
    return AIMessage(
        input="question",
        output=text,
        response=text,
        model=model,
        provider=provider,
        usage=CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class _FakeClient:
    """AbstractClient-shaped stub: async context manager + ask()."""

    def __init__(self, name: str, model: str, *, answer=None, error=None):
        self.client_name = name
        self.model = model
        self.answer = answer
        self.error = error
        self.ask_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def ask(self, **kwargs):
        self.ask_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.answer

    async def close(self):
        pass


class _FakeBase:
    """Minimal stand-in exposing the AbstractBot seams the mixin needs."""

    get_client = _get_client
    execute_llm_call = _execute_llm_call

    def __init__(self, **kwargs):
        self.name = kwargs.pop("name", "TestBot")
        self._llm = kwargs.pop("primary_client", None)
        import unittest.mock

        self.logger = unittest.mock.MagicMock()
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


class _SwitchingBot(ModelSwitchingMixin, _FakeBase):
    """Bot under test."""


def _make_bot(mode, primary, secondary, **kwargs):
    bot = _SwitchingBot(
        primary_client=primary,
        model_switch_mode=mode,
        secondary_llm="stub:secondary" if secondary is not None else None,
        **kwargs,
    )
    bot._secondary_client = secondary
    return bot


class TestModelSwitching:
    async def test_should_switch_on_returns_false_for_budget_error(self):
        bot = _make_bot(ModelSwitchMode.FALLBACK, _FakeClient("google", "gemini-x"), None)
        assert bot.should_switch_on(BudgetExhausted("out of budget")) is False

    async def test_fallback_not_triggered_on_budget_error(self):
        primary = _FakeClient("google", "gemini-x", error=BudgetExhausted("out of budget"))
        secondary = _FakeClient("anthropic", "claude-y", answer=_make_message("secondary", "anthropic", "claude-y"))
        bot = _make_bot(ModelSwitchMode.FALLBACK, primary, secondary)

        with pytest.raises(BudgetExhausted):
            await bot.execute_llm_call(primary, "ask", prompt="hi")
        assert secondary.ask_calls == []

    async def test_contrastive_reraises_budget_error_instead_of_survivor(self):
        primary = _FakeClient("google", "gemini-x", answer=_make_message("primary", "google", "gemini-x"))
        secondary = _FakeClient("anthropic", "claude-y", error=BudgetExhausted("out of budget"))
        bot = _make_bot(ModelSwitchMode.CONTRASTIVE, primary, secondary)

        with pytest.raises(BudgetExhausted):
            await bot.execute_llm_call(primary, "ask", prompt="hi")

    async def test_contrastive_prefers_primary_budget_error(self):
        """When both branches raise BudgetError, the primary's is surfaced."""
        primary = _FakeClient("google", "gemini-x", error=BudgetExhausted("primary out"))
        secondary = _FakeClient("anthropic", "claude-y", error=BudgetExhausted("secondary out"))
        bot = _make_bot(ModelSwitchMode.CONTRASTIVE, primary, secondary)

        with pytest.raises(BudgetExhausted, match="primary out"):
            await bot.execute_llm_call(primary, "ask", prompt="hi")
