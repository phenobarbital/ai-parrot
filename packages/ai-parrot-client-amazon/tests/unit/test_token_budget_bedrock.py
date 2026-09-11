"""FEAT-550 M4 — Bedrock accounting, strict qualification and finalization payload (spec §4 rows)."""

from __future__ import annotations

import asyncio

import pytest

from parrot.clients.amazon.budget import BedrockBudgetAdapter, FINALIZATION_INSTRUCTION, fingerprint
from parrot.clients.amazon.budget_qualifications import (
    QualificationKey,
    QualificationRecord,
    STRICT_QUALIFICATIONS,
    installed_sdk_versions,
    match_qualification,
    probe_count_tokens_support,
)
from parrot.core.exceptions import BudgetAccountingError, BudgetUnsupported
from parrot.models.basic import CompletionUsage

CACHE_USAGE = {
    "inputTokens": 100,
    "cacheReadInputTokens": 800,
    "cacheWriteInputTokens": 50,
    "outputTokens": 50,
    "totalTokens": 1000,
}


class TestBedrockAccounting:
    def test_converse_cache_fields_summed_once(self):
        u = BedrockBudgetAdapter().normalize_usage(CACHE_USAGE, route="converse")
        assert (u.input_tokens, u.output_tokens, u.total_tokens) == (950, 50, 1000)
        assert CompletionUsage.from_bedrock(CACHE_USAGE).prompt_tokens == 100  # established semantics untouched

    def test_missing_aggregate_is_unknown_not_zero(self):
        with pytest.raises(BudgetAccountingError):
            BedrockBudgetAdapter().normalize_usage({"outputTokens": 5}, route="converse")

    def test_native_body_categories(self):
        # Native Anthropic body format with cache fields
        native_usage = {
            "input_tokens": 10,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 1,
            "output_tokens": 2,
        }
        u = BedrockBudgetAdapter().normalize_usage(native_usage, route="invoke_model")
        assert (u.input_tokens, u.output_tokens) == (16, 2)

    async def test_count_is_deterministic_and_fingerprint_changes_with_payload(self):
        adapter = BedrockBudgetAdapter()

        payload1 = {
            "modelId": "anthropic.claude-3-sonnet-20240229-v1:0",
            "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
        }

        # Count the same payload twice
        estimate1 = await adapter.count_input(payload1, route="converse", mode="estimated")
        estimate2 = await adapter.count_input(payload1, route="converse", mode="estimated")

        # Same payload should give same fingerprint and token count
        assert estimate1.request_fingerprint == estimate2.request_fingerprint
        assert estimate1.input_tokens == estimate2.input_tokens

        # Method should be either "heuristic" or "tiktoken:*"
        assert estimate1.method in ("heuristic", "tiktoken:o200k_base")

        # Adding a message should change fingerprint
        payload2 = {
            "modelId": "anthropic.claude-3-sonnet-20240229-v1:0",
            "messages": [
                {"role": "user", "content": [{"text": "Hello"}]},
                {"role": "assistant", "content": [{"text": "Hi there!"}]},
            ],
        }
        estimate3 = await adapter.count_input(payload2, route="converse", mode="estimated")
        assert estimate3.request_fingerprint != estimate1.request_fingerprint


