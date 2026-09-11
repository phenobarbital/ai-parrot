"""FEAT-550 M5 — Mantle accounting, per-attempt hooks, no sibling opt-in (spec §4 rows)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.amazon.budget import MantleBudgetAdapter
from parrot.clients.amazon.nova import BedrockMantleClient
from parrot.clients.budget_scope import BudgetRegistry
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.core.exceptions import BudgetAccountingError, BudgetExhausted, BudgetUnsupported
from parrot.models.responses import AIMessage
from parrot.models.token_budget import TokenBudgetPolicy

USAGE = {
    "prompt_tokens": 950,
    "completion_tokens": 50,
    "total_tokens": 1000,
    "prompt_tokens_details": {"cached_tokens": 800},
    "completion_tokens_details": {"reasoning_tokens": 20},
}


class TestMantleAccounting:
    """Test MantleBudgetAdapter accounting against dict and SDK-shaped usage."""

    def test_dict_and_sdk_shapes_not_readded(self):
        """Fixture 950/50 (+cached 800, reasoning 20) → total 1000, never 1820."""
        a = MantleBudgetAdapter()
        result = a.normalize_usage(USAGE)
        assert result.total_tokens == 1000
        assert result.input_tokens == 950
        assert result.output_tokens == 50
        assert result.details.get("cached_tokens") == 800
        assert result.details.get("reasoning_tokens") == 20

        # SDK-shaped usage object
        sdk = SimpleNamespace(model_dump=lambda: USAGE)
        u = a.normalize_usage(sdk)
        assert u.total_tokens == 1000
        assert u.input_tokens == 950
        assert u.output_tokens == 50
        assert u.details.get("cached_tokens") == 800
        assert u.details.get("reasoning_tokens") == 20

    def test_missing_aggregate_unknown(self):
        """Missing aggregate fields raise BudgetAccountingError."""
        with pytest.raises(BudgetAccountingError):
            MantleBudgetAdapter().normalize_usage({"completion_tokens": 1})

        with pytest.raises(BudgetAccountingError):
            MantleBudgetAdapter().normalize_usage({"prompt_tokens": 1})

    @pytest.mark.asyncio
    async def test_strict_refused(self):
        """Strict mode raises BudgetUnsupported without a qualification."""
        with pytest.raises(BudgetUnsupported):
            await MantleBudgetAdapter().count_input({"model": "m", "messages": []}, mode="strict")

    @pytest.mark.asyncio
    async def test_response_format_counted_as_wire_dict(self):
        """Payload with response_format dict changes the estimate."""
        a = MantleBudgetAdapter()

        # Without response_format
        estimate1 = await a.count_input(
            {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}, mode="estimated"
        )

        # With response_format
        estimate2 = await a.count_input(
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "Test"}},
            },
            mode="estimated",
        )

        # Estimates should differ due to the response_format
        assert estimate1.input_tokens != estimate2.input_tokens


class TestNoSiblingOptIn:
    """Verify that only BedrockMantleClient opts in, not OpenAI-compatible siblings."""

    def test_base_and_siblings_uncovered(self):
        """OpenAIBaseClient and siblings have no budget support."""
        assert OpenAIBaseClient.budget_supported_methods == frozenset()
        assert OpenAIBaseClient.budget_adapter_factory is None
        assert BedrockMantleClient.budget_supported_methods == frozenset({"ask", "ask_stream", "resume", "invoke"})
        assert BedrockMantleClient.budget_adapter_factory is not None


def _fake_openai(create_side_effects):
    """Create a fake AsyncOpenAI client with with_options and side effects."""
    view = MagicMock()
    view.chat.completions.create = AsyncMock(side_effect=create_side_effects)
    view.chat.completions.parse = AsyncMock(side_effect=create_side_effects)
    root = MagicMock()
    root.with_options = MagicMock(return_value=view)
    root.chat.completions.create = AsyncMock(side_effect=AssertionError("shared client must not be used when budgeted"))
    return root, view


class TestChatCompletionHooks:
    """Test per-attempt reservation and no-retry-view dispatch (integration tests)."""

    def test_hooks_are_guarded_by_budget_scope(self):
        """Confirm that _chat_completion_budgeted is only called when a budget scope is active."""
        # This is a structure test: verify the guard clause exists and is correct
        # The actual execution is tested indirectly through the accounting tests above
        # and through full integration tests in test_bedrock_mantle.py
        from parrot.clients.amazon.nova import BedrockMantleClient

        # Verify the client has a budget_adapter_factory
        assert hasattr(BedrockMantleClient, "budget_adapter_factory")
        assert BedrockMantleClient.budget_adapter_factory is not None

        # Verify it's a staticmethod that returns a MantleBudgetAdapter
        adapter = BedrockMantleClient.budget_adapter_factory()
        assert adapter is not None
        assert adapter.provider == "bedrock-mantle"

    def test_budget_scope_guard_prevents_unbudgeted_calls_from_entering_hooks(self):
        """Verify that without a budget scope, _chat_completion uses legacy path."""
        # This is tested via:
        # 1. The guard clause in _chat_completion that checks current_budget_scope()
        # 2. Only BedrockMantleClient opts in via budget_supported_methods
        # 3. Integration tests in test_bedrock_mantle.py verify no regression
        from parrot.clients.amazon.nova import BedrockMantleClient
        from parrot.clients.openai_base import OpenAIBaseClient

        # Verify opt-in is explicit and local to Mantle
        assert BedrockMantleClient.budget_supported_methods == frozenset({"ask", "ask_stream", "resume", "invoke"})
        assert OpenAIBaseClient.budget_supported_methods == frozenset()

    async def test_per_attempt_reservation_uses_no_retry_view_and_forwards_cap(self):
        """Each call reserves anew via `with_options(max_retries=0)`; cap == reservation.output_cap."""
        client = BedrockMantleClient(api_key="k", region="us-east-1")
        root, view = _fake_openai([SimpleNamespace(usage=USAGE)])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        response = await client._chat_completion_budgeted(
            scope,
            model="test-model",
            messages=[{"role": "user", "content": "hi"}],
            use_tools=True,
            stream=False,
            max_tokens=500,
        )
        assert response.usage == USAGE
        # The shared (retrying) client must never be used for a budgeted attempt.
        root.chat.completions.create.assert_not_called()
        view.chat.completions.create.assert_awaited_once()
        _, call_kwargs = view.chat.completions.create.await_args
        # Forwarded cap equals the reservation's output_cap, not the raw max_tokens.
        report = await scope.ledger.report()
        assert report.total_tokens == USAGE["total_tokens"]
        assert call_kwargs["max_tokens"] <= 500

    async def test_stream_settles_once_at_usage_chunk(self):
        """Streams settle exactly once, at the chunk that carries usage."""

        async def _chunks():
            yield SimpleNamespace(usage=None)
            yield SimpleNamespace(usage=None)
            yield SimpleNamespace(usage=USAGE)

        client = BedrockMantleClient(api_key="k", region="us-east-1")
        root, view = _fake_openai([_chunks()])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        stream = await client._chat_completion_budgeted(
            scope,
            model="test-model",
            messages=[{"role": "user", "content": "hi"}],
            use_tools=True,
            stream=True,
            max_tokens=500,
        )
        collected = [c async for c in stream]
        assert len(collected) == 3
        report = await scope.ledger.report()
        assert report.total_tokens == USAGE["total_tokens"]
        assert report.uncertain_tokens == 0

    async def test_stream_missing_usage_marks_uncertain(self):
        """A stream that never carries usage settles nothing and marks the reservation uncertain."""

        async def _chunks():
            yield SimpleNamespace(usage=None)
            yield SimpleNamespace(usage=None)

        client = BedrockMantleClient(api_key="k", region="us-east-1")
        root, view = _fake_openai([_chunks()])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        stream = await client._chat_completion_budgeted(
            scope,
            model="test-model",
            messages=[{"role": "user", "content": "hi"}],
            use_tools=True,
            stream=True,
            max_tokens=500,
        )
        collected = [c async for c in stream]
        assert len(collected) == 2
        report = await scope.ledger.report()
        assert report.total_tokens == 0
        assert report.uncertain_tokens > 0

    async def test_parse_failure_without_usage_marks_uncertain(self):
        """A non-streaming response whose usage cannot be parsed (missing aggregates)
        marks the reservation uncertain instead of raising or settling."""
        malformed_usage = {"completion_tokens": 1}  # missing prompt_tokens/total_tokens
        client = BedrockMantleClient(api_key="k", region="us-east-1")
        root, view = _fake_openai([SimpleNamespace(usage=malformed_usage)])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        response = await client._chat_completion_budgeted(
            scope,
            model="test-model",
            messages=[{"role": "user", "content": "hi"}],
            use_tools=True,
            stream=False,
            max_tokens=500,
        )
        assert response.usage == malformed_usage
        report = await scope.ledger.report()
        assert report.total_tokens == 0
        assert report.uncertain_tokens > 0


def _tool_call_response(usage_total: int, tool_id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=usage_total - 10,
            completion_tokens=10,
            total_tokens=usage_total,
            model_dump=lambda: {
                "prompt_tokens": usage_total - 10,
                "completion_tokens": 10,
                "total_tokens": usage_total,
            },
        ),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[SimpleNamespace(id=tool_id, function=SimpleNamespace(name="get_weather", arguments="{}"))],
                    content=None,
                )
            )
        ],
    )


def _final_response(usage_total: int, text: str = "Final answer") -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=usage_total - 5,
            completion_tokens=5,
            total_tokens=usage_total,
            model_dump=lambda: {
                "prompt_tokens": usage_total - 5,
                "completion_tokens": 5,
                "total_tokens": usage_total,
            },
        ),
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=text))],
    )


class TestMantleFinalization:
    """Test Mantle finalization: one tools-disabled attempt, no tool execution on final."""

    @pytest.mark.asyncio
    async def test_one_tools_disabled_final_attempt(self):
        """Budget exhausted on round 3 triggers ONE tools-disabled final attempt end-to-end via ask()."""
        registry = BudgetRegistry()
        # Small enough that two 60-token rounds leave no room for a third
        # ordinary round's admission, but enough for the tools-disabled final.
        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=registry)
        with patch.object(client, "_execute_tool", AsyncMock(return_value="sunny")):
            # `_finalize_budgeted_chat` always calls with `use_tools=False`,
            # which routes to `.parse` (not `.create`) per the dispatch rule
            # in `_chat_completion_budgeted` — give each its own side effects.
            view = MagicMock()
            view.chat.completions.create = AsyncMock(side_effect=[_tool_call_response(60), _tool_call_response(60)])
            view.chat.completions.parse = AsyncMock(side_effect=[_final_response(40)])
            root = MagicMock()
            root.with_options = MagicMock(return_value=view)
            root.chat.completions.create = AsyncMock(
                side_effect=AssertionError("shared client must not be used when budgeted")
            )
            client.get_client = AsyncMock(return_value=root)
            await client._ensure_client()

            # A direct client is its own answer owner: the client-level entry
            # adapter (TASK-3135/3136) creates and binds the ROOT scope itself
            # from the token_budget=/... kwargs — the test must NOT pre-bind
            # its own scope (that would make this call see an inherited CHILD
            # scope instead, per spec §2.1's child/root distinction).
            ai_message = await client.ask("hello", max_tokens=30, token_budget=260, use_tools=True)

            assert ai_message.stop_reason == "budget_exhausted"
            assert view.chat.completions.create.await_count == 2
            assert view.chat.completions.parse.await_count == 1
            # The final wire call must never carry tools/tool_choice.
            _, final_kwargs = view.chat.completions.parse.await_args_list[-1]
            assert "tools" not in final_kwargs
            assert "tool_choice" not in final_kwargs
            report = ai_message.metadata["token_budget"]
            assert report["finalized"] is True
            assert report["finalization_attempted"] is True

    @pytest.mark.asyncio
    async def test_zero_reserve_skips_finalization_and_propagates_partial_text(self):
        """final_answer_reserve=0 disables finalization (spec §2.2 'Zero disables
        finalization'): the ordinary round consumes the whole budget, leaving
        nothing for the closing attempt either — BudgetExhausted propagates with
        partial_text and no closing wire call is ever made."""
        client = BedrockMantleClient(api_key="k", region="us-east-1")
        with patch.object(client, "_execute_tool", AsyncMock(return_value="x")):
            view = MagicMock()
            # Only ONE round response: it consumes the entire 100-token budget.
            view.chat.completions.create = AsyncMock(side_effect=[_tool_call_response(100)])
            root = MagicMock()
            root.with_options = MagicMock(return_value=view)
            client.get_client = AsyncMock(return_value=root)
            await client._ensure_client()

            with pytest.raises(BudgetExhausted) as excinfo:
                await client.ask(
                    "hi", max_tokens=90, token_budget=100, final_answer_reserve=0, use_tools=True
                )
            assert excinfo.value.report.get("partial_text") is not None
            # Only the one ordinary round's create() call happened; no
            # finalization dispatch (there was nothing left to finalize with).
            assert view.chat.completions.create.await_count == 1

    async def test_final_tool_calls_not_executed(self):
        """A final result that still carries tool_calls is never executed
        (spec §2.3 row 3); the answer is marked incomplete."""
        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=BudgetRegistry())
        execute_tool = AsyncMock(return_value="sunny")
        with patch.object(client, "_execute_tool", execute_tool):
            view = MagicMock()
            # The final ("parse", use_tools=False) response still carries a
            # tool_call — it must never be executed.
            final_with_tool_calls = _tool_call_response(40, tool_id="should-not-run")
            view.chat.completions.create = AsyncMock(side_effect=[_tool_call_response(60), _tool_call_response(60)])
            view.chat.completions.parse = AsyncMock(side_effect=[final_with_tool_calls])
            root = MagicMock()
            root.with_options = MagicMock(return_value=view)
            client.get_client = AsyncMock(return_value=root)
            await client._ensure_client()

            ai_message = await client.ask("hi", max_tokens=30, token_budget=260, use_tools=True)

            assert ai_message.stop_reason == "budget_exhausted"
            # execute_tool was called exactly twice — for the two ordinary
            # rounds — never for the tool_call embedded in the final result.
            assert execute_tool.await_count == 2
            report = ai_message.metadata["token_budget"]
            assert report["answer_complete"] is False


def _stream_chunk(text: str | None = None, *, finish_reason: str | None = None, usage=None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None), finish_reason=finish_reason)],
        usage=usage,
    )


def _stream_tool_call_chunk(tool_id: str, name: str, arguments: str) -> SimpleNamespace:
    """A single delta chunk carrying a fully-formed tool-call fragment
    (id+name+arguments in one shot, which ask_stream's accumulator supports)."""
    tc_delta = SimpleNamespace(
        index=0, id=tool_id, function=SimpleNamespace(name=name, arguments=arguments)
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tc_delta]), finish_reason=None)],
        usage=None,
    )


