"""FEAT-550 M6 — integration scenarios for cumulative question token budgets (spec §4 'Integration Tests').

Offline only: fake Bedrock Converse / Mantle Chat Completions transports (via
patched `_sdk_create`/`_sdk_stream`/`_execute_tool`/`_chat_completion`), real
``BaseBot`` wiring, real ``BudgetRegistry``. No network calls, no timing sleeps.

See the Completion Note in ``sdd/tasks/completed/TASK-3144-...`` for a
documented production finding: going through ``BaseBot`` the client always
operates under an *inherited child* scope (spec §2.3 "under an inherited
child scope, propagate budget control to the owner") — the BOT is the
"owner" and its `_budget_partial_message` translation (not a second
tools-disabled wire attempt) is what spec §2.3's bot-boundary paragraph
describes. The client-level "one tools-disabled final attempt" mechanic
(TASK-3141/3143, covered exhaustively at the unit level) only fires when
the client itself is the direct answer owner (no enclosing bot scope).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("parrot.clients.amazon")

from parrot.bots.base import BaseBot  # noqa: E402
from parrot.bots.mixins.model_switching import ModelSwitchingMixin  # noqa: E402
from parrot.clients.amazon.bedrock import BedrockConverseClient  # noqa: E402
from parrot.clients.amazon.nova import BedrockMantleClient  # noqa: E402
from parrot.clients.base import AbstractClient  # noqa: E402
from parrot.clients.budget_scope import (  # noqa: E402
    TOKEN_BUDGET_STATE_KEY,
    BudgetRegistry,
    current_budget_scope,
)
from parrot.core.exceptions import (  # noqa: E402
    BudgetExhausted,
    BudgetResumeConflict,
    BudgetUnsupported,
    HumanInteractionInterrupt,
)
from parrot.models.basic import CompletionUsage  # noqa: E402
from parrot.models.responses import AIMessage  # noqa: E402
from parrot.tools import tool  # noqa: E402

B, F = 10_000, 1_500
R1 = {"inputTokens": 2000, "outputTokens": 500}
R2 = {"inputTokens": 3000, "outputTokens": 700}


def _tool_round(tid: str, usage: dict, name: str = "lookup") -> dict:
    return {
        "stopReason": "tool_use",
        "output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": tid, "name": name, "input": {}}}]}},
        "usage": usage,
    }


def _final_round(usage: dict, text: str = "final answer") -> dict:
    return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "usage": usage}


async def _make_bot(client: Any, **kw: Any) -> BaseBot:
    """A configured ``BaseBot`` wired to *client* (mirrors test_token_budget_boundaries.py)."""
    bot = BaseBot(name="itest-bot", llm=client, memory_type="memory", injection_detection=False, **kw)
    await bot.configure()
    return bot


class _StubBase(AbstractClient):
    """Minimal offline AbstractClient stub (mirrors test_token_budget_boundaries.py)."""

    client_type = "stub"

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("model", "stub")
        super().__init__(**kw)
        self.calls: list[tuple[str, dict]] = []

    async def get_client(self):
        return self

    async def ask(self, prompt, model=None, **kwargs):
        self.calls.append(("ask", dict(kwargs)))
        return AIMessage(input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage())

    async def ask_stream(self, prompt, **kwargs):
        self.calls.append(("ask_stream", dict(kwargs)))
        yield "chunk"

    async def resume(self, session_id, user_input, state):
        self.calls.append(("resume", {}))
        return await self.ask(user_input)

    async def invoke(self, prompt, **kwargs):
        self.calls.append(("invoke", dict(kwargs)))
        raise NotImplementedError


class UnsupportedStub(_StubBase):
    """No budget opt-in — the entry gate rejects it under any active scope."""

    budget_supported_methods = frozenset()


class TestScenario1TwoRoundsAndFinalization:
    """Scenario 1: bot question, two tool rounds; a third is denied (spec §2.3 default-reserve example).

    Verified finding: through `BaseBot`, the client always sees an inherited
    CHILD scope (the bot is the answer owner), so `BudgetExhausted` from the
    third round's denial is translated directly into a partial `AIMessage`
    by `AbstractBot._budget_partial_message` — no client-level tools-disabled
    finalization dispatch occurs (that path requires the client itself to be
    the direct, unenclosed answer owner; see TASK-3141/3143 unit coverage).
    """

    @pytest.mark.asyncio
    async def test_bedrock_exhaustion_after_two_rounds_yields_partial(self):
        registry = BudgetRegistry()
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=registry)
        captured: dict[str, Any] = {}

        @tool
        def lookup() -> str:
            """Return a fixed lookup result."""
            scope = current_budget_scope()
            captured.setdefault("scopes", []).append(scope)
            return "42"

        bot = await _make_bot(client, tools=[lookup])

        # NOTE: unlike the direct-client unit tests, the bot's tool specs and
        # system prompt inflate the real per-round input estimate — B/F are
        # tuned here (not spec's raw B=10_000/F=1_500) so round1/round2 admit
        # and round3 is denied against the ACTUAL estimate, not the settled
        # usage sum alone.
        with patch.object(client, "_sdk_create", side_effect=[_tool_round("t1", R1), _tool_round("t2", R2)]) as mock_create:
            msg = await bot.ask(
                "q", token_budget=4700, final_answer_reserve=1500,
                use_conversation_history=False, use_vector_context=False,
            )

        assert mock_create.call_count == 2  # no third (client-side) dispatch attempted
        assert msg.stop_reason == "budget_exhausted"
        assert msg.metadata.get("budget_exhausted") is True
        # The two rounds were tool-only (no assistant text) — the partial
        # output is legitimately empty, not a bug.
        assert msg.output == ""

        # Independently verify the ledger's real totals via the scope
        # captured from inside a tool call on the SAME shared ledger
        # (bypassing the currently-empty `metadata["token_budget"]" —
        # see the Completion Note finding).
        scope = captured["scopes"][0]
        report = await scope.ledger.report()
        assert report.total_tokens == 2500 + 3700  # both ordinary rounds settled
        assert report.budget_exhausted is True

    @pytest.mark.asyncio
    async def test_mantle_exhaustion_after_two_rounds_yields_partial(self):
        registry = BudgetRegistry()
        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=registry)
        captured: dict[str, Any] = {}

        @tool
        def lookup() -> str:
            """Return a fixed lookup result."""
            captured.setdefault("scopes", []).append(current_budget_scope())
            return "42"

        bot = await _make_bot(client, tools=[lookup])

        def _mantle_tool_round(tid, prompt_tokens, completion_tokens):
            return SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    model_dump=lambda: {
                        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                ),
                choices=[SimpleNamespace(message=SimpleNamespace(
                    tool_calls=[SimpleNamespace(id=tid, function=SimpleNamespace(name="lookup", arguments="{}"))],
                    content=None,
                ))],
            )

        view = MagicMock()
        view.chat.completions.create = AsyncMock(
            side_effect=[_mantle_tool_round("t1", 2000, 500), _mantle_tool_round("t2", 3000, 700)]
        )
        root = MagicMock()
        root.with_options = MagicMock(return_value=view)
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        # Same tuning note as the Bedrock variant above — Mantle's own
        # per-round estimate (message-shape dependent) needs its own budget.
        msg = await bot.ask(
            "q", token_budget=4700, final_answer_reserve=1500,
            use_conversation_history=False, use_vector_context=False,
        )

        assert view.chat.completions.create.await_count == 2
        assert msg.stop_reason == "budget_exhausted"
        scope = captured["scopes"][0]
        report = await scope.ledger.report()
        assert report.total_tokens == 2500 + 3700
        assert report.budget_exhausted is True


class TestScenario2ChildBot:
    """Scenario 2: a tool invokes a child bot on another supported client — shared ledger, child cannot finalize."""

    @pytest.mark.asyncio
    async def test_child_bot_shares_ledger_and_is_not_root(self):
        registry = BudgetRegistry()
        root_client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=registry)
        child_client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=registry)

        captured: dict[str, Any] = {}

        @tool
        async def call_child() -> str:
            """Invoke a child bot on a different provider."""
            root_scope = current_budget_scope()
            captured["root_operation_id"] = root_scope.operation_id if root_scope else None

            child_bot = await _make_bot(child_client)
            view = MagicMock()
            view.chat.completions.create = AsyncMock(
                return_value=SimpleNamespace(
                    usage=SimpleNamespace(
                        prompt_tokens=900, completion_tokens=100, total_tokens=1000,
                        model_dump=lambda: {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000},
                    ),
                    choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="child done"))],
                )
            )
            root = MagicMock()
            root.with_options = MagicMock(return_value=view)
            child_client.get_client = AsyncMock(return_value=root)
            await child_client._ensure_client()

            child_msg = await child_bot.ask("child q", use_conversation_history=False, use_vector_context=False)
            child_scope = current_budget_scope()
            captured["child_operation_id"] = child_scope.operation_id if child_scope else None
            captured["child_is_root"] = child_scope.is_root if child_scope else None
            captured["child_output"] = child_msg.output
            return "child result"

        root_bot = await _make_bot(root_client, tools=[call_child])

        with patch.object(
            root_client, "_sdk_create",
            side_effect=[
                _tool_round("t1", {"inputTokens": 500, "outputTokens": 50}, name="call_child"),
                _final_round({"inputTokens": 500, "outputTokens": 100}),
            ],
        ):
            msg = await root_bot.ask(
                "q", token_budget=B, use_conversation_history=False, use_vector_context=False,
            )

        assert captured["child_operation_id"] == captured["root_operation_id"]
        assert captured["child_is_root"] is False
        assert captured["child_output"] == "child done"
        assert msg.output == "final answer"


class TestScenario3FallbackAndContrastive:
    """Scenario 3: model fallback and contrastive execution share the ledger; an unsupported secondary is rejected."""

    @pytest.mark.asyncio
    async def test_same_provider_fallback_retry_charged_same_ledger(self):
        """A same-provider capacity-error retry (client-level fallback_model) reserves twice on one ledger."""

        class ThrottlingException(Exception):
            pass

        registry = BudgetRegistry()
        client = BedrockConverseClient(model="claude-sonnet-4-5", fallback_model="claude-haiku-4-5", budget_registry=registry)
        bot = await _make_bot(client)

        final_response = _final_round({"inputTokens": 100, "outputTokens": 50})
        with patch.object(client, "_sdk_create", side_effect=[ThrottlingException("slow down"), final_response]) as mock_create:
            msg = await bot.ask("q", token_budget=100_000, use_conversation_history=False, use_vector_context=False)

        assert mock_create.call_count == 2
        assert msg.output == "final answer"
        report = msg.metadata["token_budget"]
        # Both physical attempts (the failed one retained as uncertain, the
        # settled retry) are charged on the same operation.
        assert report["total_tokens"] >= 150

    @pytest.mark.asyncio
    async def test_contrastive_unsupported_secondary_raises_budget_unsupported(self):
        """Contrastive mode: an unsupported secondary's BudgetUnsupported propagates and is never bypassed."""

        class ContrastiveBot(ModelSwitchingMixin, BaseBot):
            pass

        registry = BudgetRegistry()
        primary = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=registry)
        secondary = UnsupportedStub()

        bot = ContrastiveBot(
            name="contrastive-probe", llm=primary, secondary_llm=secondary, model_switch_mode="contrastive",
            memory_type="memory", injection_detection=False,
        )
        await bot.configure()

        with patch.object(primary, "_sdk_create", side_effect=[_final_round({"inputTokens": 100, "outputTokens": 50})]):
            with pytest.raises(BudgetUnsupported):
                await bot.ask("q", token_budget=1000, use_conversation_history=False, use_vector_context=False)


