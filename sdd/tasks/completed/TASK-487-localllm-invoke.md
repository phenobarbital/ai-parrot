# TASK-487: LocalLLMClient.invoke() Implementation

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-481
**Assigned-to**: unassigned

---

## Context

> Implements Module 8 from the spec. LocalLLMClient inherits from OpenAIClient and wraps
> OpenAI-compatible local servers (vLLM, llama.cpp, etc.). `_lightweight_model` is `None`
> because the user controls which local model to use. Structured output support depends on
> the local server's capabilities.

---

## Scope

- Add `_lightweight_model = None` class attribute to `LocalLLMClient`.
- Implement `invoke()` on `LocalLLMClient`:
  1. Call shared helpers for system prompt, structured config, model resolution.
  2. If structured output: attempt OpenAI-compatible `response_format` with `json_schema`.
     If the server doesn't support it, fall back to schema-in-prompt (like Claude).
  3. Single SDK call — no retry, no streaming, no history.
  4. Parse response, apply `custom_parser` if set, otherwise `_parse_structured_output()`.
  5. Build `InvokeResult` via `_build_invoke_result()`.
  6. Wrap exceptions via `_handle_invoke_error()`.
- Write unit tests with mocked OpenAI-compatible client.

**NOT in scope**: Changes to existing `ask()`. vLLM-specific optimizations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/localllm.py` | MODIFY | Add `_lightweight_model`, implement `invoke()` |
| `tests/unit/test_localllm_invoke.py` | CREATE | Unit tests with mocked client |

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

        # Try native JSON schema if structured output requested
        if config:
            # Attempt OpenAI-compatible format
            schema = config.get_schema()
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": config.output_type.__name__,
                    "schema": schema,
                    "strict": True,
                }
            }

        response = await self.client.chat.completions.create(**kwargs)
        raw_text = response.choices[0].message.content or ""

        output = raw_text
        if config:
            if config.custom_parser:
                output = config.custom_parser(raw_text)
            else:
                output = await self._parse_structured_output(raw_text, config)

        usage = CompletionUsage.from_openai(response.usage)
        return self._build_invoke_result(output, output_type, resolved_model, usage, response)
    except Exception as e:
        # If structured output format failed, retry with schema-in-prompt
        if config and "response_format" in str(e):
            return await self._invoke_with_schema_in_prompt(
                prompt, config, resolved_prompt, resolved_model,
                max_tokens, temperature, output_type
            )
        raise self._handle_invoke_error(e)
```

### Key Constraints
- `_lightweight_model = None` — `_resolve_invoke_model()` falls back to `self.model`.
- Local servers may not support `response_format` — fallback to schema-in-prompt.
- `_is_responses_model()` always returns False (line 103) — never use Responses API.
- No retry, no streaming, no conversation history.

### References in Codebase
- `parrot/clients/localllm.py:19` — class definition
- `parrot/clients/localllm.py:56` — default model `llama3.1:8b`
- `parrot/clients/localllm.py:103` — `_is_responses_model()` override

---

## Acceptance Criteria

- [ ] `_lightweight_model = None` set on `LocalLLMClient`
- [ ] `invoke()` attempts OpenAI-compatible structured output format
- [ ] Fallback to schema-in-prompt when server doesn't support `response_format`
- [ ] `invoke()` works with raw string (no output_type)
- [ ] `invoke()` uses `self.model` when no explicit model passed
- [ ] No conversation history, no retry, no streaming
- [ ] All tests pass: `pytest tests/unit/test_localllm_invoke.py -v`

---

## Test Specification

```python
# tests/unit/test_localllm_invoke.py
import pytest
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class SimpleResult(BaseModel):
    answer: str


class TestLocalLLMInvoke:
    async def test_openai_compat_structured(self, mock_localllm_client):
        """invoke() uses OpenAI-compatible response_format."""
        result = await mock_localllm_client.invoke(
            "Answer this", output_type=SimpleResult,
        )
        assert isinstance(result, InvokeResult)

    async def test_no_lightweight_model(self, mock_localllm_client):
        """Uses self.model when _lightweight_model is None."""
        result = await mock_localllm_client.invoke("Hello")
        assert result.model == mock_localllm_client.model

    async def test_raw_string(self, mock_localllm_client):
        """invoke() without output_type returns raw text."""
        result = await mock_localllm_client.invoke("Summarize")
        assert isinstance(result.output, str)

    async def test_error_wrapped(self, mock_localllm_client):
        """Provider errors wrapped in InvokeError."""
        with pytest.raises(InvokeError):
            await mock_localllm_client.invoke("test")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-487-localllm-invoke.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
