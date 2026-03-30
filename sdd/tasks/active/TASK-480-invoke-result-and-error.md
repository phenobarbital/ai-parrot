# TASK-480: InvokeResult Model and InvokeError Exception

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 from the spec. `InvokeResult` and `InvokeError` are the foundational types
> that all other modules depend on. `InvokeResult` is the lightweight return type for `invoke()`
> calls (replacing `AIMessage`). `InvokeError` is the dedicated exception that wraps provider errors.

---

## Scope

- Implement `InvokeResult` Pydantic model in `parrot/models/responses.py`.
- Implement `InvokeError` exception in `parrot/exceptions.py`.
- Write unit tests for both.

**Fields for InvokeResult:**
- `output: Any` — parsed result (Pydantic model instance, dataclass, or raw str)
- `output_type: Optional[type] = None` — the class used for structured output (store the class itself)
- `model: str` — model used for this invocation
- `usage: CompletionUsage` — token usage statistics
- `raw_response: Optional[Any] = None` — provider's raw response for debugging

**Fields for InvokeError:**
- Extends `ParrotError`
- `original: Optional[Exception] = None` — the original provider exception

**NOT in scope**: Abstract method on AbstractClient, shared helpers, any client implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/models/responses.py` | MODIFY | Add `InvokeResult` class |
| `parrot/exceptions.py` | MODIFY | Add `InvokeError` class |
| `tests/unit/test_invoke_result.py` | CREATE | Unit tests for InvokeResult and InvokeError |

---

## Implementation Notes

### Pattern to Follow
```python
# InvokeResult follows the same Pydantic BaseModel pattern as AIMessage
class InvokeResult(BaseModel):
    """Lightweight result from a stateless invoke() call."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: Any = Field(description="Parsed result")
    output_type: Optional[type] = Field(default=None, description="Type class for structured output")
    model: str = Field(description="Model used")
    usage: CompletionUsage = Field(description="Token usage")
    raw_response: Optional[Any] = Field(default=None, description="Raw provider response")
```

```python
# InvokeError follows the existing ParrotError pattern
class InvokeError(ParrotError):
    """Raised when an invoke() call fails."""
    def __init__(self, message: str, *args, original: Optional[Exception] = None, **kwargs):
        super().__init__(message, *args, **kwargs)
        self.original = original
```

### Key Constraints
- `InvokeResult` must allow `arbitrary_types_allowed=True` because `output_type` stores a class reference.
- `InvokeError` must preserve the original exception for debugging.

### References in Codebase
- `parrot/models/responses.py:72` — `AIMessage` class (pattern reference)
- `parrot/models/basic.py:42` — `CompletionUsage` (used by InvokeResult)
- `parrot/exceptions.py:12` — `ParrotError` (base for InvokeError)

---

## Acceptance Criteria

- [ ] `InvokeResult` defined in `parrot/models/responses.py` with all 5 fields
- [ ] `InvokeError` defined in `parrot/exceptions.py` extending `ParrotError`
- [ ] `InvokeError.original` preserves the wrapped exception
- [ ] All tests pass: `pytest tests/unit/test_invoke_result.py -v`
- [ ] Imports work: `from parrot.models.responses import InvokeResult`
- [ ] Imports work: `from parrot.exceptions import InvokeError`

---

## Test Specification

```python
# tests/unit/test_invoke_result.py
import pytest
from pydantic import BaseModel, Field
from parrot.models.responses import InvokeResult
from parrot.models.basic import CompletionUsage
from parrot.exceptions import InvokeError


class SampleModel(BaseModel):
    name: str
    age: int


class TestInvokeResult:
    def test_structured_output(self):
        """InvokeResult with Pydantic model output."""
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        result = InvokeResult(
            output=SampleModel(name="Alice", age=30),
            output_type=SampleModel,
            model="gpt-4.1",
            usage=usage,
        )
        assert isinstance(result.output, SampleModel)
        assert result.output.name == "Alice"
        assert result.output_type is SampleModel
        assert result.model == "gpt-4.1"
        assert result.usage.total_tokens == 15
        assert result.raw_response is None

    def test_raw_string_output(self):
        """InvokeResult with raw string output."""
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        result = InvokeResult(
            output="Hello world",
            output_type=None,
            model="claude-haiku-4-5-20251001",
            usage=usage,
        )
        assert result.output == "Hello world"
        assert result.output_type is None

    def test_with_raw_response(self):
        """InvokeResult includes raw_response for debugging."""
        usage = CompletionUsage()
        raw = {"id": "msg_123", "content": [{"type": "text", "text": "hi"}]}
        result = InvokeResult(
            output="hi", model="test", usage=usage, raw_response=raw
        )
        assert result.raw_response == raw


class TestInvokeError:
    def test_basic_error(self):
        """InvokeError with message."""
        err = InvokeError("something failed")
        assert str(err) == "something failed"
        assert err.original is None

    def test_wraps_original(self):
        """InvokeError preserves original exception."""
        original = ValueError("API rate limit")
        err = InvokeError("invoke failed", original=original)
        assert err.original is original
        assert isinstance(err.original, ValueError)

    def test_is_parrot_error(self):
        """InvokeError inherits from ParrotError."""
        from parrot.exceptions import ParrotError
        err = InvokeError("test")
        assert isinstance(err, ParrotError)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-480-invoke-result-and-error.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
