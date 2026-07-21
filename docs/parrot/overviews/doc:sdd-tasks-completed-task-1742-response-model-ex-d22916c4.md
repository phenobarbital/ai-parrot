---
type: Wiki Overview
title: 'TASK-1742: Response Model Extensions for Bedrock'
id: doc:sdd-tasks-completed-task-1742-response-model-extensions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is a leaf dependency that all subsequent Bedrock client tasks depend
  on. It adds the factory methods needed to construct ai-parrot's unified response
  models from Bedrock Converse API response shapes. Without these, the `BedrockConverseClient`
  cannot return proper `AIMessage`
relates_to:
- concept: mod:parrot.models.basic
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1742: Response Model Extensions for Bedrock

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is a leaf dependency that all subsequent Bedrock client tasks depend on. It adds the factory methods needed to construct ai-parrot's unified response models from Bedrock Converse API response shapes. Without these, the `BedrockConverseClient` cannot return proper `AIMessage` or `CompletionUsage` objects.

Implements Spec Module 1.

---

## Scope

- Add `CompletionUsage.from_bedrock(usage: Dict[str, Any])` classmethod to `parrot/models/basic.py`
  - Maps `inputTokens` / `outputTokens` (camelCase) to `prompt_tokens` / `completion_tokens`
  - Stores `cacheReadInputTokens` / `cacheWriteInputTokens` in `extra_usage`
- Add `AIMessageFactory.from_bedrock(response, input_text, model, ...)` static method to `parrot/models/responses.py`
  - Extracts text from `response["output"]["message"]["content"]` blocks where `"text"` key exists
  - Maps `response["stopReason"]` to `stop_reason` / `finish_reason`
  - Converts `toolUse` content blocks to `ToolCall` objects
  - Sets `provider="bedrock-converse"`
- Write unit tests

**NOT in scope**: BedrockConverseClient itself, tool schema adaptation, model ID translation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/basic.py` | MODIFY | Add `CompletionUsage.from_bedrock()` classmethod |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Add `AIMessageFactory.from_bedrock()` static method |
| `tests/models/test_bedrock_usage.py` | CREATE | Unit tests for both factory methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage, ToolCall  # verified: parrot/models/basic.py:48, 23
from parrot.models.responses import AIMessage, AIMessageFactory  # verified: parrot/models/responses.py:72, 389
```

### Existing Signatures to Use
```python
# parrot/models/basic.py:48
class CompletionUsage(BaseModel):
    prompt_tokens: int = Field(0, validation_alias=AliasChoices("prompt_tokens", "input_tokens"))  # line 70
    completion_tokens: int = Field(0, validation_alias=AliasChoices("completion_tokens", "output_tokens"))  # line 73
    total_tokens: int = 0  # line 76
    extra_usage: Dict[str, Any] = Field(default_factory=dict)  # line 88
    @classmethod def from_claude(cls, usage: Dict[str, Any]) -> "CompletionUsage":  # line 131
    @classmethod def from_openai(cls, usage: Any) -> "CompletionUsage":  # line 109

# parrot/models/basic.py:23
class ToolCall(BaseModel):
    id: str; name: str; arguments: Dict[str, Any]
    result: Optional[Any] = None; error: Optional[str] = None

# parrot/models/responses.py:389
class AIMessageFactory:
    @staticmethod def from_claude(response: Dict, input_text: str, model: str, ...) -> AIMessage:  # line 573
    # Pattern to follow for from_bedrock():
    #   Extract text from content blocks, build CompletionUsage, set provider, return AIMessage

# parrot/models/responses.py:72
class AIMessage(BaseModel):
    input: str; output: Any; response: Optional[str]
    model: str; provider: str; usage: CompletionUsage
    stop_reason: Optional[str]; finish_reason: Optional[str]
    tool_calls: List[ToolCall] = []; structured_output: Optional[Any]
    is_structured: bool = False; raw_response: Optional[Dict]
```

### Does NOT Exist
- ~~`CompletionUsage.from_bedrock()`~~ — does not exist yet; this task creates it
- ~~`AIMessageFactory.from_bedrock()`~~ — does not exist yet; this task creates it
- ~~`AIMessage.reasoning_content`~~ — not a field; reasoning blocks are in `raw_response`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow from_claude() at responses.py:573 exactly:
@staticmethod
def from_bedrock(
    response: Dict[str, Any],
    input_text: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None,
    tool_calls: List[ToolCall] = None
) -> AIMessage:
    content = ""
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            content += block["text"]
    return AIMessage(
        input=input_text,
        output=structured_output or content,
        is_structured=structured_output is not None,
        structured_output=structured_output,
        model=model,
        provider="bedrock-converse",
        usage=CompletionUsage.from_bedrock(response.get("usage", {})),
        stop_reason=response.get("stopReason"),
        finish_reason=response.get("stopReason"),
        tool_calls=tool_calls or [],
        user_id=user_id, session_id=session_id, turn_id=turn_id,
        raw_response=response,
        response=content if isinstance(content, str) else str(content)
    )
