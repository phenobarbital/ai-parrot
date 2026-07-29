---
type: Wiki Overview
title: 'TASK-1362: Implement document_understanding() method and _upload_document()
  helper'
id: doc:sdd-tasks-completed-task-1362-document-understanding-method-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the core `document_understanding()` async method on
  the
---

# TASK-1362: Implement document_understanding() method and _upload_document() helper

**Feature**: FEAT-203 — Google Document Understanding
**Spec**: `sdd/specs/google-document-understanding.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the core `document_understanding()` async method on the
`GoogleAnalysis` mixin. It is the main deliverable of FEAT-203 and follows the
same patterns established by `video_understanding()` and `image_understanding()`.

Implements spec sections: §2 (Architectural Design), §3 Module 1.

---

## Scope

- Implement `async def document_understanding()` on the `GoogleAnalysis` class
  in `analysis.py`.
- Implement `async def _upload_document()` private helper for uploading
  documents via the Files API with PROCESSING → ACTIVE polling.
- Accept `documents` as a single path (str/Path) or a list of paths.
- Validate all files exist (raise `FileNotFoundError` if missing).
- Validate all files are ≤50 MB (raise `ValueError` if exceeded).
- Upload all documents via `client.aio.files.upload()`.
- Poll upload state until `ACTIVE` (raise `ValueError` on `FAILED`).
- Detect MIME type via `mimetypes.guess_type()`.
- Build multipart content: `[Part(text=prompt), Part(file_data=...), ...]`.
- Support `StructuredOutputConfig` via `_get_structured_config()` +
  `_apply_structured_output_schema()`.
- Support stateless mode (direct `generate_content`) and stateful mode
  (conversation history via `_prepare_conversation_context()` / chat session).
- Use `_await_with_progress()` for timeout-aware API calls.
- Return `AIMessage` via `AIMessageFactory.from_gemini()` with timing,
  usage, and `provider = "google_genai"`.

**NOT in scope**:
- Unit tests (TASK-1363)
- Integration tests (TASK-1364)
- URL-based document downloads
- Document chunking or splitting

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/analysis.py` | MODIFY | Add `document_understanding()` and `_upload_document()` methods |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use ONLY these verified imports and signatures. Do NOT invent.

### Verified Imports

```python
# Already imported at top of analysis.py — no new imports needed for these:
from pathlib import Path                         # analysis.py:8
import mimetypes                                 # NEW — add to imports
import time                                      # analysis.py:7
import uuid                                      # analysis.py:11
import asyncio                                   # analysis.py:6
import logging                                   # analysis.py:4
from typing import Any, List, Optional, Union    # analysis.py:2

# Already imported in analysis.py:
from google.genai import types                   # analysis.py:19
from google.genai.types import (
    GenerateContentConfig,                       # analysis.py:21
    Part,                                        # analysis.py:22
    ModelContent,                                # analysis.py:23
    UserContent,                                 # analysis.py:24
)

from ...models import (
    AIMessage,                                   # analysis.py:33
    AIMessageFactory,                            # analysis.py:34
    CompletionUsage,                             # analysis.py:35
)
from ...models.google import GoogleModel         # analysis.py:38
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/analysis.py:51
class GoogleAnalysis:
    logger: logging.Logger  # line 55
    # self.client — the genai.Client, accessed via MRO from GoogleGenAIClient

    # Pattern method to follow for upload + poll:
    async def _upload_video(self, video_path: Union[str, Path]) -> types.Part:  # line 1320
        # Uses: self.client.aio.files.upload(file=video_path)
        # Polls: video_file.state == "PROCESSING" → asyncio.sleep(5) → client.aio.files.get()
        # Returns: types.Part(file_data=types.FileData(file_uri=..., mime_type=...))

    # Pattern for timeout-aware awaiting:
    async def _await_with_progress(self, coro, *, label, timeout, log_interval=10):  # line 1287

    # Pattern for stateful conversation context:
    async def _prepare_conversation_context(
        self, prompt, files, user_id, session_id, system_prompt, stateless
    ):  # via AbstractClient (base.py)

    async def _update_conversation_memory(
        self, user_id, session_id, conversation_history, messages, ...
    ):  # via AbstractClient (base.py)

# packages/ai-parrot/src/parrot/clients/google/client.py:432
async def _ensure_client(self, model=None, **hints) -> genai.Client:

# packages/ai-parrot/src/parrot/clients/google/client.py:804
def _apply_structured_output_schema(
    self,
    generation_config: Dict[str, Any],
    output_config: Optional[StructuredOutputConfig]
) -> Optional[Dict[str, Any]]:

# packages/ai-parrot/src/parrot/clients/base.py:1444
def _get_structured_config(
    self,
    structured_output: Union[type, StructuredOutputConfig, None]
) -> Optional[StructuredOutputConfig]:

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
) -> AIMessage:
```

