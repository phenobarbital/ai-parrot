# TASK-484: GoogleGenAIClient.invoke() Implementation

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-481
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 from the spec. Google GenAI uses `generation_config` with
> `response_mime_type="application/json"` and `response_schema` for structured output.
> Google does NOT support tools + structured output simultaneously, so a two-call strategy
> is needed when both are requested.

---

## Scope

- Add `_lightweight_model = "gemini-3-flash-lite"` class attribute to `GoogleGenAIClient`.
- Implement `invoke()` on `GoogleGenAIClient`:
  1. Call shared helpers for system prompt, structured config, model resolution.
  2. If structured output (no tools): set `generation_config` with `response_mime_type="application/json"` and `response_schema`.
  3. If `use_tools=True` + `output_type`: **two-call strategy**:
     - First call: tools enabled, no structured output → get tool results + raw text.
     - Second call: raw result as input, structured output enabled, no tools → parse into target schema.
  4. If tools only (no structured output): single call with tools.
  5. Parse response, apply `custom_parser` if set, otherwise `_parse_structured_output()`.
  6. Build `InvokeResult` via `_build_invoke_result()`.
  7. Wrap exceptions via `_handle_invoke_error()`.
- Write unit tests with mocked Google GenAI SDK.

**NOT in scope**: Changes to existing `ask()`. Vertex AI-specific paths.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/google/client.py` | MODIFY | Add `_lightweight_model`, implement `invoke()` |
| `tests/unit/test_google_invoke.py` | CREATE | Unit tests with mocked SDK |

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
            # First call: tools, no structured output
            # ... get raw_text with tool results
            # Second call: structured output, no tools
            # ... parse raw_text into structured output
        else:
            # Single call
            generation_config = {"max_output_tokens": max_tokens, "temperature": temperature}
            if config:
                generation_config["response_mime_type"] = "application/json"
                generation_config["response_schema"] = config.get_schema()
            # ... make SDK call
    except Exception as e:
        raise self._handle_invoke_error(e)
```

### Key Constraints
- Google requires schema type values in uppercase — use existing `_fix_tool_schema()` if needed.
- Two-call strategy must pass the complete raw result from call 1 as user content for call 2.
- No retry, no streaming, no conversation history.

### References in Codebase
- `parrot/clients/google/client.py:56` — class definition and defaults
- `parrot/clients/google/client.py:170` — `_fix_tool_schema()` for schema normalization

---

## Acceptance Criteria

- [ ] `_lightweight_model = "gemini-3-flash-lite"` set on `GoogleGenAIClient`
- [ ] `invoke()` uses `generation_config` with `response_schema` for structured output
- [ ] Two-call strategy works when `use_tools=True` + `output_type` set
- [ ] `invoke()` works with raw string (no output_type)
- [ ] `invoke()` respects `custom_parser` when set
- [ ] No conversation history, no retry, no streaming
- [ ] All tests pass: `pytest tests/unit/test_google_invoke.py -v`

---

## Test Specification

```python
# tests/unit/test_google_invoke.py
import pytest
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class ExtractedData(BaseModel):
    entities: list[str]
    count: int


class TestGoogleInvoke:
    async def test_structured_output_generation_config(self, mock_google_client):
        """invoke() uses generation_config with response_schema."""
        result = await mock_google_client.invoke(
            "Extract entities", output_type=ExtractedData,
        )
        assert isinstance(result, InvokeResult)
        assert result.model == "gemini-3-flash-lite"

    async def test_two_call_tools_plus_structured(self, mock_google_client):
        """Two-call strategy when use_tools + output_type."""
        result = await mock_google_client.invoke(
            "Search and extract", output_type=ExtractedData, use_tools=True,
        )
        assert isinstance(result, InvokeResult)

    async def test_raw_string(self, mock_google_client):
        """invoke() without output_type returns raw text."""
        result = await mock_google_client.invoke("Summarize")
        assert isinstance(result.output, str)

    async def test_error_wrapped(self, mock_google_client):
        """Provider errors wrapped in InvokeError."""
        with pytest.raises(InvokeError):
            await mock_google_client.invoke("test")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-484-google-invoke.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