class TestStrictQualification:
    def test_registry_ships_empty_and_probe_false_on_installed_sdk(self):
        assert STRICT_QUALIFICATIONS == ()
        assert probe_count_tokens_support() is False  # botocore 1.35.36 has no CountTokens (spec §2.5)

    async def test_strict_refused_without_qualification(self):
        with pytest.raises(BudgetUnsupported):
            await BedrockBudgetAdapter().count_input({"modelId": "m", "messages": []}, route="converse", mode="strict")

    async def test_injected_exact_match_succeeds_and_any_change_denies(self):
        adapter = BedrockBudgetAdapter()

        payload = {
            "modelId": "anthropic.claude-3-sonnet-20240229-v1:0",
            "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
        }

        # Build the key via adapter._qualification_key
        key = adapter._qualification_key(payload, route="converse", endpoint="us-east-1")

        # Create a synthetic qualification record
        rec = QualificationRecord(key=key, qualification_id="q1", evidence_ref="artifacts/logs/x")

        # Should succeed with injected registry
        result = await adapter.count_input(
            payload, route="converse", mode="strict", registry=(rec,), endpoint="us-east-1"
        )
        assert result.quality == "exact"
        assert result.qualification_id == "q1"

        # Change the model ID in payload - should fail
        payload_diff_model = {**payload, "modelId": "different-model"}
        with pytest.raises(BudgetUnsupported):
            await adapter.count_input(
                payload_diff_model, route="converse", mode="strict", registry=(rec,), endpoint="us-east-1"
            )

        # Change tools flag - should fail
        payload_with_tools = {**payload, "toolConfig": {"tools": []}}
        with pytest.raises(BudgetUnsupported):
            await adapter.count_input(
                payload_with_tools, route="converse", mode="strict", registry=(rec,), endpoint="us-east-1"
            )

        # Change route - should fail
        with pytest.raises(BudgetUnsupported):
            await adapter.count_input(
                payload, route="invoke_model", mode="strict", registry=(rec,), endpoint="us-east-1"
            )

        # Change SDK versions in registry - should fail
        key_diff_sdk = QualificationKey(
            model=key.model,
            endpoint=key.endpoint,
            route=key.route,
            tools=key.tools,
            schema=key.schema,
            cache=key.cache,
            thinking=key.thinking,
            stream=key.stream,
            sdk_versions=(("botocore", "9.9.9"),),  # Different version
            count_method=key.count_method,
            output_cap_semantics=key.output_cap_semantics,
        )
        rec_diff_sdk = QualificationRecord(key=key_diff_sdk, qualification_id="q2", evidence_ref="artifacts/logs/y")

        with pytest.raises(BudgetUnsupported):
            await adapter.count_input(payload, route="converse", mode="strict", registry=(rec_diff_sdk,))


class TestFinalizationPayload:
    def test_tool_blocks_become_text_and_toolconfig_removed(self):
        adapter = BedrockBudgetAdapter()

        frame = {
            "payload": {
                "modelId": "anthropic.claude-3-sonnet-20240229-v1:0",
                "system": [{"text": "You are helpful."}],
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": "Call get_weather"}],
                    },
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "id": "call-1",
                                    "name": "get_weather",
                                    "input": {"location": "NY"},
                                }
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": "call-1",
                                    "content": [{"text": "Sunny, 72F"}],
                                }
                            }
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "id": "call-2",
                                    "name": "get_time",
                                    "input": {},
                                }
                            }
                        ],
                    },
                ],
                "toolConfig": {
                    "tools": [
                        {"toolSpec": {"name": "get_weather"}},
                        {"toolSpec": {"name": "get_time"}},
                    ]
                },
            },
            "completed_tool_calls": [
                {"id": "call-1", "name": "get_weather", "arguments": '{"location":"NY"}', "result": "Sunny, 72F"}
            ],
            "pending_tool_calls": [{"id": "call-2", "name": "get_time", "arguments": "{}", "result": None}],
            "answer_text": "The weather is sunny.",
        }

        result = adapter.prepare_finalization(frame)

        # Verify toolConfig is removed
        assert "toolConfig" not in result

        # Verify original payload is untouched
        assert "toolConfig" in frame["payload"]

        # Verify tool blocks are converted to text
        messages = result["messages"]
        content_texts = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and "text" in block:
                        content_texts.append(block["text"])

        # Check for converted tool calls
        assert any("[tool call call-1]" in t for t in content_texts)
        assert any("[tool call call-2]" in t for t in content_texts)

        # Check for completed result
        assert any("Sunny, 72F" in t for t in content_texts)

        # Check for UNEXECUTED marker
        assert any("UNEXECUTED" in t for t in content_texts)

        # Check for finalization instruction
        assert FINALIZATION_INSTRUCTION in "\n".join(content_texts)

        # No "toolUse" or "toolResult" keys should remain
        for msg in messages:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    assert "toolUse" not in block
                    assert "toolResult" not in block

    def test_totalTokens_never_readded(self):
        """totalTokens from raw provider should not be part of the normalized budget usage."""
        usage_with_inflated_total = {
            "inputTokens": 100,
            "cacheReadInputTokens": 800,
            "cacheWriteInputTokens": 50,
            "outputTokens": 50,
            "totalTokens": 99999,  # Inflated value
        }
        u = BedrockBudgetAdapter().normalize_usage(usage_with_inflated_total, route="converse")

        # Should use the computed total (950 + 50), not the inflated 99999
        assert u.total_tokens == 1000
        assert u.input_tokens == 950
        assert u.output_tokens == 50