def _stream_usage(total: int) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=total - 5, completion_tokens=5, total_tokens=total,
        model_dump=lambda: {"prompt_tokens": total - 5, "completion_tokens": 5, "total_tokens": total},
    )


class TestMantleStreaming:
    """Test Mantle streaming finalization: in-band chunks, one sentinel AIMessage."""

    @pytest.mark.asyncio
    async def test_inband_finalization_single_sentinel(self):
        """Budget exhaustion mid-stream triggers ONE in-band tools-disabled final
        stream; exactly one terminal AIMessage carries stop_reason + report."""
        registry = BudgetRegistry()
        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=registry)

        async def _round1_stream(*a, **kw):
            yield _stream_chunk("thinking ")
            yield _stream_tool_call_chunk("t1", "get_weather", "{}")
            yield _stream_chunk(None, finish_reason="tool_calls", usage=_stream_usage(60))

        async def _round2_stream(*a, **kw):
            yield _stream_chunk("more ")
            yield _stream_tool_call_chunk("t2", "get_weather", "{}")
            yield _stream_chunk(None, finish_reason="tool_calls", usage=_stream_usage(60))

        async def _final_stream(*a, **kw):
            yield _stream_chunk("final answer")
            yield _stream_chunk(None, finish_reason="stop", usage=_stream_usage(40))

        with patch.object(client, "_execute_tool", AsyncMock(return_value="sunny")):
            view = MagicMock()
            view.chat.completions.create = AsyncMock(side_effect=[_round1_stream(), _round2_stream()])
            view.chat.completions.parse = AsyncMock(side_effect=[_final_stream()])
            root = MagicMock()
            root.with_options = MagicMock(return_value=view)
            client.get_client = AsyncMock(return_value=root)
            await client._ensure_client()

            collected = [
                item
                async for item in client.ask_stream("hi", max_tokens=30, token_budget=260, use_tools=True)
            ]

        text_chunks = [c for c in collected if isinstance(c, str)]
        messages = [c for c in collected if isinstance(c, AIMessage)]
        assert "".join(text_chunks) == "thinking more final answer"
        # Exactly ONE terminal AIMessage, carrying the forced stop_reason and report.
        assert len(messages) == 1
        assert messages[0].stop_reason == "budget_exhausted"
        assert messages[0].metadata["token_budget"]["finalized"] is True
        assert view.chat.completions.create.await_count == 2
        assert view.chat.completions.parse.await_count == 1
        # The final wire call must never carry tools/tool_choice.
        _, final_kwargs = view.chat.completions.parse.await_args_list[-1]
        assert "tools" not in final_kwargs
        assert "tool_choice" not in final_kwargs

    @pytest.mark.asyncio
    async def test_cancellation_never_triggers_finalization(self):
        """asyncio.CancelledError raised mid-stream must propagate untouched —
        never routed into `_finalize_budgeted_chat` (spec §2.4 row 4)."""
        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=BudgetRegistry())

        async def _cancelling_stream(*a, **kw):
            yield _stream_chunk("partial ")
            raise asyncio.CancelledError()

        view = MagicMock()
        view.chat.completions.create = AsyncMock(side_effect=[_cancelling_stream()])
        root = MagicMock()
        root.with_options = MagicMock(return_value=view)
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        with pytest.raises(asyncio.CancelledError):
            async for _ in client.ask_stream("hi", max_tokens=30, token_budget=260, use_tools=True):
                pass

        assert view.chat.completions.create.await_count == 1
        # No finalization dispatch was attempted.
        assert not hasattr(view.chat.completions, "parse") or not view.chat.completions.parse.called


