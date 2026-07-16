---
type: Wiki Overview
title: 'Feature Specification: Google Document Understanding'
id: doc:sdd-specs-google-document-understanding-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: for document processing. Users who need to extract information, summarize,
relates_to:
- concept: mod:parrot.loaders
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Google Document Understanding

**Feature ID**: FEAT-203
**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`GoogleAnalysis` mixin already provides `video_understanding()` and
`image_understanding()` for multimodal analysis, but there is no equivalent
for document processing. Users who need to extract information, summarize,
or query PDF and other document types currently have no built-in method and
must manually handle file uploads, size checks, and response parsing.

Google Gemini supports rich document processing capabilities including inline
data for small documents and the Files API for large ones (up to 2 GB),
structured output via `response_schema`, and multi-document analysis.

### Goals

- Add `document_understanding()` async method to `GoogleAnalysis` mixin.
- Support all Gemini-supported document types (PDF, TXT, HTML, CSS, JS, PY,
  MD, CSV, XML, RTF, DOCX, XLSX, PPTX, and more).
- Pre-validate files >50 MB before upload (user-requested threshold).
- Upload files via Google GenAI Files API for documents exceeding inline limits.
- Support multiple document uploads in a single call.
- Support `StructuredOutputConfig` for typed responses (same pattern as `ask()`).
- Return `AIMessage` via `AIMessageFactory.from_gemini()` (consistent with
  all other GoogleAnalysis methods).
- Support both stateless and stateful (conversation memory) modes.

### Non-Goals (explicitly out of scope)

- OCR-specific preprocessing — Gemini handles OCR natively for PDFs.
- Document chunking or splitting — out of scope; send whole documents.
- Document-to-document conversion (e.g., PDF to DOCX).
- Caching of uploaded files across calls.

---

## 2. Architectural Design

### Overview

A new `document_understanding()` async method on the `GoogleAnalysis` mixin
that follows the same patterns as `video_understanding()` and
`image_understanding()`:

1. Accept a prompt, one or more document paths (or URLs), and optional
   configuration (model, structured output, temperature, etc.).
2. Validate file sizes — reject files >50 MB with a clear error (user requirement).
3. For files ≤20 MB: upload via the Files API (Google's recommended approach
   for documents, since inline base64 doubles the payload).
4. For files >20 MB and ≤50 MB: upload via the Files API with progress polling.
5. Construct a multipart content request with text prompt + uploaded file references.
6. Call `generate_content` (stateless) or `chat.send_message` (stateful).
7. Parse response, optionally apply structured output schema, and return `AIMessage`.

### Component Diagram

```
User
 │
 ▼
document_understanding(prompt, documents, ...)
 │
 ├── _validate_document_files()     → size check (>50 MB → error)
 │
 ├── _upload_document()             → Files API upload + state polling
 │   (reuses _upload_video pattern for polling PROCESSING → ACTIVE)
 │
 ├── Build content parts:
 │   [Part(text=prompt), Part(file_data=uploaded_1), Part(file_data=uploaded_2), ...]
 │
 ├── GenerateContentConfig          → structured output schema if provided
 │
 ├── client.aio.models.generate_content()  (stateless)
 │   OR client.aio.chats.create() + send_message()  (stateful)
 │
 └── AIMessageFactory.from_gemini() → AIMessage
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleAnalysis` mixin | extends | New method added to existing mixin |
| `GoogleGenAIClient` | inherits | Gets method via MRO from GoogleAnalysis |
| `AIMessageFactory.from_gemini()` | uses | Standard response construction |
| `StructuredOutputConfig` | uses | Optional typed output parsing |
| `_ensure_client()` | calls | Client initialization before API call |
| `_await_with_progress()` | calls | Timeout-aware awaiting |
| `_prepare_conversation_context()` | calls | For stateful mode |
| `_update_conversation_memory()` | calls | For stateful mode |
| `_apply_structured_output_schema()` | calls | Schema cleaning for Gemini |
| `clean_google_schema()` | calls | Strip unsupported JSON schema keys |
| Files API (`client.aio.files.upload`) | calls | Document upload |

### Data Models

No new Pydantic models required. Uses existing:

```python
# Existing models — no changes needed
from parrot.models import AIMessage, AIMessageFactory, StructuredOutputConfig, CompletionUsage
from parrot.models.google import GoogleModel
```