### Does NOT Exist

- ~~`types.Document`~~ — no such type in google.genai.types; use `Part(file_data=...)`
- ~~`self.client.aio.documents`~~ — no documents namespace; use `self.client.aio.files`
- ~~`GoogleAnalysis.document_understanding()`~~ — this is what we are creating
- ~~`GoogleAnalysis._upload_document()`~~ — this is what we are creating
- ~~`GoogleAnalysis._validate_documents()`~~ — does not exist; do validation inline
- ~~`types.DocumentData`~~ — does not exist; use `types.FileData`

---

## Implementation Notes

### Pattern to Follow

Follow `_upload_video()` (analysis.py:1320) for the upload + polling pattern:

```python
# Simplified pattern from _upload_video:
async def _upload_document(self, doc_path: Path) -> types.Part:
    if hasattr(self.client.aio, 'files'):
        doc_file = await self.client.aio.files.upload(file=doc_path)
    else:
        loop = asyncio.get_running_loop()
        doc_file = await loop.run_in_executor(
            None, lambda: self.client.files.upload(file=doc_path)
        )
    # Poll until ACTIVE
    while doc_file.state == "PROCESSING":
        await asyncio.sleep(2)
        if hasattr(self.client.aio, 'files'):
            doc_file = await self.client.aio.files.get(name=doc_file.name)
        else:
            loop = asyncio.get_running_loop()
            doc_file = await loop.run_in_executor(
                None, lambda: self.client.files.get(name=doc_file.name)
            )
    if doc_file.state == "FAILED":
        raise ValueError(f"Document processing failed: {doc_file.name}")
    return types.Part(
        file_data=types.FileData(file_uri=doc_file.uri, mime_type=doc_file.mime_type)
    )
```

Follow `image_understanding()` (analysis.py:496) for the overall method shape:
structured output config, stateless/stateful branching, AIMessage construction.

### Key Constraints

- Must be async throughout.
- Default temperature: `0.0` for deterministic analysis.
- `response_modalities`: `["TEXT"]` (documents produce text output).
- 50 MB size limit is a user requirement, not an API limit. Use clear error message:
  `f"File {path} is {size_mb:.1f} MB, exceeding the 50 MB limit"`.
- MIME type detection: use `mimetypes.guess_type(str(path))[0]` with fallback to
  `"application/octet-stream"`.
- Add `import mimetypes` at the top of `analysis.py` (it's stdlib, not yet imported).

### References in Codebase

- `analysis.py:1320-1387` — `_upload_video()` upload + poll pattern
- `analysis.py:496-669` — `image_understanding()` overall method structure
- `analysis.py:212-494` — `video_understanding()` stateful mode pattern
- `client.py:804-825` — `_apply_structured_output_schema()` for structured output

---

## Acceptance Criteria

- [ ] `document_understanding()` method exists on `GoogleAnalysis` class
- [ ] Accepts single path or list of paths (str or Path)
- [ ] Files >50 MB raise `ValueError` with descriptive message
- [ ] Missing files raise `FileNotFoundError`
- [ ] All documents uploaded via Files API with PROCESSING → ACTIVE polling
- [ ] Upload raises `ValueError` on `FAILED` state
- [ ] Supports `StructuredOutputConfig` and bare Pydantic model class
- [ ] Returns `AIMessage` via `AIMessageFactory.from_gemini()`
- [ ] `ai_message.provider == "google_genai"`
- [ ] Stateless mode works (generate_content)
- [ ] Stateful mode works (chat session with history)
- [ ] Default temperature is 0.0
- [ ] Timeout via `_await_with_progress()`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/google/analysis.py`

---

## Test Specification

> Tests are created in TASK-1363. This task focuses on implementation only.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-document-understanding.spec.md`
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm imports and line numbers match
4. **Read analysis.py** fully to understand the existing pattern
5. **Add `import mimetypes`** to the imports section
6. **Implement `_upload_document()`** following `_upload_video()` pattern
7. **Implement `document_understanding()`** following `image_understanding()` pattern
8. **Verify** all acceptance criteria
9. **Move this file** to `sdd/tasks/completed/`
10. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-28
**Notes**: Implemented `document_understanding()` async method and `_upload_document()`
private helper on `GoogleAnalysis` mixin in `analysis.py`. Added `import mimetypes`
(new import) and `StructuredOutputConfig` to the models import block. Both methods
follow the exact patterns specified (upload+poll from `_upload_video()`, overall
structure from `image_understanding()`). Pre-existing ruff issues in unrelated methods
(image_identification()) were not fixed as they are outside scope.

**Deviations from spec**: none