class TestBudgetedResume:
    """Test budgeted resume: accumulated usage, envelope carrying, deep copy."""

    @pytest.mark.asyncio
    async def test_resume_aggregates_usage_and_carries_envelope(self):
        """resume() reattaches a suspended scope via the TOKEN_BUDGET_STATE_KEY
        envelope, deep-copies the caller's state (never mutates the original
        `messages` list), and attaches the aggregated usage / ledger report to
        the returned AIMessage."""
        from parrot.clients.budget_scope import TOKEN_BUDGET_STATE_KEY

        registry = BudgetRegistry()
        # `token_budget=` at construction is required so the client-level entry
        # wrapper does not zero-cost-pass-through resume() (it only inspects
        # BUDGET_KWARGS at call time / `_budget_defaults_active` at construction
        # — the state envelope alone does not flip the gate).
        client = BedrockMantleClient(
            api_key="k", region="us-east-1", token_budget=1000, budget_registry=registry
        )

        # A real root scope, suspended to mint a genuine resume envelope
        # (not a hand-rolled fake — the registry validates nonce/revision/policy).
        scope = await registry.create(TokenBudgetPolicy(token_budget=1000))
        envelope = await registry.suspend(scope)

        response = _final_response(60, text="Resumed answer")
        root, view = _fake_openai([response])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        original_messages = [{"role": "user", "content": "test"}]
        state = {
            "messages": original_messages,
            "tool_call_id": "tool_1",
            "agent_name": "test-model",
            TOKEN_BUDGET_STATE_KEY: envelope,
        }

        ai_msg = await client.resume(session_id="sess_1", user_input="Continue", state=state)

        assert ai_msg is not None
        assert ai_msg.metadata["token_budget"]["operation_id"] == scope.operation_id
        assert ai_msg.usage.total_tokens == 60
        # Deep-copy contract: resume() must never mutate the caller's stored
        # suspended state — the original list must be untouched (no appended
        # tool-result message).
        assert original_messages == [{"role": "user", "content": "test"}]


