# TASK-488: Invoke Integration Tests

**Feature**: lightweight-invoke-client-method
**Spec**: `sdd/specs/lightweight-invoke-client-method.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-482, TASK-483, TASK-484, TASK-485, TASK-486, TASK-487
**Assigned-to**: unassigned

---

## Context

> Implements Module 9 from the spec. End-to-end integration tests that verify `invoke()`
> works correctly across all clients with real (mocked) provider interactions. Tests
> structured output, raw string, tools + structured two-call, custom_parser, error handling,
> and lightweight model defaults.

---

## Scope

- Write integration tests covering all acceptance criteria from the spec.
- Test cross-cutting concerns:
  - Structured output with Pydantic models and dataclasses.
  - Raw string output (no output_type).
  - `StructuredOutputConfig` with `custom_parser`.
  - Two-call strategy on Google/Groq (tools + structured output).
  - Error propagation as `InvokeError` with original preserved.
  - `_lightweight_model` default per client.
  - Model override via `model` parameter.
  - Custom `system_prompt` passthrough.
  - `use_tools=False` by default (no tools unless requested).

**NOT in scope**: Live API calls to real providers. Only mocked SDK interactions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_invoke.py` | CREATE | Integration tests for invoke() across all clients |

---

## Implementation Notes

### Test Structure
```python
# tests/integration/test_invoke.py
import pytest
from pydantic import BaseModel, Field
from dataclasses import dataclass
from parrot.models.responses import InvokeResult
from parrot.models.outputs import StructuredOutputConfig, OutputFormat
from parrot.models.basic import CompletionUsage
from parrot.exceptions import InvokeError


class PersonInfo(BaseModel):
    name: str = Field(description="Full name")
    age: int = Field(description="Age in years")

class SentimentResult(BaseModel):
    sentiment: str
    confidence: float

@dataclass
class SimpleData:
    key: str
    value: str


# Parametrize across all client types
@pytest.fixture(params=["anthropic", "openai", "google", "groq", "grok", "localllm"])
def mock_client(request):
    """Create a mocked client for each provider."""
    ...
```

### Key Constraints
- All tests use mocked SDK clients — no real API calls.
- Tests should verify the contract (InvokeResult fields, error types) not implementation details.
- Two-call tests only apply to Google and Groq — parametrize appropriately.

### References in Codebase
- `tests/integration/` — existing integration test patterns
- All 6 client files — for understanding how to mock each SDK

---

## Acceptance Criteria

- [ ] Integration tests cover structured output with Pydantic model
- [ ] Integration tests cover structured output with dataclass
- [ ] Integration tests cover raw string output
- [ ] Integration tests cover `custom_parser` in StructuredOutputConfig
- [ ] Integration tests cover two-call strategy (Google, Groq)
- [ ] Integration tests cover `InvokeError` propagation with `original`
- [ ] Integration tests cover `_lightweight_model` defaults
- [ ] Integration tests cover `model` override
- [ ] All tests pass: `pytest tests/integration/test_invoke.py -v`

---

## Test Specification

```python
class TestInvokeStructuredOutput:
    async def test_pydantic_model(self, mock_client):
        """invoke() returns validated Pydantic model instance."""
        result = await mock_client.invoke(
            "Extract: John is 30", output_type=PersonInfo,
        )
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, PersonInfo)
        assert result.output_type is PersonInfo

    async def test_dataclass(self, mock_client):
        """invoke() returns populated dataclass instance."""
        result = await mock_client.invoke(
            "Extract key-value", output_type=SimpleData,
        )
        assert isinstance(result, InvokeResult)

    async def test_custom_parser(self, mock_client):
        """StructuredOutputConfig with custom_parser applied."""
        def my_parser(text):
            return PersonInfo(name="Parsed", age=0)

        config = StructuredOutputConfig(
            output_type=PersonInfo,
            format=OutputFormat.JSON,
            custom_parser=my_parser,
        )
        result = await mock_client.invoke(
            "test", structured_output=config,
        )
        assert result.output.name == "Parsed"


class TestInvokeRawString:
    async def test_no_output_type(self, mock_client):
        """invoke() without output_type returns str."""
        result = await mock_client.invoke("Summarize this text")
        assert isinstance(result.output, str)
        assert result.output_type is None


class TestInvokeTwoCall:
    @pytest.fixture(params=["google", "groq"])
    def two_call_client(self, request):
        """Clients that need two-call for tools + structured."""
        ...

    async def test_tools_plus_structured(self, two_call_client):
        """Two-call strategy produces valid structured output."""
        result = await two_call_client.invoke(
            "Search and extract",
            output_type=PersonInfo,
            use_tools=True,
        )
        assert isinstance(result, InvokeResult)


class TestInvokeErrors:
    async def test_provider_error_wrapped(self, mock_client):
        """Provider exceptions wrapped in InvokeError."""
        # Configure mock to raise
        with pytest.raises(InvokeError) as exc_info:
            await mock_client.invoke("trigger error")
        assert exc_info.value.original is not None


class TestInvokeModelResolution:
    async def test_lightweight_model_default(self, mock_client):
        """Each client uses _lightweight_model by default."""
        result = await mock_client.invoke("test")
        if mock_client._lightweight_model:
            assert result.model == mock_client._lightweight_model

    async def test_model_override(self, mock_client):
        """Explicit model param overrides _lightweight_model."""
        result = await mock_client.invoke("test", model="custom-model")
        assert result.model == "custom-model"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-488-invoke-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
