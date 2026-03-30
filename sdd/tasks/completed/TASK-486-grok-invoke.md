# TASK-486: GrokClient.invoke() Implementation

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-481
**Assigned-to**: unassigned

---

## Context

> Implements Module 7 from the spec. Grok (xAI) supports native JSON schema in
> response_format, similar to OpenAI. Uses the xAI SDK's AsyncClient.

---

## Scope

- Add `_lightweight_model = "grok-4-1-fast-non-reasoning"` class attribute to `GrokClient`.
- Implement `invoke()` on `GrokClient`:
  1. Call shared helpers for system prompt, structured config, model resolution.
  2. If structured output: build native `json_schema` response_format (same pattern as OpenAI).
  3. If `use_tools=True`: prepare tools via `_prepare_tools_for_grok()`.
  4. Single SDK call — no retry, no streaming, no history.
  5. Parse response, apply `custom_parser` if set, otherwise `_parse_structured_output()`.
  6. Build `InvokeResult` via `_build_invoke_result()`.
  7. Wrap exceptions via `_handle_invoke_error()`.
- Write unit tests with mocked xAI SDK.

**NOT in scope**: Changes to existing `ask()`. Other client implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/grok.py` | MODIFY | Add `_lightweight_model`, implement `invoke()` |
| `tests/unit/test_grok_invoke.py` | CREATE | Unit tests with mocked SDK |

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

        if config:
            schema = config.get_schema()
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": config.output_type.__name__,
                    "schema": schema,
                    "strict": True,
                }
            }

        if use_tools:
            tool_defs = self._prepare_tools_for_grok()
            if tool_defs:
                kwargs["tools"] = tool_defs

        response = await self.client.chat.completions.create(**kwargs)
        raw_text = response.choices[0].message.content or ""

        output = raw_text
        if config:
            if config.custom_parser:
                output = config.custom_parser(raw_text)
            else:
                output = await self._parse_structured_output(raw_text, config)

        usage = CompletionUsage.from_grok(response.usage)
        return self._build_invoke_result(output, output_type, resolved_model, usage, response)
    except Exception as e:
        raise self._handle_invoke_error(e)
```

### Key Constraints
- Uses xAI SDK `AsyncClient` — same OpenAI-compatible chat completions interface.
- Native `json_schema` with `strict: True` for structured output.
- No retry, no streaming, no conversation history.

### References in Codebase
- `parrot/clients/grok.py:39` — class definition
- `parrot/clients/grok.py:119` — structured output handling in `ask()`
- `parrot/clients/grok.py:152` — `ask()` method

---

## Acceptance Criteria

- [ ] `_lightweight_model = "grok-4-1-fast-non-reasoning"` set on `GrokClient`
- [ ] `invoke()` uses native `json_schema` response_format for structured output
- [ ] `invoke()` works with raw string (no output_type)
- [ ] `invoke()` respects `use_tools=False` by default
- [ ] `invoke()` respects `custom_parser` when set
- [ ] No conversation history, no retry, no streaming
- [ ] All tests pass: `pytest tests/unit/test_grok_invoke.py -v`

---

## Test Specification

```python
# tests/unit/test_grok_invoke.py
import pytest
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class AnalysisResult(BaseModel):
    summary: str
    key_points: list[str]


class TestGrokInvoke:
    async def test_native_json_schema(self, mock_grok_client):
        """invoke() uses native json_schema response_format."""
        result = await mock_grok_client.invoke(
            "Analyze this", output_type=AnalysisResult,
        )
        assert isinstance(result, InvokeResult)
        assert result.model == "grok-4-1-fast-non-reasoning"

    async def test_raw_string(self, mock_grok_client):
        """invoke() without output_type returns raw text."""
        result = await mock_grok_client.invoke("Hello")
        assert isinstance(result.output, str)

    async def test_error_wrapped(self, mock_grok_client):
        """Provider errors wrapped in InvokeError."""
        with pytest.raises(InvokeError):
            await mock_grok_client.invoke("test")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-486-grok-invoke.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