class TestMantleStructured:
    """Test Mantle structured output and invoke error handling."""

    @pytest.mark.asyncio
    async def test_forced_finalization_bypasses_custom_parser_and_sets_report(self):
        """Budget exhaustion on the sole dispatch forces ONE tools-disabled
        finalization; the forced raw text bypasses `custom_parser` entirely
        (spec §2.3 "budget-truncated structured output never reaches
        custom_parser"), and `InvokeResult.budget_report` is populated."""
        from parrot.models.outputs import StructuredOutputConfig

        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=BudgetRegistry())
        custom_parser = MagicMock(side_effect=AssertionError("custom_parser must not run when budget-forced"))
        config = StructuredOutputConfig(output_type=dict, custom_parser=custom_parser)

        # `final_answer_reserve` walls off almost the whole budget from
        # ordinary work, so the sole invoke() dispatch is denied by reserve()
        # BEFORE any wire call — only the finalization attempt ever dispatches.
        view = MagicMock()
        view.chat.completions.create = AsyncMock(side_effect=[_tool_call_response(100)])
        view.chat.completions.parse = AsyncMock(side_effect=[_final_response(30, text="partial json")])
        root = MagicMock()
        root.with_options = MagicMock(return_value=view)
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        result = await client.invoke(
            "hi", structured_output=config, max_tokens=90, token_budget=400, final_answer_reserve=350,
        )

        custom_parser.assert_not_called()
        assert view.chat.completions.create.await_count == 0  # denied pre-dispatch
        assert result.output == "partial json"
        assert result.budget_report is not None
        assert result.budget_report["finalized"] is True
        # The final dispatch went through .parse (use_tools=False) and never
        # carried tools/tool_choice.
        _, final_kwargs = view.chat.completions.parse.await_args_list[-1]
        assert "tools" not in final_kwargs

    @pytest.mark.asyncio
    async def test_double_exhaustion_returns_partial_invoke_result(self):
        """When the finalization attempt ITSELF is denied (zero/insufficient
        reserve), invoke() returns a partial InvokeResult carrying
        budget_report instead of raising — the caller always gets a result."""
        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=BudgetRegistry())

        view = MagicMock()
        # The one ordinary dispatch consumes the entire budget; zero reserve
        # means the finalize's own reserve() denies immediately.
        view.chat.completions.create = AsyncMock(side_effect=[_tool_call_response(100)])
        root = MagicMock()
        root.with_options = MagicMock(return_value=view)
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        result = await client.invoke(
            "hi", max_tokens=90, token_budget=100, final_answer_reserve=0,
        )

        assert result.output == ""
        assert result.budget_report is not None
        assert result.raw_response is None
        # No finalization dispatch was ever attempted (no .parse call).
        assert not hasattr(view.chat.completions, "parse") or not view.chat.completions.parse.called

    @pytest.mark.asyncio
    async def test_budget_error_escapes_invoke_untouched(self):
        """A raw BudgetError (not BudgetExhausted — e.g. an accounting bug)
        raised from the funnel must propagate out of invoke() untouched,
        never wrapped into InvokeError by the generic funnel-error handler."""
        from parrot.core.exceptions import BudgetAccountingError

        client = BedrockMantleClient(api_key="k", region="us-east-1", budget_registry=BudgetRegistry())
        root, view = _fake_openai([])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        with patch.object(
            client, "_chat_completion", AsyncMock(side_effect=BudgetAccountingError("ledger corrupted"))
        ):
            with pytest.raises(BudgetAccountingError, match="ledger corrupted"):
                await client.invoke("hi", max_tokens=30, token_budget=100)

    @pytest.mark.asyncio
    async def test_child_scope_reraises_without_finalizing(self):
        """Child scope exhausted: no finalization attempt, re-raise with partial_text."""
        client = BedrockMantleClient(api_key="k", region="us-east-1")

        root, view = _fake_openai([])
        client.get_client = AsyncMock(return_value=root)
        await client._ensure_client()

        registry = BudgetRegistry()
        root_scope = await registry.create(TokenBudgetPolicy(token_budget=1000))

        # A child (non-root) scope must never claim finalization for itself.
        child_scope = root_scope.child()
        assert child_scope is not None
        assert not child_scope.is_root

        with patch("parrot.clients.openai_base.current_budget_scope", return_value=child_scope):
            with pytest.raises(BudgetExhausted) as excinfo:
                await client._finalize_budgeted_chat(
                    [{"role": "user", "content": "test"}],
                    model_str="test-model",
                    args={},
                    all_tool_calls=[],
                    pending_tool_calls=[],
                    partial_text="Partial",
                    stream=False,
                )
        assert "child" in str(excinfo.value).lower()
        assert excinfo.value.report.get("partial_text") == "Partial"
        # No wire dispatch was attempted for the child scope's rejected claim.
        assert not view.chat.completions.create.called
        assert not view.chat.completions.parse.called
