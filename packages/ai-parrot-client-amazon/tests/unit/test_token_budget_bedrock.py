"""FEAT-550 M4 — Bedrock accounting, strict qualification and finalization payload (spec §4 rows)."""

from __future__ import annotations

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
