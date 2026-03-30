# TASK-483: OpenAIClient.invoke() Implementation

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-481
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 from the spec. OpenAI supports native structured output via
> `response_format` with `json_schema` type and `strict: True`. This gives the strongest
> schema enforcement of all providers.

---

## Scope

- Add `_lightweight_model = "gpt-4.1"` class attribute to `OpenAIClient`.
- Implement `invoke()` on `OpenAIClient`:
  1. Call shared helpers for system prompt, structured config, model resolution.
  2. If structured output: build `response_format` with native `json_schema` using `_build_response_format_from()`.
  3. If `use_tools=True`: prepare tools via `_prepare_tools()`.
  4. Single call to `self.client.chat.completions.create()` or `.parse()` — no retry, no streaming, no history.
  5. If `custom_parser` set: apply to raw text. Otherwise use SDK-parsed response or `_parse_structured_output()`.
  6. Build `InvokeResult` via `_build_invoke_result()`.
  7. Wrap exceptions via `_handle_invoke_error()`.
- Write unit tests with mocked OpenAI SDK.

**NOT in scope**: Responses API routing (o3/o4 models). Changes to existing `ask()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/gpt.py` | MODIFY | Add `_lightweight_model`, implement `invoke()` |
| `tests/unit/test_openai_invoke.py` | CREATE | Unit tests with mocked SDK |

---

## Implementation Notes

### Pattern to Follow
```python
async def invoke(self, prompt, *, output_type=None, structured_output=None,
                 model=None, system_prompt=None, max_tokens=4096,
                 temperature=0.0, use_tools=False, tools=None) -> InvokeResult:
    try:
        resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)
        config = self._build_invoke_structured_config(output_type, structured_output)
        resolved_model = self._resolve_invoke_model(model)

        messages = [
            {"role": "system", "content": resolved_prompt},
            {"role": "user", "content": prompt},
        ]

        kwargs = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        # Native JSON schema structured output
        if config:
            response_format = self._build_response_format_from(config)
            if response_format:
                kwargs["response_format"] = response_format

        # Tools
        if use_tools:
            tool_defs = await self._prepare_tools()
            if tool_defs:
                kwargs["tools"] = tool_defs

        response = await self.client.chat.completions.create(**kwargs)
        raw_text = response.choices[0].message.content or ""

        # Parse output
        output = raw_text
        if config:
            if config.custom_parser:
                output = config.custom_parser(raw_text)
            else:
                output = await self._parse_structured_output(raw_text, config)

        usage = CompletionUsage.from_openai(response.usage)
        return self._build_invoke_result(output, output_type, resolved_model, usage, response)
    except Exception as e:
        raise self._handle_invoke_error(e)
```

### Key Constraints
- Use `_build_response_format_from()` (existing method) for structured output format.
- No tenacity retry wrapping — direct SDK call.
- No `_prepare_conversation_context()` or `_update_conversation_memory()`.

### References in Codebase
- `parrot/clients/gpt.py:592` — `ask()` method (pattern reference)
- `parrot/clients/gpt.py:221` — `_chat_completion()` with retry (invoke skips retry)
- `parrot/clients/gpt.py:743` — structured output handling

---

## Acceptance Criteria

- [ ] `_lightweight_model = "gpt-4.1"` set on `OpenAIClient`
- [ ] `invoke()` uses native `response_format` with `json_schema` for structured output
- [ ] `invoke()` works with raw string (no output_type)
- [ ] `invoke()` respects `use_tools=False` by default
- [ ] `invoke()` respects `custom_parser` when set
- [ ] No conversation history, no retry, no streaming
- [ ] All tests pass: `pytest tests/unit/test_openai_invoke.py -v`

---

## Test Specification

```python
# tests/unit/test_openai_invoke.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class SentimentResult(BaseModel):
    sentiment: str
    confidence: float


class TestOpenAIInvoke:
    async def test_native_json_schema(self, mock_openai_client):
        """invoke() uses response_format with json_schema."""
        result = await mock_openai_client.invoke(
            "Classify sentiment", output_type=SentimentResult,
        )
        assert isinstance(result, InvokeResult)
        assert result.model == "gpt-4.1"

    async def test_raw_string(self, mock_openai_client):
        """invoke() without output_type returns raw text."""
        result = await mock_openai_client.invoke("Summarize this")
        assert isinstance(result.output, str)

    async def test_error_wrapped(self, mock_openai_client):
        """Provider errors wrapped in InvokeError."""
        with pytest.raises(InvokeError):
            await mock_openai_client.invoke("test")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-483-openai-invoke.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
