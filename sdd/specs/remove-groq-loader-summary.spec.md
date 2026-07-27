---
feature: remove-groq-loader-summary
feature_id: FEAT-386
type: hotfix
base_branch: dev
jira: NAV-9273
status: approved
created_at: "2026-07-28"
---

# FEAT-386: Remove Groq-based summary of text in Loaders

## Problem

The `AbstractLoader.summary_from_text()` method in
`packages/ai-parrot/src/parrot/loaders/abstract.py` uses `GroqClient` for
LLM-based text summarization. The `GROQ_API_KEY` is no longer valid in this
environment, causing a 401 error every time a loader attempts to produce a
summary.

Error observed in production (2026-07-27):

```
[INFO]  Parrot.Loaders.PDFLoader(pdf.py:214) :: Loading PDF file: ...
[ERROR] Parrot.Loaders.PDFLoader(abstract.py:1060) :: ERROR on summary_from_text:
        Error code: 401 - {'error': {'message': 'Invalid API Key', ...}}
```

The Groq provider is being phased out from this codebase. All summarization
should use Google Gemini instead.

## Affected Component

`AbstractLoader` — `packages/ai-parrot/src/parrot/loaders/abstract.py`

Callers that indirectly depend on this fix (no changes needed in these files):
- `parrot_loaders/pdf.py`
- `parrot_loaders/audio.py`
- `parrot_loaders/youtube.py`
- `parrot_loaders/pdfmark.py`
- `parrot_loaders/markdown.py`
- `parrot_loaders/videolocal.py`
- `parrot_loaders/html.py`
- `parrot_loaders/vimeo.py`

## Solution

Replace the Groq client in `get_summarization_model()` with
`GoogleGenAIClient` using the `gemini-2.5-flash-lite` model.

### Key technical constraints

1. **Sync vs async mismatch**: `GoogleAnalysis.summarize_text()` is a
   synchronous method (`def`, not `async def`). The current
   `summary_from_text()` calls `await summarizer.summarize_text(...)` and
   `await summarizer._ensure_client()`. After the switch:
   - Remove the `await summarizer._ensure_client()` call (Google client
     initialises lazily on first call, no explicit warm-up needed).
   - Call `summarizer.summarize_text(...)` without `await` (synchronous call).
     To avoid blocking the async event loop, wrap it with
     `asyncio.to_thread(...)`.

2. **Model constant**: Use `GoogleModel.GEMINI_2_5_FLASH_LITE` which maps to
   `"gemini-2.5-flash-lite"`.

3. **Import cleanup**: Remove `from ..models.groq import GroqModel` from
   `abstract.py` and add `from ..models.google import GoogleModel`.

4. **Return value**: `GoogleAnalysis.summarize_text()` returns an `AIMessage`;
   the output text is in `ai_message.output`. The current code already reads
   `summary.output`, so no change needed there.

## Acceptance Criteria

- [ ] `get_summarization_model()` no longer creates a `GroqClient`; it creates
  a `GoogleGenAIClient` with model `gemini-2.5-flash-lite`.
- [ ] `summary_from_text()` calls `summarize_text()` without `await`, wrapped
  in `asyncio.to_thread()` to preserve async safety.
- [ ] `GroqModel` import is removed from `abstract.py`.
- [ ] `ruff check .` passes with exit code 0.
- [ ] `pytest -q` passes with exit code 0.
- [ ] No other files are modified (callers are untouched).