### New Public Interfaces

```python
# Added to GoogleAnalysis mixin (parrot/clients/google/analysis.py)
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
    """
    Analyze and extract information from one or more documents.

    Supports all Gemini-compatible document types: PDF, TXT, HTML, CSS,
    JS, PY, MD, CSV, XML, RTF, DOCX, XLSX, PPTX, etc.

    Files are uploaded via the Google GenAI Files API. Files larger than
    50 MB are rejected with a ValueError.

    Args:
        prompt: The question or instruction about the document(s).
        documents: Path(s) to local document file(s). Single path or list.
        model: Gemini model to use.
        prompt_instruction: Optional system instruction.
        user_id: Optional user ID for conversation memory.
        session_id: Optional session ID for conversation memory.
        stateless: If True, skip conversation memory.
        timeout: Timeout in seconds for the API call.
        temperature: Sampling temperature (default 0.0 for deterministic).
        structured_output: Optional Pydantic model or StructuredOutputConfig
            for typed response parsing (same as ask()).
        max_output_tokens: Optional maximum output tokens.

    Returns:
        AIMessage with the model's response. If structured_output is
        provided, AIMessage.structured_output contains the parsed object.

    Raises:
        ValueError: If any file exceeds 50 MB.
        FileNotFoundError: If any document path does not exist.
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: Document Understanding Method

- **Path**: `packages/ai-parrot/src/parrot/clients/google/analysis.py`
- **Responsibility**: Implement `document_understanding()` async method and
  `_upload_document()` private helper on the `GoogleAnalysis` mixin.
- **Depends on**: Existing `GoogleAnalysis` class, `_ensure_client()`,
  `_await_with_progress()`, `_prepare_conversation_context()`,
  `_update_conversation_memory()`, `AIMessageFactory.from_gemini()`,
  `_apply_structured_output_schema()`, `clean_google_schema()`,
  `_get_structured_config()`.

### Module 2: Unit Tests

- **Path**: `tests/unit/test_google_document_understanding.py`
- **Responsibility**: Unit tests for the `document_understanding()` method
  covering: file validation, single/multiple documents, structured output,
  stateless and stateful modes, error handling.
- **Depends on**: Module 1

### Module 3: Integration Test

- **Path**: `tests/handlers/test_document_understanding_integration.py`
- **Responsibility**: Integration test that calls the actual Gemini API
  with a small test PDF. Marked with `@pytest.mark.integration` so it
  only runs when explicitly requested.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_document_understanding_single_pdf` | 1 | Single PDF file, stateless, returns AIMessage |
| `test_document_understanding_multiple_files` | 1 | List of documents, all uploaded |
| `test_document_understanding_structured_output` | 1 | StructuredOutputConfig with Pydantic model |
| `test_document_understanding_structured_output_class` | 1 | Bare Pydantic class (auto-wrapped) |
| `test_document_understanding_stateful` | 1 | Stateful mode with conversation memory |
| `test_document_understanding_file_too_large` | 1 | File >50 MB raises ValueError |
| `test_document_understanding_file_not_found` | 1 | Missing file raises FileNotFoundError |
| `test_document_understanding_string_path` | 1 | Accepts str paths (not just Path objects) |
| `test_upload_document_polling` | 1 | _upload_document polls PROCESSING → ACTIVE |
| `test_upload_document_failed_state` | 1 | _upload_document raises on FAILED state |

### Integration Tests

| Test | Description |
|---|---|
| `test_document_understanding_real_pdf` | End-to-end with a real small PDF via Gemini API |
| `test_document_understanding_real_structured` | End-to-end structured output extraction |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_pdf(tmp_path):
    """Create a minimal PDF for testing."""
    # Use reportlab or a pre-made tiny PDF
    pdf_path = tmp_path / "test.pdf"
    # ... create minimal PDF content
    return pdf_path

@pytest.fixture
def large_file(tmp_path):
    """Create a file >50 MB for rejection testing."""
    large_path = tmp_path / "large.bin"
    large_path.write_bytes(b"\0" * (51 * 1024 * 1024))
    return large_path
