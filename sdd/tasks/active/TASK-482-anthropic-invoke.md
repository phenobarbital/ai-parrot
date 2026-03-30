# TASK-482: AnthropicClient.invoke() Implementation

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-481
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 from the spec. Anthropic/Claude does not support native JSON schema
> in response_format — structured output is achieved by injecting the schema instruction
> into the system prompt via `StructuredOutputConfig.format_schema_instruction()`.

---

## Scope

- Add `_lightweight_model = "claude-haiku-4-5-20251001"` class attribute to `AnthropicClient`.
- Implement `invoke()` on `AnthropicClient`:
  1. Call shared helpers for system prompt, structured config, model resolution.
  2. If structured output: append `config.format_schema_instruction()` to system prompt.
  3. If `use_tools=True`: prepare tools via `_prepare_tools()`.
  4. Single call to `self.client.messages.create()` — no retry, no streaming, no history.
  5. If `custom_parser` set on config: apply it to raw text. Otherwise parse via `_parse_structured_output()`.
  6. Build `InvokeResult` via `_build_invoke_result()`.
  7. Wrap exceptions via `_handle_invoke_error()`.
- Write unit tests with mocked Anthropic SDK.

**NOT in scope**: Changes to existing `ask()` method. Other client implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/claude.py` | MODIFY | Add `_lightweight_model`, implement `invoke()` |
| `tests/unit/test_anthropic_invoke.py` | CREATE | Unit tests with mocked SDK |

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

        # Claude: inject schema into system prompt
        if config:
            resolved_prompt += "\n\n" + config.format_schema_instruction()

        messages = [{"role": "user", "content": prompt}]

        # Prepare tools if requested
        tool_defs = None
        if use_tools:
            tool_defs = await self._prepare_tools()
            # ... also register any tools passed via `tools` param

        kwargs = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": resolved_prompt,
            "messages": messages,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        response = await self.client.messages.create(**kwargs)

        # Extract text from response content blocks
        raw_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                raw_text += block.text

        # Parse structured output
        output = raw_text
        if config:
            if config.custom_parser:
                output = config.custom_parser(raw_text)
            else:
                output = await self._parse_structured_output(raw_text, config)

        usage = CompletionUsage.from_claude(response.usage.__dict__)
        return self._build_invoke_result(output, output_type, resolved_model, usage, response)
    except Exception as e:
        raise self._handle_invoke_error(e)
```

### Key Constraints
- No retry — single `client.messages.create()` call.
- No `_prepare_conversation_context()` or `_update_conversation_memory()`.
- No prompt builder / `define_prompt()`.
- Tool calling: if enabled and the response has `stop_reason == "tool_use"`, execute tools and re-call (same as `ask()` tool loop but simpler — no history updates).

### References in Codebase
- `parrot/clients/claude.py:78` — `ask()` method (pattern reference, but invoke is simpler)
- `parrot/clients/claude.py:44` — existing model defaults
- `parrot/models/outputs.py:171` — `format_schema_instruction()`

---

## Acceptance Criteria

- [ ] `_lightweight_model = "claude-haiku-4-5-20251001"` set on `AnthropicClient`
- [ ] `invoke()` works with structured output (schema injected into system prompt)
- [ ] `invoke()` works with raw string (no output_type)
- [ ] `invoke()` respects `use_tools=False` by default
- [ ] `invoke()` respects `custom_parser` when set
- [ ] No conversation history read/write
- [ ] No retry logic
- [ ] All tests pass: `pytest tests/unit/test_anthropic_invoke.py -v`

---

## Test Specification

```python
# tests/unit/test_anthropic_invoke.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class PersonInfo(BaseModel):
    name: str
    age: int


class TestAnthropicInvoke:
    async def test_structured_output(self, mock_claude_client):
        """invoke() with output_type injects schema and parses response."""
        result = await mock_claude_client.invoke(
            "Extract: John is 30",
            output_type=PersonInfo,
        )
        assert isinstance(result, InvokeResult)
        assert result.model == "claude-haiku-4-5-20251001"

    async def test_raw_string(self, mock_claude_client):
        """invoke() without output_type returns raw text."""
        result = await mock_claude_client.invoke("Hello")
        assert isinstance(result.output, str)

    async def test_custom_system_prompt(self, mock_claude_client):
        """Custom system_prompt used instead of BASIC_SYSTEM_PROMPT."""
        result = await mock_claude_client.invoke(
            "test", system_prompt="Custom instructions"
        )
        assert isinstance(result, InvokeResult)

    async def test_error_wrapped(self, mock_claude_client):
        """Provider errors wrapped in InvokeError."""
        mock_claude_client.client.messages.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_claude_client.invoke("test")
        assert exc_info.value.original is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-482-anthropic-invoke.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