from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from parrot.clients.amazon.bedrock import BedrockConverseClient  # noqa: E402
from parrot.clients.amazon.nova import NovaClient  # noqa: E402
from parrot.clients.budget_scope import BudgetRegistry, TOKEN_BUDGET_STATE_KEY, current_budget_scope  # noqa: E402
from parrot.core.exceptions import BudgetExhausted, HumanInteractionInterrupt  # noqa: E402
from parrot.models.token_budget import TokenBudgetPolicy  # noqa: E402


def _final(usage, text="done"):
    return {
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "usage": usage,
    }


def _tool_round(tool_use_id: str, tool_name: str = "t"):
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": tool_use_id, "name": tool_name, "input": {}}}],
            }
        },
        "usage": {"inputTokens": 50, "outputTokens": 10},
    }


class TestAttemptHooks:
    async def test_every_physical_attempt_reserved_including_fallback(self):
        """Under a budget, a capacity error + fallback retry is TWO reservations
        (first uncertain, second settled); the forwarded cap never exceeds it."""

        class ThrottlingException(Exception):
            pass

        final_response = _final({"inputTokens": 100, "outputTokens": 50})
        client = BedrockConverseClient(model="claude-sonnet-4-5", fallback_model="claude-haiku-4-5")
        registry = BudgetRegistry()
        # A generous budget: the first (failed) attempt's FULL reservation stays
        # debited as "uncertain" (spec §2.4 "an HTTP error is not proof of zero
        # charge") — the fallback retry must still fit inside what remains.
        scope = await registry.create(TokenBudgetPolicy(token_budget=100_000))

        async with scope:
            with patch.object(
                client, "_sdk_create", side_effect=[ThrottlingException("slow down"), final_response]
            ) as mock_create:
                result = await client.ask("Hello", max_tokens=500)
            assert result.output == "done"
            assert mock_create.call_count == 2
            # Both attempts' forwarded payload carries a bounded, non-default cap.
            for call in mock_create.call_args_list:
                payload = call.args[0]
                assert payload["inferenceConfig"]["maxTokens"] <= 500

        report = await scope.ledger.report()
        # First attempt (ThrottlingException) marked uncertain; second settled.
        assert report.total_tokens == 150
        assert report.uncertain_tokens > 0

    async def test_no_budget_path_touches_nothing(self):
        """No active scope -> the adapter/registry are never touched; the legacy path is untouched."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        final_response = _final({"inputTokens": 10, "outputTokens": 5})
        with patch.object(client, "_get_budget_adapter", side_effect=AssertionError("must not be called")):
            with patch.object(client, "_sdk_create", side_effect=[final_response]):
                result = await client.ask("Hello")
        assert result.output == "done"

    async def test_stream_settles_at_metadata_and_uncertain_when_missing(self):
        """Streams settle once at the metadata event; missing metadata marks uncertain."""

        async def _stream_with_metadata(_payload=None, handle=None):
            yield {"contentBlockDelta": {"delta": {"text": "hi"}}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 20, "outputTokens": 5}}}

        client = BedrockConverseClient(model="claude-sonnet-4-5")
        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))
        async with scope:
            with patch.object(client, "_sdk_stream", side_effect=_stream_with_metadata):
                chunks = [c async for c in client.ask_stream("hi")]
        assert "hi" in chunks
        report = await scope.ledger.report()
        assert report.total_tokens == 25
        assert report.uncertain_tokens == 0

        async def _stream_without_metadata(_payload=None, handle=None):
            yield {"contentBlockDelta": {"delta": {"text": "hi"}}}
            yield {"messageStop": {"stopReason": "end_turn"}}

        client2 = BedrockConverseClient(model="claude-sonnet-4-5")
        scope2 = await registry.create(TokenBudgetPolicy(token_budget=10_000))
        async with scope2:
            with patch.object(client2, "_sdk_stream", side_effect=_stream_without_metadata):
                _ = [c async for c in client2.ask_stream("hi")]
        report2 = await scope2.ledger.report()
        assert report2.total_tokens == 0
        assert report2.uncertain_tokens > 0

    async def test_budgeted_client_is_no_retry_and_shared_stays_adaptive(self):
        """The budgeted (no-retry) client uses a distinct BotoConfig from the shared client."""
        captured_configs = []

        class _FakeClientCtx:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *a):
                return False

        class _FakeSession:
            def __init__(self, *a, **kw):
                self._session = MagicMock()

            def client(self, service, **kwargs):
                captured_configs.append(kwargs["config"])
                return _FakeClientCtx()

        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch("aioboto3.Session", _FakeSession):
            shared = await client._build_client(no_retry=False)
            budgeted = await client._build_client(no_retry=True)
        assert captured_configs[0].retries["mode"] == "adaptive"
        assert captured_configs[1].retries == {"total_max_attempts": 1, "mode": "standard"}

    async def test_nova_inherits_opt_in(self):
        assert NovaClient.budget_supported_methods == BedrockConverseClient.budget_supported_methods

    async def test_interrupt_carries_envelope_and_resume_deepcopies(self):
        """A tool-raised HumanInteractionInterrupt under a budget carries the
        namespaced envelope; resume() never mutates the caller's stored messages."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        interrupt = HumanInteractionInterrupt("need human input")
        async with scope:
            with (
                patch.object(client, "_sdk_create", side_effect=[_tool_round("tu_1")]),
                patch.object(client, "_execute_tool", side_effect=interrupt),
            ):
                with pytest.raises(HumanInteractionInterrupt) as excinfo:
                    await client.ask("Hello")

        raised = excinfo.value
        assert TOKEN_BUDGET_STATE_KEY in raised.state
        assert raised.state[TOKEN_BUDGET_STATE_KEY]["operation_id"] == scope.operation_id

        # resume() must not mutate the caller's stored message list.
        original_messages = list(raised.messages)
        state = {"messages": raised.messages, "tool_call_id": raised.tool_call_id}
        final_response = _final({"inputTokens": 5, "outputTokens": 5})
        with patch.object(client, "_sdk_create", side_effect=[final_response]):
            await client.resume("session-1", "the answer", state)
        assert raised.messages == original_messages
        assert len(state["messages"]) == len(original_messages)

    async def test_native_invoke_model_guarded(self):
        """_invoke_native reserves once with route='invoke_model' and lowers body['max_tokens']."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        fake_body = {"usage": {"input_tokens": 20, "output_tokens": 10}}
        fake_response = {"body": AsyncMock()}
        fake_response["body"].read = AsyncMock(return_value=__import__("json").dumps(fake_body).encode())

        async with scope:
            budgeted_client = MagicMock()
            budgeted_client.invoke_model = AsyncMock(return_value=fake_response)
            with patch.object(client, "_get_budgeted_client", AsyncMock(return_value=budgeted_client)):
                result = await client._invoke_native([{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
        assert result == fake_body
        budgeted_client.invoke_model.assert_awaited_once()
        _, call_kwargs = budgeted_client.invoke_model.await_args
        sent_body = __import__("json").loads(call_kwargs["body"])
        assert sent_body["max_tokens"] <= 10_000
        report = await scope.ledger.report()
        assert report.total_tokens == 30


class TestFinalization:
    """TASK-3141: draining, one tools-disabled finalization, report attachment (spec §2.3)."""

    async def test_one_tools_disabled_attempt_within_a_final(self):
        """Two ordinary tool rounds admit, a third is denied, and the owner
        gets exactly ONE tools-disabled final attempt — three SDK calls total."""
        final_response = _final({"inputTokens": 30, "outputTokens": 10}, text="final answer")
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        with patch.object(client, "_execute_tool", AsyncMock(return_value="ok")):
            with patch.object(
                client,
                "_sdk_create",
                side_effect=[_tool_round("tu_1"), _tool_round("tu_2"), final_response],
            ) as mock_create:
                ai_message = await client.ask(
                    "Hello", max_tokens=600, token_budget=300, final_answer_reserve=100
                )

        assert ai_message.stop_reason == "budget_exhausted"
        assert mock_create.call_count == 3
        final_payload = mock_create.call_args_list[-1].args[0]
        assert "toolConfig" not in final_payload
        assert final_payload["inferenceConfig"]["maxTokens"] <= 600
        report = ai_message.metadata["token_budget"]
        assert report["finalized"] is True
        assert report["finalization_attempted"] is True

    async def test_zero_reserve_skips_finalization_and_propagates_partial_text(self):
        """final_answer_reserve=0 leaves nothing for the closing attempt once
        the ordinary round has consumed the whole budget — BudgetExhausted
        propagates to the caller with partial_text, no closing SDK call."""
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        with patch.object(client, "_execute_tool", AsyncMock(return_value="ok")):
            with patch.object(client, "_sdk_create", side_effect=[_tool_round("tu_1")]) as mock_create:
                with pytest.raises(BudgetExhausted) as excinfo:
                    await client.ask("Hello", max_tokens=90, token_budget=60, final_answer_reserve=0)
        assert excinfo.value.report.get("partial_text") is not None
        assert mock_create.call_count == 1

    async def test_oversized_final_input_skips_inference(self):
        """A final payload whose estimate cannot fit even the full remaining
        budget is denied without a closing SDK call (spec §2.3 table row 2)."""
        from parrot.models.token_budget import TokenEstimate

        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        real_adapter = client._get_budget_adapter()
        calls = {"n": 0}

        async def _count_input(payload, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return await real_adapter.count_input(payload, **kw)
            return TokenEstimate(
                input_tokens=100_000, method="heuristic", quality="upper_bound", request_fingerprint="oversized"
            )

        fake_adapter = MagicMock()
        fake_adapter.count_input = AsyncMock(side_effect=_count_input)
        fake_adapter.prepare_finalization = real_adapter.prepare_finalization
        fake_adapter.normalize_usage = real_adapter.normalize_usage

        with patch.object(client, "_get_budget_adapter", return_value=fake_adapter):
            with patch.object(client, "_execute_tool", AsyncMock(return_value="ok")):
                with patch.object(client, "_sdk_create", side_effect=[_tool_round("tu_1")]) as mock_create:
                    with pytest.raises(BudgetExhausted) as excinfo:
                        await client.ask(
                            "Hello", max_tokens=600, token_budget=10_000, final_answer_reserve=5_000
                        )
        assert mock_create.call_count == 1
        assert excinfo.value.report.get("partial_text") is not None

    async def test_final_tool_call_not_executed_and_no_fallback(self):
        """A final result still carrying a `toolUse` block is never executed,
        and the report reflects an incomplete answer (spec §2.3 table row 3)."""
        # The final ("tools-disabled") attempt still returns a toolUse block —
        # it must never be dispatched to _execute_tool.
        final_with_tool_use = _tool_round("should-not-run")
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        execute_tool = AsyncMock(return_value="ok")
        with patch.object(client, "_execute_tool", execute_tool):
            with patch.object(
                client, "_sdk_create",
                side_effect=[_tool_round("tu_1"), _tool_round("tu_2"), final_with_tool_use],
            ):
                ai_message = await client.ask(
                    "Hello", max_tokens=600, token_budget=300, final_answer_reserve=100
                )
        assert ai_message.stop_reason == "budget_exhausted"
        # Only the two ordinary rounds ever executed a tool.
        assert execute_tool.await_count == 2
        report = ai_message.metadata["token_budget"]
        assert report["answer_complete"] is False

    async def test_child_scope_reraises_without_finalizing(self):
        """A child (non-root) scope re-raises BudgetExhausted to its owner
        instead of attempting finalization itself (spec §2.1/§2.3)."""
        registry = BudgetRegistry()
        root_scope = await registry.create(TokenBudgetPolicy(token_budget=10, final_answer_reserve=0))
        child_scope = root_scope.child()
        assert not child_scope.is_root

        client = BedrockConverseClient(model="claude-sonnet-4-5")
        async with child_scope:
            with pytest.raises(BudgetExhausted):
                await client.ask("Hello")

        report = await root_scope.ledger.report()
        assert report.finalization_attempted is False


class TestStreamingFinalization:
    """TASK-3141: streamed finalization text in-band, exactly one sentinel."""

    async def test_finalization_chunks_in_stream_and_single_sentinel(self):
        from parrot.models.responses import AIMessage

        async def _final_stream(_payload=None, handle=None):
            yield {"contentBlockDelta": {"delta": {"text": "final chunk"}}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 30, "outputTokens": 5}}}

        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        with patch.object(client, "_sdk_stream", side_effect=_final_stream) as mock_stream:
            collected = [
                item
                async for item in client.ask_stream(
                    "Hi", max_tokens=100, token_budget=50, final_answer_reserve=40
                )
            ]

        text_chunks = [c for c in collected if isinstance(c, str)]
        messages = [c for c in collected if isinstance(c, AIMessage)]
        assert "".join(text_chunks) == "final chunk"
        assert len(messages) == 1
        assert messages[0].stop_reason == "budget_exhausted"
        assert messages[0].metadata["token_budget"]["finalized"] is True
        assert mock_stream.call_count == 1

    async def test_cancellation_never_finalizes(self):
        """asyncio.CancelledError mid-stream propagates untouched — never
        routed into finalization (spec §2.3 table row 4)."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        registry = BudgetRegistry()
        scope = await registry.create(TokenBudgetPolicy(token_budget=10_000))

        async def _cancelling_stream(_payload=None, handle=None):
            yield {"contentBlockDelta": {"delta": {"text": "partial"}}}
            raise asyncio.CancelledError()

        async with scope:
            with patch.object(client, "_sdk_stream", side_effect=_cancelling_stream) as mock_stream:
                with pytest.raises(asyncio.CancelledError):
                    async for _ in client.ask_stream("Hi"):
                        pass

        assert mock_stream.call_count == 1
        report = await scope.ledger.report()
        assert report.finalization_attempted is False
        # The unresolved reservation was marked uncertain, never silently dropped.
        assert report.uncertain_tokens > 0


