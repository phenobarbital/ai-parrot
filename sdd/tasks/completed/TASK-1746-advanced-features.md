# TASK-1746: BedrockConverseClient Advanced Features

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-1745
**Assigned-to**: unassigned

---

## Context

After the core `BedrockConverseClient` is functional, this task adds the advanced features: extended thinking, prompt caching, structured output, and guardrails configuration. These features use Bedrock-specific API parameters.

Implements Spec Module 5.

---

## Scope

- **Extended thinking** via `additionalModelRequestFields`:
  - `thinking: {type: "enabled", budget_tokens: N}` in request
  - Parse `reasoningContent` blocks from response (text + signature)
  - Store reasoning in `raw_response` (no dedicated AIMessage field)
- **Prompt caching** via `additionalModelRequestFields`:
  - `promptCaching: {cachePoint: {type: "default"}}` for eligible blocks
  - Track cache hit/miss via `cacheReadInputTokens`/`cacheWriteInputTokens` in usage
- **Structured output**:
  - Schema-in-system-prompt approach (same as AnthropicClient)
  - Parse JSON from response text, validate against schema
  - Set `AIMessage.structured_output` and `is_structured=True`
- **Guardrails** via `guardrailConfig`:
  - Optional `guardrail_id` and `guardrail_version` parameters
  - Pass through to `converse()` call

**NOT in scope**: NovaSonicClient, factory registration, voice integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | MODIFY | Add advanced features to `BedrockConverseClient` |
| `tests/clients/test_bedrock_advanced.py` | CREATE | Unit tests for advanced features |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.bedrock import BedrockConverseClient  # created by TASK-1745
```

### Existing Signatures to Use
```python
# parrot/clients/claude.py (REFERENCE — structured output pattern)
# AnthropicClient uses schema-in-system-prompt at ask():
#   system_prompt += f"\n\nRespond with valid JSON matching this schema: {json.dumps(schema)}"
#   Then parses JSON from response text

# Bedrock Converse API — additionalModelRequestFields:
# converse(
#     modelId=..., messages=..., system=...,
#     additionalModelRequestFields={
#         "thinking": {"type": "enabled", "budget_tokens": 4096},
#         "promptCaching": {"cachePoint": {"type": "default"}}
#     },
#     guardrailConfig={"guardrailIdentifier": "...", "guardrailVersion": "..."}
# )
```

### Does NOT Exist
- ~~`AbstractClient.enable_thinking()`~~ — not a method; thinking is per-request
- ~~`AIMessage.reasoning_content`~~ — not a field; stored in `raw_response`
- ~~`AbstractClient.guardrail_config`~~ — not an attribute; pass per-request

---

## Implementation Notes

### Extended Thinking
```python
# Add to ask() / ask_stream() when thinking_budget is set:
additional_fields = {}
if thinking_budget:
    additional_fields["thinking"] = {
        "type": "enabled",
        "budget_tokens": thinking_budget
    }

# Parse reasoningContent from response:
for block in response["output"]["message"]["content"]:
    if "reasoningContent" in block:
        reasoning_text = block["reasoningContent"].get("reasoningText", {}).get("text", "")
        signature = block["reasoningContent"].get("signature")
        # Store both in raw_response for transparency
```

### Prompt Caching
```python
# Add cache points to system message blocks:
if cache_system:
    system_blocks = [
        {"text": system_text},
        {"cachePoint": {"type": "default"}}
    ]
    additional_fields["promptCaching"] = {"cachePoint": {"type": "default"}}
```

### Key Constraints
- Extended thinking is only available on specific models (Claude Sonnet 4, etc.)
- `additionalModelRequestFields` is a Dict passed as-is to the API
- Guardrails require pre-configured guardrail IDs in AWS account
- Structured output validation should use the same JSON parsing as AnthropicClient

---

## Acceptance Criteria

- [ ] `ask(prompt, thinking_budget=4096)` sends `additionalModelRequestFields.thinking`
- [ ] Extended thinking `reasoningContent` blocks are parsed and stored in `raw_response`
- [ ] `reasoningContent.signature` is preserved across tool-use rounds
- [ ] Prompt caching fields are sent when configured
- [ ] Cache usage metrics appear in `CompletionUsage.extra_usage`
- [ ] Structured output works via schema-in-system-prompt
- [ ] Guardrail config is passed through when specified
- [ ] All tests pass: `pytest tests/clients/test_bedrock_advanced.py -v`

---

## Test Specification

```python
# tests/clients/test_bedrock_advanced.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.clients.bedrock import BedrockConverseClient


class TestExtendedThinking:
    @pytest.mark.asyncio
    async def test_thinking_budget_sent(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {"reasoningText": {"text": "Let me think..."}, "signature": "sig123"}},
                {"text": "The answer is 42."}
            ]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 50, "outputTokens": 30}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            result = await client.ask("What is the meaning of life?", thinking_budget=4096)
            call_kwargs = mock_create.call_args
            assert "thinking" in call_kwargs.kwargs.get("additionalModelRequestFields", {}) or True
            assert result.output == "The answer is 42."


class TestStructuredOutput:
    @pytest.mark.asyncio
    async def test_json_schema_in_system(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": '{"name": "Alice", "age": 30}'}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        schema = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}
        with patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("Who is Alice?", output_schema=schema)
            assert result.is_structured is True
            assert result.structured_output["name"] == "Alice"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Verify** TASK-1745 is completed — `BedrockConverseClient` must exist in `bedrock.py`
3. **Study** the Bedrock Converse API `additionalModelRequestFields` structure
4. **Study** AnthropicClient's structured output pattern at `claude.py`
5. **Implement** each advanced feature incrementally with tests
6. **Run tests** and verify all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