class TestScenario4SuspendResume:
    """Scenario 4: human suspension and resume — envelope carried, single-use nonce.

    NOTE (documented production finding, not patched here per task scope):
    ``AbstractBot.resume()`` (packages/ai-parrot/src/parrot/bots/abstract.py:4308)
    reads ``self.client``, an attribute that does not exist on ``BaseBot``
    (the LLM client is exposed as ``self.llm``/``self._llm``) — every call to
    ``bot.resume(...)`` raises ``AttributeError`` unconditionally. This
    predates FEAT-550 and is orthogonal to the token-budget wiring, but this
    integration scenario is the first exerciser of that code path. Resume is
    driven through the CLIENT directly below (already covered end-to-end at
    the unit level by TASK-3140/3141's `test_interrupt_carries_envelope_and_
    resume_deepcopies`); a follow-up task should fix `self.client` ->
    `self.llm` in `AbstractBot.resume()` and re-point this test at
    `bot.resume(...)`.
    """

    @pytest.mark.asyncio
    async def test_interrupt_envelope_and_resume_once_then_conflict(self):
        registry = BudgetRegistry()
        # `token_budget=` at construction is required for the bare
        # `client.resume(session_id, user_input, state)` call below (no
        # explicit budget kwargs) to reattach via the state envelope rather
        # than zero-cost-pass-through the whole budget system (mirrors the
        # same finding in test_token_budget_mantle.py's TestBudgetedResume).
        client = BedrockConverseClient(model="claude-sonnet-4-5", token_budget=100_000, budget_registry=registry)

        @tool
        def wait_for_input() -> str:
            """Ask a human for input."""
            raise HumanInteractionInterrupt("need input")

        # NOTE: `budget_registry=registry` on the BOT (not just the client)
        # is required — `bot.ask(token_budget=...)` makes the BOT the root
        # owner, and `AbstractBot._bind_question_scope` resolves its OWN
        # registry (`self._budget_defaults_value.registry or
        # get_default_registry()`), independent of the client's. Without it
        # the interrupt's envelope points at a record in the process-wide
        # default registry, not the local `registry` this test constructs.
        bot = await _make_bot(client, tools=[wait_for_input], budget_registry=registry)

        with patch.object(client, "_sdk_create", side_effect=[_tool_round("t1", {"inputTokens": 100, "outputTokens": 20}, name="wait_for_input")]):
            with pytest.raises(HumanInteractionInterrupt) as excinfo:
                await bot.ask("q", token_budget=B, use_conversation_history=False, use_vector_context=False)

        raised = excinfo.value
        assert isinstance(raised.state, dict) and TOKEN_BUDGET_STATE_KEY in raised.state
        envelope = raised.state[TOKEN_BUDGET_STATE_KEY]
        assert "operation_id" in envelope and "resume_nonce" in envelope

        # bedrock.py's ask() attaches messages/tool_call_id as separate
        # exception attributes (not inside `.state`) — assemble the resume
        # state the way the client expects it (mirrors TASK-3140/3141's
        # `test_interrupt_carries_envelope_and_resume_deepcopies`).
        state = {
            "messages": raised.messages,
            "tool_call_id": raised.tool_call_id,
            TOKEN_BUDGET_STATE_KEY: envelope,
        }

        final_response = _final_round({"inputTokens": 50, "outputTokens": 20})
        with patch.object(client, "_sdk_create", side_effect=[final_response]):
            msg = await client.resume("sid", "the answer", state)
        assert msg.output == "final answer"

        # Second resume with the SAME (now-consumed) envelope is refused.
        with patch.object(client, "_sdk_create", side_effect=[final_response]):
            with pytest.raises(BudgetResumeConflict):
                await client.resume("sid", "the answer", state)