class TestStructuredResult:
    """TASK-3141: budget-forced answers never reach a custom parser."""

    async def test_budget_cutoff_never_reaches_custom_parser(self):
        from pydantic import BaseModel

        from parrot.models.outputs import StructuredOutputConfig

        class _Answer(BaseModel):
            value: str = ""

        custom_parser = AsyncMock(side_effect=AssertionError("custom_parser must not run when budget-forced"))
        config = StructuredOutputConfig(output_type=_Answer, custom_parser=custom_parser)
        final_response = _final({"inputTokens": 30, "outputTokens": 10}, text="raw final text")

        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        with patch.object(client, "_execute_tool", AsyncMock(return_value="ok")):
            with patch.object(
                client,
                "_sdk_create",
                side_effect=[_tool_round("tu_1"), final_response],
            ) as mock_create:
                ai_message = await client.ask(
                    "Hello", max_tokens=600, token_budget=300, final_answer_reserve=100,
                    structured_output=config,
                )
        # One ordinary round (the schema instruction inflates the prompt
        # enough that a second is already denied) then the forced final.
        assert mock_create.call_count == 2

        custom_parser.assert_not_called()
        assert ai_message.structured_output == "raw final text"
        report = ai_message.metadata["token_budget"]
        assert report["answer_complete"] is False

    async def test_invoke_result_carries_budget_report(self):
        response = _final({"inputTokens": 20, "outputTokens": 10}, text="42")
        client = BedrockConverseClient(model="claude-sonnet-4-5", budget_registry=BudgetRegistry())
        with patch.object(client, "_sdk_create", side_effect=[response]):
            result = await client.invoke("What is 6*7?", token_budget=10_000)
        assert result.output == "42"
        assert result.budget_report is not None
        assert result.budget_report["operation_id"]