```

### Key Constraints
- Follow the exact same signature pattern as `from_claude()`
- Bedrock Converse uses camelCase: `inputTokens`, `outputTokens`, `stopReason`, `toolUse`, `toolUseId`
- `extra_usage` should store cache-related token fields for observability

---

## Acceptance Criteria

- [ ] `CompletionUsage.from_bedrock({"inputTokens": 100, "outputTokens": 50})` returns correct `prompt_tokens=100, completion_tokens=50, total_tokens=150`
- [ ] `CompletionUsage.from_bedrock()` stores `cacheReadInputTokens`/`cacheWriteInputTokens` in `extra_usage`
- [ ] `AIMessageFactory.from_bedrock()` extracts text from nested `output.message.content` blocks
- [ ] `AIMessageFactory.from_bedrock()` maps `stopReason` to `stop_reason` and `finish_reason`
- [ ] `AIMessageFactory.from_bedrock()` converts `toolUse` blocks to `ToolCall` objects
- [ ] `AIMessageFactory.from_bedrock()` sets `provider="bedrock-converse"`
- [ ] All tests pass: `pytest tests/models/test_bedrock_usage.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/`

---

## Test Specification

```python
# tests/models/test_bedrock_usage.py
import pytest
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessageFactory


class TestCompletionUsageFromBedrock:
    def test_basic_usage(self):
        usage = CompletionUsage.from_bedrock({"inputTokens": 100, "outputTokens": 50})
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_cache_tokens(self):
        usage = CompletionUsage.from_bedrock({
            "inputTokens": 200, "outputTokens": 100,
            "cacheReadInputTokens": 150, "cacheWriteInputTokens": 50
        })
        assert usage.extra_usage["cacheReadInputTokens"] == 150
        assert usage.extra_usage["cacheWriteInputTokens"] == 50

    def test_empty_usage(self):
        usage = CompletionUsage.from_bedrock({})
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0


class TestAIMessageFactoryFromBedrock:
    def test_text_response(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hello!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        msg = AIMessageFactory.from_bedrock(response, "Hi", "claude-sonnet-4-5")
        assert msg.output == "Hello!"
        assert msg.provider == "bedrock-converse"
        assert msg.stop_reason == "end_turn"

    def test_tool_use_response(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "NYC"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        tool_calls = [ToolCall(id="tu_1", name="get_weather", arguments={"city": "NYC"})]
        msg = AIMessageFactory.from_bedrock(response, "Weather?", "claude-sonnet-4-5", tool_calls=tool_calls)
        assert msg.stop_reason == "tool_use"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "get_weather"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/bedrock-client-llm.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `CompletionUsage.from_claude()` (basic.py:131) and `AIMessageFactory.from_claude()` (responses.py:573) still exist with the listed signatures
4. **Implement** `from_bedrock()` methods following the `from_claude()` pattern exactly
5. **Run tests** and verify all acceptance criteria

---

## Completion Note

Implemented `CompletionUsage.from_bedrock()` (basic.py, following `from_claude()`
pattern) and `AIMessageFactory.from_bedrock()` (responses.py, following the
spec's exact reference implementation). Extended `from_bedrock()` beyond the
spec snippet to auto-extract `ToolCall` objects from `toolUse` content blocks
when no explicit `tool_calls` param is passed (per acceptance criterion
"converts toolUse blocks to ToolCall objects"), while still honoring an
explicit `tool_calls` override for parity with `from_claude()`'s signature.

Created `packages/ai-parrot/tests/models/test_bedrock_usage.py` (the task's
listed path `tests/models/test_bedrock_usage.py` was adjusted to the
package-scoped test root, matching the existing convention of sibling files
in `packages/ai-parrot/tests/models/`). Added one extra test
(`test_tool_use_response_auto_extraction`) beyond the task's scaffold to
cover the auto-extraction behavior.

All 6 tests pass (`pytest tests/models/test_bedrock_usage.py -v`). `ruff
check` clean on all 3 touched files. No regressions in
`packages/ai-parrot/tests/models/` (1 pre-existing, unrelated failure in
`test_dataset_models.py` not touched by this task).
