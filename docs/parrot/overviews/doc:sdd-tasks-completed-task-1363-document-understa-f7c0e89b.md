---
type: Wiki Overview
title: 'TASK-1363: Unit tests for document_understanding()'
id: doc:sdd-tasks-completed-task-1363-document-understanding-unit-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates comprehensive unit tests for the `document_understanding()`
relates_to:
- concept: mod:parrot.clients.google
  rel: mentions
- concept: mod:parrot.clients.google.analysis
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
---

# TASK-1363: Unit tests for document_understanding()

**Feature**: FEAT-203 — Google Document Understanding
**Spec**: `sdd/specs/google-document-understanding.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1362
**Assigned-to**: unassigned

---

## Context

This task creates comprehensive unit tests for the `document_understanding()`
method and `_upload_document()` helper implemented in TASK-1362. Tests mock
the Google GenAI SDK to run without API credentials.

Implements spec section: §4 (Test Specification), §3 Module 2.

---

## Scope

- Create `tests/unit/test_google_document_understanding.py` with unit tests.
- Mock `client.aio.files.upload()`, `client.aio.files.get()`, and
  `client.aio.models.generate_content()` to avoid real API calls.
- Test all acceptance criteria from the spec:
  - Single PDF, multiple files, string paths
  - StructuredOutputConfig and bare Pydantic model class
  - Stateless and stateful modes
  - File >50 MB rejection (ValueError)
  - File not found rejection (FileNotFoundError)
  - Upload polling (PROCESSING → ACTIVE)
  - Upload failure (FAILED state → ValueError)
- Use `pytest` and `pytest-asyncio`.

**NOT in scope**:
- Integration tests with real API (TASK-1364)
- Implementation changes to `analysis.py`

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_google_document_understanding.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test imports
import pytest                                    # standard test framework
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# What we're testing — import AFTER TASK-1362 is complete:
# The method is on GoogleGenAIClient (inherits from GoogleAnalysis)
from parrot.clients.google import GoogleGenAIClient  # verified: google/__init__.py:1
from parrot.models import AIMessage                  # verified: models/__init__.py
from parrot.models import StructuredOutputConfig     # verified: models/outputs.py:74
from parrot.models.google import GoogleModel         # verified: models/google.py:9
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/analysis.py (after TASK-1362)
# New method signature (from spec §2):
async def document_understanding(
    self,
    prompt: str,
    documents: Union[str, Path, List[Union[str, Path]]],
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
    prompt_instruction: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    stateless: bool = True,
    timeout: Optional[int] = 600,
    temperature: Optional[float] = None,
    structured_output: Optional[Union[type, StructuredOutputConfig]] = None,
    max_output_tokens: Optional[int] = None,
) -> AIMessage:

# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    input: str           # line 76
    output: Any          # line 79
    model: str           # line 111
    provider: str        # line 114
    usage: CompletionUsage  # line 118
    structured_output: Any  # (field exists on AIMessage)
    is_structured: bool     # (field exists on AIMessage)
```

### Does NOT Exist

- ~~`GoogleAnalysis` standalone instantiation~~ — it's a mixin, test via `GoogleGenAIClient`
- ~~`parrot.clients.google.analysis.GoogleAnalysis`~~ — import via `parrot.clients.google.GoogleGenAIClient`
- ~~`AIMessage.documents`~~ — the field name is `documents` (Optional[List[Any]]) but may be empty

---

## Implementation Notes

### Pattern to Follow

Follow existing test patterns in the repo. Check for similar test files:

