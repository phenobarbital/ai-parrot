# TASK-485: GroqClient.invoke() Implementation

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-481
**Assigned-to**: unassigned

---

## Context

> Implements Module 6 from the spec. Groq uses JSON mode for structured output but requires
> schema normalization via `_fix_schema_for_groq()` (drops unsupported constraints like minimum,
> maximum, pattern, format). Groq CANNOT combine JSON mode with tool calling, so a two-call
> strategy is required when both are requested.

---

## Scope

- Add `_lightweight_model = "kimi-k2-instruct"` class attribute to `GroqClient`.
- Implement `invoke()` on `GroqClient`:
  1. Call shared helpers for system prompt, structured config, model resolution.
  2. If structured output (no tools): normalize schema via `_fix_schema_for_groq()`, set JSON mode response_format.
  3. If `use_tools=True` + `output_type`: **two-call strategy**:
     - First call: tools enabled, no JSON mode → get tool results + raw text.
     - Second call: raw result as input, JSON mode + normalized schema, no tools → parse into target schema.
  4. Parse response, apply `custom_parser` if set, otherwise `_parse_structured_output()`.
  5. Build `InvokeResult` via `_build_invoke_result()`.
  6. Wrap exceptions via `_handle_invoke_error()`.
- Write unit tests with mocked Groq SDK.

**NOT in scope**: Changes to existing `ask()`. Changes to `_fix_schema_for_groq()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/groq.py` | MODIFY | Add `_lightweight_model`, implement `invoke()` |
| `tests/unit/test_groq_invoke.py` | CREATE | Unit tests with mocked SDK |

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

        needs_two_call = use_tools and config is not None

        if needs_two_call:
            # First call: tools, no JSON mode
            # Second call: JSON mode + schema, no tools
            ...
        else:
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
                fixed_schema = self._fix_schema_for_groq(schema)
                kwargs["response_format"] = {
                    "type": "json_object",
                    "schema": fixed_schema,
                }
            response = await self.client.chat.completions.create(**kwargs)
            ...
    except Exception as e:
        raise self._handle_invoke_error(e)
```

### Key Constraints
- `_fix_schema_for_groq()` must be applied to the schema before passing to Groq.
- Groq's JSON mode uses `"type": "json_object"` (not `"json_schema"` like OpenAI).
- Two-call strategy: first call gets tools+raw text, second call formats into schema.
- No retry, no streaming, no conversation history.

### References in Codebase
- `parrot/clients/groq.py:43` — class definition
- `parrot/clients/groq.py:76` — `_fix_schema_for_groq()` schema normalization
- `parrot/clients/groq.py:181` — `_prepare_groq_tools()`

---

## Acceptance Criteria

- [ ] `_lightweight_model = "kimi-k2-instruct"` set on `GroqClient`
- [ ] `invoke()` uses JSON mode with normalized schema for structured output
- [ ] Two-call strategy works when `use_tools=True` + `output_type` set
- [ ] `invoke()` works with raw string (no output_type)
- [ ] `invoke()` respects `custom_parser` when set
- [ ] No conversation history, no retry, no streaming
- [ ] All tests pass: `pytest tests/unit/test_groq_invoke.py -v`

---

## Test Specification

```python
# tests/unit/test_groq_invoke.py
import pytest
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class ClassifyResult(BaseModel):
    category: str
    score: float


class TestGroqInvoke:
    async def test_json_mode_structured(self, mock_groq_client):
        """invoke() uses JSON mode with normalized schema."""
        result = await mock_groq_client.invoke(
            "Classify this", output_type=ClassifyResult,
        )
        assert isinstance(result, InvokeResult)
        assert result.model == "kimi-k2-instruct"

    async def test_two_call_tools_plus_structured(self, mock_groq_client):
        """Two-call strategy when use_tools + output_type."""
        result = await mock_groq_client.invoke(
            "Search and classify", output_type=ClassifyResult, use_tools=True,
        )
        assert isinstance(result, InvokeResult)

    async def test_raw_string(self, mock_groq_client):
        """invoke() without output_type returns raw text."""
        result = await mock_groq_client.invoke("Summarize")
        assert isinstance(result.output, str)

    async def test_error_wrapped(self, mock_groq_client):
        """Provider errors wrapped in InvokeError."""
        with pytest.raises(InvokeError):
            await mock_groq_client.invoke("test")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-485-groq-invoke.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