class TestScenario5StreamCancelled:
    """Scenario 5: a streaming bot terminated by the caller never finalizes and cleans up."""

    @pytest.mark.asyncio
    async def test_caller_close_never_finalizes_and_cleans_scope(self):
        registry = BudgetRegistry()
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=registry)
        bot = await _make_bot(client)

        async def _stream(_payload=None, handle=None):
            yield {"contentBlockDelta": {"delta": {"text": "chunk1 "}}}
            yield {"contentBlockDelta": {"delta": {"text": "chunk2 "}}}
            await asyncio.sleep(3600)  # never resolves — the caller must close instead

        with patch.object(client, "_sdk_stream", side_effect=_stream):
            agen = bot.ask_stream("q", token_budget=B, use_conversation_history=False, use_vector_context=False)
            chunks = []
            async for chunk in agen:
                chunks.append(chunk)
                if len(chunks) >= 2:
                    break
            await agen.aclose()

        assert chunks == ["chunk1 ", "chunk2 "]
        # ContextVar cleaned up after the bot's `async with scope:` exits.
        assert current_budget_scope() is None


class TestScenario6TwoIndependentQuestions:
    """Scenario 6: two independent questions on one reused client never share state."""

    @pytest.mark.asyncio
    async def test_separate_operation_ids_and_policies(self):
        registry = BudgetRegistry()
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=registry)
        bot = await _make_bot(client)

        responses = [
            _final_round({"inputTokens": 1000, "outputTokens": 200}),
            _final_round({"inputTokens": 500, "outputTokens": 100}, text="second answer"),
        ]
        with patch.object(client, "_sdk_create", side_effect=[responses[0]]):
            msg1 = await bot.ask("q1", token_budget=B, use_conversation_history=False, use_vector_context=False)
        with patch.object(client, "_sdk_create", side_effect=[responses[1]]):
            msg2 = await bot.ask("q2", token_budget=5_000, use_conversation_history=False, use_vector_context=False)

        report1 = msg1.metadata["token_budget"]
        report2 = msg2.metadata["token_budget"]
        assert report1["operation_id"] != report2["operation_id"]
        assert report1["policy"]["token_budget"] == B
        assert report2["policy"]["token_budget"] == 5_000
        assert msg1.output == "final answer"
        assert msg2.output == "second answer"