```python
# tests/unit/test_google_document_understanding.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path
from pydantic import BaseModel


class TestDocumentUnderstanding:
    """Tests for GoogleAnalysis.document_understanding()."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock GoogleGenAIClient with mocked SDK."""
        # Mock the genai client and its methods
        ...

    @pytest.fixture
    def sample_pdf(self, tmp_path):
        """Create a small test PDF file."""
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4 minimal content")
        return pdf

    @pytest.fixture
    def large_file(self, tmp_path):
        """Create a file >50 MB."""
        large = tmp_path / "large.bin"
        large.write_bytes(b"\0" * (51 * 1024 * 1024))
        return large

    @pytest.mark.asyncio
    async def test_single_pdf(self, mock_client, sample_pdf):
        """Single PDF, stateless, returns AIMessage."""
        result = await mock_client.document_understanding(
            prompt="Summarize this document",
            documents=sample_pdf,
        )
        assert isinstance(result, AIMessage)
        assert result.provider == "google_genai"

    @pytest.mark.asyncio
    async def test_file_too_large(self, mock_client, large_file):
        """File >50 MB raises ValueError."""
        with pytest.raises(ValueError, match="50 MB"):
            await mock_client.document_understanding(
                prompt="Summarize",
                documents=large_file,
            )

    @pytest.mark.asyncio
    async def test_file_not_found(self, mock_client):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await mock_client.document_understanding(
                prompt="Summarize",
                documents="/nonexistent/file.pdf",
            )
```

### Key Constraints

- Use `pytest-asyncio` for async tests (`@pytest.mark.asyncio`).
- Mock at the SDK level (`client.aio.files.upload`, `client.aio.models.generate_content`).
- Create real temporary files via `tmp_path` fixture for size validation tests.
- For the 50 MB test, create an actual file of that size (use `write_bytes`).
- Test both `str` and `Path` inputs for the `documents` parameter.
- For structured output tests, define a simple Pydantic model in the test file.

### References in Codebase

- `tests/unit/test_google_invoke.py` — existing Google client test patterns
- `tests/handlers/test_understanding_handler.py` — understanding test patterns
- `tests/handlers/test_understanding_integration.py` — integration test patterns

---

## Acceptance Criteria

- [ ] Test file created at `tests/unit/test_google_document_understanding.py`
- [ ] Test: single PDF returns AIMessage with provider="google_genai"
- [ ] Test: multiple files all uploaded
- [ ] Test: string paths accepted (not just Path objects)
- [ ] Test: StructuredOutputConfig populates AIMessage.structured_output
- [ ] Test: bare Pydantic class auto-wrapped
- [ ] Test: stateful mode calls _prepare_conversation_context
- [ ] Test: file >50 MB raises ValueError
- [ ] Test: missing file raises FileNotFoundError
- [ ] Test: upload polling PROCESSING → ACTIVE
- [ ] Test: upload FAILED state raises ValueError
- [ ] All tests pass: `pytest tests/unit/test_google_document_understanding.py -v`

---

## Test Specification

```python
# Full test list (implement all of these):

class TestDocumentUnderstanding:
    async def test_single_pdf(self, ...): ...
    async def test_multiple_files(self, ...): ...
    async def test_string_path(self, ...): ...
    async def test_structured_output_config(self, ...): ...
    async def test_structured_output_pydantic_class(self, ...): ...
    async def test_stateful_mode(self, ...): ...
    async def test_file_too_large(self, ...): ...
    async def test_file_not_found(self, ...): ...

class TestUploadDocument:
    async def test_upload_polls_processing(self, ...): ...
    async def test_upload_failed_state(self, ...): ...
    async def test_upload_mime_type_detection(self, ...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-document-understanding.spec.md`
2. **Check dependencies** — TASK-1362 must be in `sdd/tasks/completed/`
3. **Read the implementation** in `analysis.py` to understand the actual method signatures
4. **Check existing test patterns** in `tests/unit/test_google_invoke.py`
5. **Implement all tests** listed in the test specification
6. **Run tests**: `pytest tests/unit/test_google_document_understanding.py -v`
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-28
**Notes**: Created `tests/unit/test_google_document_understanding.py` with 19 passing tests
covering: single PDF, multiple files, string paths, StructuredOutputConfig, bare Pydantic
class, stateful mode, file-too-large, file-not-found, upload polling (PROCESSING→ACTIVE),
upload FAILED state, MIME type detection, and model enum acceptance. Used `get_client()`
patching (via `AsyncMock`) to inject mock SDK without the deprecated `client` setter.
All 19 tests pass: `pytest tests/unit/test_google_document_understanding.py -v`.

**Deviations from spec**: none | describe if any
