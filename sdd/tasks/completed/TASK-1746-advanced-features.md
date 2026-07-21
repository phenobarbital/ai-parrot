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

Extended `packages/ai-parrot/src/parrot/clients/bedrock.py` (same file,
TASK-1745's `BedrockConverseClient`) with:
- **Extended thinking**: `thinking_budget` param on `ask()`/`ask_stream()`
  → `additionalModelRequestFields.thinking = {"type": "enabled",
  "budget_tokens": N}`. `reasoningContent` blocks are not parsed into a new
  field (per spec — none exists); they survive verbatim in
  `AIMessage.raw_response` (already true from TASK-1745's tool-loop
  re-append logic) — verified explicitly by
  `test_reasoning_content_stored_in_raw_response`.
- **Prompt caching**: `prompt_cache` param on `ask()` → system becomes
  `[{"text": ...}, {"cachePoint": {"type": "default"}}]` +
  `additionalModelRequestFields.promptCaching`. Cache hit/miss metrics were
  already surfaced in `CompletionUsage.extra_usage` by TASK-1742's
  `from_bedrock()` — no new code needed there, only verified via
  `test_cache_usage_in_extra_usage`.
- **Structured output (schema-in-system-prompt)**: new `output_schema`
  param (raw JSON Schema dict) on `ask()`, distinct from the existing
  `structured_output`/`output_type` (Pydantic/dataclass-type-based) path
  from TASK-1745. Injects a schema instruction into the system prompt and
  parses the final response text as JSON via new helper
  `_parse_json_schema_output()` (direct parse → markdown-block extraction
  fallback → raw text fallback).
- **Guardrails**: `guardrail_id`/`guardrail_version` per-call params on
  `ask()`/`ask_stream()` (falling back to the constructor values from
  TASK-1745), added to `payload["guardrailConfig"]` when both are resolved.
  New `apply_guardrail_text(text, source="OUTPUT")` method calls Bedrock's
  standalone `apply_guardrail()` API (returns text unmodified when no
  guardrail is configured) — implements the spec's Module 4 public
  interface method that hadn't been implemented yet.
- **`_invoke_native()` fallback**: new method using `invoke_model()` with
  the Anthropic-native request/response payload (not the Converse
  envelope) for models without ARN-versioned IDs (Opus 4.8, Fable 5) — per
  spec Module 5 responsibility (present in the spec's Module breakdown for
  Module 5 even though this task's own Scope bullet list omitted it;
  implemented since the spec explicitly assigns it here and the FEAT-302
  acceptance criteria require it).

Created `packages/ai-parrot/tests/clients/test_bedrock_advanced.py` — 12
tests covering all five areas above (thinking budget sent/omitted,
reasoning preserved, cache point + cache usage, schema-based structured
output, guardrail config from constructor/per-call/absent,
`apply_guardrail_text()` with and without configuration, and
`_invoke_native()`). All 12 pass; `ruff check` clean; full
`tests/clients/` suite re-run shows only the 2 pre-existing, unrelated
`test_google_computer_use.py` failures (confirmed via `git stash` in
TASK-1745) — no regressions.

Used `git mv` for this task's active→completed move (learned from the
TASK-1742/1743/1744 bookkeeping bug fixed during TASK-1745).
