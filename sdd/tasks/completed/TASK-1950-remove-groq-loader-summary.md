# TASK-1950: Remove Groq-based summary in AbstractLoader, replace with Gemini

**Feature**: remove-groq-loader-summary
**Feature ID**: FEAT-386
**Spec**: sdd/specs/remove-groq-loader-summary.spec.md
**Status**: [ ] pending | [ ] in-progress | [x] done
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

`AbstractLoader.summary_from_text()` in
`packages/ai-parrot/src/parrot/loaders/abstract.py` calls a Groq LLM client
for text summarization. The GROQ API key is invalid (401). The fix is to
replace the Groq client with a Google Gemini Flash Lite client.

## Scope

Modify **only** `packages/ai-parrot/src/parrot/loaders/abstract.py`:

1. Remove `from ..models.groq import GroqModel` (line 17).
2. Add `from ..models.google import GoogleModel` import (or add to existing
   google imports if present).
3. In `get_summarization_model()` (lines 1065–1100): replace the Groq branch:
   ```python
   # BEFORE (remove this):
   self._summary_model = LLMFactory.create(
       llm=f"groq:{GroqModel.LLAMA_3_3_70B_VERSATILE}",
       model_kwargs={
           "temperature": 0.1,
           "top_p": 0.5,
       }
   )
   ```
   With:
   ```python
   # AFTER:
   self._summary_model = LLMFactory.create(
       llm=f"google:{GoogleModel.GEMINI_2_5_FLASH_LITE.value}",
       model_kwargs={
           "temperature": 0.1,
       }
   )
   ```
4. In `summary_from_text()` (lines 1018–1063), replace the Groq-specific
   block:
   ```python
   # BEFORE (remove these three lines):
   await summarizer._ensure_client()
   summary = await summarizer.summarize_text(
       text=text,
       model=GroqModel.LLAMA_3_3_70B_VERSATILE,
       system_prompt=system_prompt,
       temperature=0.1,
       max_tokens=1000,
       top_p=0.5
   )
   ```
   With:
   ```python
   # AFTER:
   summary = await asyncio.to_thread(
       summarizer.summarize_text,
       text=text,
       model=GoogleModel.GEMINI_2_5_FLASH_LITE,
       temperature=0.1,
   )
   ```
5. Add `import asyncio` at the top of the file if not already present.
6. Remove the now-unused `system_prompt` f-string that was only used by the
   Groq call (lines 1042–1047 in the current file).

## Files to Create/Modify

- `packages/ai-parrot/src/parrot/loaders/abstract.py` — the only file to touch

## Implementation Notes

- `GoogleGenAIClient.summarize_text()` is **synchronous** — must use
  `asyncio.to_thread()` to avoid blocking the event loop.
- `GoogleModel.GEMINI_2_5_FLASH_LITE` maps to `"gemini-2.5-flash-lite"`.
- The return value is an `AIMessage`; `.output` is the text — compatible with
  the existing `return summary.output` line.
- Do **not** modify `get_default_llm()` or any other method; only the two
  methods described above.
- Do **not** touch any caller files (pdf.py, audio.py, youtube.py, etc.).

## Reference Code

- Google model enum: `packages/ai-parrot/src/parrot/models/google.py` line 25
  (`GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"`)
- Google summarize_text: `packages/ai-parrot/src/parrot/clients/google/analysis.py`
  line 1212
- LLMFactory: `packages/ai-parrot/src/parrot/clients/factory.py`

## Acceptance Criteria

- [ ] `GroqModel` is no longer imported in `abstract.py`
- [ ] `get_summarization_model()` creates a Google client with
  `gemini-2.5-flash-lite`
- [ ] `summary_from_text()` calls `summarize_text` via `asyncio.to_thread`
  (no `await` on a sync function)
- [ ] `ruff check .` exits 0
- [ ] `pytest -q` exits 0

## Output

When complete:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/remove-groq-loader-summary.json` status to "done"
3. Add completion note below

### Completion Note
Implemented 2026-07-28. Removed `from ..models.groq import GroqModel` import from
`packages/ai-parrot/src/parrot/loaders/abstract.py`. Replaced the Groq branch in
`get_summarization_model()` with a `GoogleGenAIClient` using
`GoogleModel.GEMINI_2_5_FLASH_LITE`. Updated `summary_from_text()` to call the
synchronous `summarizer.summarize_text()` via `asyncio.to_thread()` (no `await`,
no `_ensure_client()` warm-up). `asyncio` was already imported. Pre-existing ruff
and test failures (7 tests, 37k lint issues) confirmed present on base before this
change — none introduced by this fix.
