---
type: Wiki Overview
title: 'TASK-1364: Integration test for document_understanding()'
id: doc:sdd-tasks-completed-task-1364-document-understanding-integration-test-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates an integration test that exercises `document_understanding()`
relates_to:
- concept: mod:parrot.clients.google
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
---

# TASK-1364: Integration test for document_understanding()

**Feature**: FEAT-203 — Google Document Understanding
**Spec**: `sdd/specs/google-document-understanding.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1362, TASK-1363
**Assigned-to**: unassigned

---

## Context

This task creates an integration test that exercises `document_understanding()`
against the real Gemini API with actual PDF documents. The test is marked with
`@pytest.mark.integration` so it only runs when explicitly requested and
requires valid Google API credentials.

Implements spec section: §4 (Integration Tests), §3 Module 3.

---

## Scope

- Create `tests/handlers/test_document_understanding_integration.py`.
- Test 1: Send a small real PDF to Gemini and verify AIMessage response.
- Test 2: Send a small PDF with a `StructuredOutputConfig` (Pydantic model)
  and verify `AIMessage.structured_output` is populated.
- Mark all tests with `@pytest.mark.integration`.
- Use a small inline-generated PDF (via `reportlab` or a static fixture file)
  to avoid external test data dependencies.

**NOT in scope**:
- Testing large file uploads (cost/time prohibitive in CI)
- Testing every supported document type
- Modifying implementation code

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_document_understanding_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from pathlib import Path
from pydantic import BaseModel, Field

from parrot.clients.google import GoogleGenAIClient  # verified: google/__init__.py:1
from parrot.models import AIMessage                  # verified: models/__init__.py
from parrot.models import StructuredOutputConfig     # verified: models/outputs.py:74
from parrot.models.google import GoogleModel         # verified: models/google.py:9
```

### Existing Signatures to Use

```python
# After TASK-1362, GoogleGenAIClient has via GoogleAnalysis mixin:
async def document_understanding(
    self,
    prompt: str,
    documents: Union[str, Path, List[Union[str, Path]]],
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
    structured_output: Optional[Union[type, StructuredOutputConfig]] = None,
    ...
) -> AIMessage:
```

### Does NOT Exist

- ~~`GoogleGenAIClient.document_understanding`~~ as a standalone — inherited via `GoogleAnalysis` mixin
- ~~`pytest.mark.live`~~ — use `pytest.mark.integration` (project convention)

---

## Implementation Notes

### Pattern to Follow

Follow existing integration test at `tests/handlers/test_understanding_integration.py`:

```python
# tests/handlers/test_document_understanding_integration.py
import pytest
from pathlib import Path
from pydantic import BaseModel, Field

from parrot.clients.google import GoogleGenAIClient
from parrot.models import AIMessage, StructuredOutputConfig


@pytest.mark.integration
class TestDocumentUnderstandingIntegration:

    @pytest.fixture
    def client(self):
        """Real GoogleGenAIClient — requires GOOGLE_API_KEY env var."""
        return GoogleGenAIClient()

    @pytest.fixture
    def sample_pdf(self, tmp_path):
        """Create a minimal real PDF for testing."""
        # ... generate a tiny PDF with some text content
        ...

    @pytest.mark.asyncio
    async def test_real_pdf_analysis(self, client, sample_pdf):
        result = await client.document_understanding(
            prompt="What is the main topic of this document?",
            documents=sample_pdf,
        )
        assert isinstance(result, AIMessage)
        assert result.provider == "google_genai"
        assert result.output  # non-empty response

    @pytest.mark.asyncio
    async def test_real_structured_output(self, client, sample_pdf):
        class DocumentSummary(BaseModel):
            title: str = Field(description="Document title")
            summary: str = Field(description="Brief summary")

        result = await client.document_understanding(
            prompt="Extract the title and summary",
            documents=sample_pdf,
            structured_output=DocumentSummary,
        )
        assert isinstance(result, AIMessage)
        assert result.structured_output is not None
```

### Key Constraints

- Requires `GOOGLE_API_KEY` environment variable.
- Use `@pytest.mark.integration` on every test.
- Keep test PDFs very small (< 100 KB) to minimize API cost and latency.
- If `reportlab` is not available, create a minimal PDF by writing raw PDF bytes
  (a valid minimal PDF is ~200 bytes).

### References in Codebase

- `tests/handlers/test_understanding_integration.py` — existing integration test pattern
- `tests/handlers/test_understanding_handler.py` — handler test pattern

---

## Acceptance Criteria

- [ ] Test file created at `tests/handlers/test_document_understanding_integration.py`
- [ ] Test: real PDF analysis returns AIMessage with non-empty output
- [ ] Test: structured output extraction populates AIMessage.structured_output
- [ ] All tests marked with `@pytest.mark.integration`
- [ ] Tests pass when run with credentials: `pytest tests/handlers/test_document_understanding_integration.py -v -m integration`

---

## Test Specification

```python
@pytest.mark.integration
class TestDocumentUnderstandingIntegration:
    async def test_real_pdf_analysis(self, client, sample_pdf): ...
    async def test_real_structured_output(self, client, sample_pdf): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-document-understanding.spec.md`
2. **Check dependencies** — TASK-1362 and TASK-1363 must be complete
3. **Read existing integration tests** at `tests/handlers/test_understanding_integration.py`
4. **Implement both tests**
5. **Run tests** (only if API key available): `pytest tests/handlers/test_document_understanding_integration.py -v -m integration`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-28
**Notes**: Created `tests/handlers/test_document_understanding_integration.py` with 2
integration tests: `test_real_pdf_analysis` (basic PDF → AIMessage) and
`test_real_structured_output` (PDF → DocumentSummary Pydantic model). Both marked with
`@pytest.mark.integration`. Used an inline minimal-PDF fixture (~1 KB) to avoid
external file dependencies and minimize API cost. Requires GOOGLE_API_KEY env var.
Skips gracefully when key is absent. Tests collect cleanly.

**Completed by**: sdd-worker agent
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