```

---

## 5. Acceptance Criteria

- [ ] `document_understanding()` method exists on `GoogleAnalysis` mixin.
- [ ] Accepts single path or list of paths (str or Path).
- [ ] Files >50 MB raise `ValueError` with a clear message.
- [ ] Missing files raise `FileNotFoundError`.
- [ ] All documents are uploaded via the Files API (`client.aio.files.upload`).
- [ ] Upload polls for `PROCESSING` → `ACTIVE` state (same pattern as `_upload_video`).
- [ ] Upload raises `ValueError` on `FAILED` state.
- [ ] Supports `StructuredOutputConfig` — schema applied via `_apply_structured_output_schema()`.
- [ ] Supports bare Pydantic model class (auto-wrapped via `_get_structured_config()`).
- [ ] When structured output is requested, `AIMessage.structured_output` is populated.
- [ ] Returns `AIMessage` via `AIMessageFactory.from_gemini()` with usage, provider, timing.
- [ ] `ai_message.provider` is set to `"google_genai"`.
- [ ] Stateless mode works (no conversation memory).
- [ ] Stateful mode works (loads/saves conversation history).
- [ ] Default temperature is `0.0` for deterministic analysis.
- [ ] Timeout support via `_await_with_progress()`.
- [ ] All unit tests pass: `pytest tests/unit/test_google_document_understanding.py -v`
- [ ] No breaking changes to existing `GoogleAnalysis` or `GoogleGenAIClient` APIs.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/models/__init__.py exports these
from parrot.models import AIMessage, AIMessageFactory, CompletionUsage
from parrot.models import StructuredOutputConfig, OutputFormat

# verified: packages/ai-parrot/src/parrot/models/google.py:9
from parrot.models.google import GoogleModel

# verified: packages/ai-parrot/src/parrot/clients/google/analysis.py:19-25
from google.genai import types
from google.genai.types import (
    GenerateContentConfig,
    Part,
    ModelContent,
    UserContent,
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/google/analysis.py:51
class GoogleAnalysis:
    """Mixin class for Google Generative AI analysis capabilities."""
    logger: logging.Logger  # line 55

    # Existing async methods that serve as patterns:
    async def video_understanding(self, prompt, ...) -> AIMessage:  # line 212
    async def image_understanding(self, prompt, images, ...) -> AIMessage:  # line 496

    # Private helpers available via MRO from GoogleGenAIClient:
    async def _ensure_client(self, model=None, **hints) -> genai.Client:  # client.py:432
    async def _await_with_progress(self, coro, *, label, timeout, log_interval=10):  # analysis.py:1287
    async def _upload_video(self, video_path) -> types.Part:  # analysis.py:1320
    async def _prepare_conversation_context(self, prompt, files, user_id, session_id, system_prompt, stateless):  # base.py (AbstractClient)
    async def _update_conversation_memory(self, user_id, session_id, conversation_history, messages, ...):  # base.py (AbstractClient)

# packages/ai-parrot/src/parrot/clients/google/client.py:804
def _apply_structured_output_schema(
    self,
    generation_config: Dict[str, Any],
    output_config: Optional[StructuredOutputConfig]
) -> Optional[Dict[str, Any]]:  # line 804

# packages/ai-parrot/src/parrot/clients/google/client.py:668
def clean_google_schema(self, schema: dict) -> dict:  # line 668

# packages/ai-parrot/src/parrot/clients/base.py:1444
def _get_structured_config(
    self,
    structured_output: Union[type, StructuredOutputConfig, None]
) -> Optional[StructuredOutputConfig]:  # line 1444

# packages/ai-parrot/src/parrot/models/responses.py:866
@staticmethod
def from_gemini(
    response: Any,
    input_text: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None,
    tool_calls: List[ToolCall] = None,
    conversation_history: Optional[Any] = None,
    text_response: Optional[str] = None,
    files: Optional[List[Path]] = None,
    images: Optional[List[Any]] = None,
    code: Optional[str] = None
) -> AIMessage:  # line 866

# packages/ai-parrot/src/parrot/models/outputs.py:74
@dataclass
class StructuredOutputConfig:
    output_type: type  # line 76
    format: OutputFormat = OutputFormat.JSON  # line 77
    custom_parser: Optional[Callable[[str], Any]] = None  # line 78
    def get_schema(self) -> dict[str, Any]:  # line 80
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `document_understanding()` | `_ensure_client()` | method call | `client.py:432` |
| `document_understanding()` | `_await_with_progress()` | method call | `analysis.py:1287` |
| `document_understanding()` | `client.aio.files.upload()` | SDK call | pattern at `analysis.py:1332` |
| `document_understanding()` | `client.aio.files.get()` | SDK poll | pattern at `analysis.py:1364` |
| `document_understanding()` | `AIMessageFactory.from_gemini()` | static call | `responses.py:866` |
| `document_understanding()` | `_apply_structured_output_schema()` | method call | `client.py:804` |
| `document_understanding()` | `_get_structured_config()` | method call | `base.py:1444` |
| `document_understanding()` | `_prepare_conversation_context()` | method call | stateful mode |
| `document_understanding()` | `_update_conversation_memory()` | method call | stateful mode |

### Does NOT Exist (Anti-Hallucination)

- ~~`GoogleAnalysis.document_understanding()`~~ — this is what we are creating
- ~~`GoogleAnalysis._upload_document()`~~ — does not exist yet; create it
- ~~`parrot.loaders.pdf_loader`~~ — not relevant; this feature uses Gemini API directly
- ~~`types.Document`~~ — no such type in google.genai.types; use `Part(file_data=...)`
- ~~`self.client.aio.documents`~~ — no documents namespace in the SDK; use `self.client.aio.files`
- ~~`GoogleAnalysis._validate_documents()`~~ — does not exist; create it or do inline

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **File upload pattern**: Follow `_upload_video()` at `analysis.py:1320` for the
  async upload + polling loop pattern. Same approach: `client.aio.files.upload()`,
  poll `state == "PROCESSING"`, raise on `"FAILED"`.
- **Structured output pattern**: Follow `image_understanding()` at `analysis.py:567-574`
  for applying `response_schema` via `GenerateContentConfig`. For the full
  `StructuredOutputConfig` integration, follow `ask()` at `client.py:2193` which
  calls `_get_structured_config()` then `_apply_structured_output_schema()`.
- **AIMessage construction**: Follow `image_understanding()` at `analysis.py:648-665`
  for `AIMessageFactory.from_gemini()` usage with timing, usage, and provider.
- **Stateful mode**: Follow `video_understanding()` at `analysis.py:244-272` for
  conversation history preparation and `analysis.py:447-465` for memory update.
- **Progress logging**: Use `_await_with_progress()` for the generate_content call
  (pattern at `analysis.py:410-418`).
- **MIME type detection**: Use `mimetypes.guess_type()` from stdlib. Fall back to
  `"application/octet-stream"` if unknown.

### Known Risks / Gotchas

- **50 MB limit is a user requirement**, not a Gemini API limit. The Files API
  supports up to 2 GB. The 50 MB check is a guardrail to prevent accidental
  upload of very large files. Document this in the method docstring.
- **Files API upload is async but polling is needed**: The upload returns
  immediately but the file may be in `PROCESSING` state. Must poll until
  `ACTIVE` before using in `generate_content`.
- **Inline data is NOT used**: Unlike `image_understanding` which uses inline
  data for small images, documents should always use the Files API per Google's
  recommendation (base64-encoding a PDF doubles its size and wastes context).
- **Structured output + document processing**: Gemini supports `response_schema`
  with document content. No special handling needed beyond the standard
  `_apply_structured_output_schema()` flow.
- **MIME types**: Google Gemini supports these document MIME types:
  `application/pdf`, `text/plain`, `text/html`, `text/css`, `text/javascript`,
  `application/x-python`, `text/x-python`, `text/markdown`, `text/csv`,
  `application/xml`, `text/xml`, `application/rtf`, and various office formats.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `google-genai` | `>=1.0` | Already a dependency; Files API support |
| `mimetypes` | stdlib | MIME type detection for uploads |

---

## 8. Open Questions

- [ ] Should we add a `max_file_size_mb` parameter to let callers override the
  50 MB default? — *Owner: Jesus*
- [ ] Should we support URL-based documents (e.g., `https://example.com/doc.pdf`)
  by downloading first, or leave that to the caller? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All three modules are sequential (tests depend on implementation).
- No cross-feature dependencies.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-28 | Jesus Lara | Initial draft |
