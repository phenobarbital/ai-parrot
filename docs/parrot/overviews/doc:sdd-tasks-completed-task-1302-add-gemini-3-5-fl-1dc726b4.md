---
type: Wiki Overview
title: 'TASK-1302: Add `GEMINI_3_5_FLASH` to GoogleModel enum'
id: doc:sdd-tasks-completed-task-1302-add-gemini-3-5-flash-enum-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The spec's combined-mode whitelist references `gemini-3.5-flash` as a real
  Google model identifier (confirmed in the proposal Q&A — U1, citing https://ai.google.dev/gemini-api/docs/deprecations).
  The `GoogleModel` enum at `packages/ai-parrot/src/parrot/models/google.py:9-39`
  does
relates_to:
- concept: mod:parrot.models.google
  rel: mentions
---

# TASK-1302: Add `GEMINI_3_5_FLASH` to GoogleModel enum

**Feature**: FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
**Spec**: `sdd/specs/google-genai-combined-tools-and-schema.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The spec's combined-mode whitelist references `gemini-3.5-flash` as a real Google model identifier (confirmed in the proposal Q&A — U1, citing https://ai.google.dev/gemini-api/docs/deprecations). The `GoogleModel` enum at `packages/ai-parrot/src/parrot/models/google.py:9-39` does not yet contain this value. This task adds the enum entry so callers can reference the model symbolically rather than as a bare string. Implements spec §3 Module 1.

---

## Scope

- Add `GEMINI_3_5_FLASH = "gemini-3.5-flash"` to the `GoogleModel` enum.
- Add a one-line unit test asserting `GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"`.

**NOT in scope**:
- Adding the model to `VertexAIModel` (spec §8 Open Questions defers this until Vertex availability is verified).
- Any client.py changes (covered by TASK-1303 / TASK-1304 / TASK-1305).
- Touching any of the other 30+ enum entries in `GoogleModel` or related files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/google.py` | MODIFY | Add one enum line: `GEMINI_3_5_FLASH = "gemini-3.5-flash"`. |
| `packages/ai-parrot/tests/test_google_models.py` | CREATE or MODIFY | Add `test_google_model_enum_has_gemini_3_5_flash`. If the file does not exist, create it with a minimal scaffold. If it does exist, append the test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.google import GoogleModel   # verified at HEAD on dev (2026-05-27)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/google.py  (verified at HEAD, 589 lines)
from enum import Enum

class GoogleModel(Enum):
    """Enum for Google AI models."""
    GEMINI_3_PRO                    = "gemini-3.1-pro-preview"             # line 11
    GEMINI_3_PRO_PREVIEW            = "gemini-3.1-pro-preview"             # line 12
    GEMINI_3_FLASH                  = "gemini-3-flash-preview"             # line 13
    GEMINI_3_FLASH_PREVIEW          = "gemini-3-flash-preview"             # line 14
    GEMINI_FLASH_LATEST             = "gemini-3-flash-preview"             # line 15
    GEMINI_3_1_FLASH_LITE_PREVIEW   = "gemini-3.1-flash-lite-preview"      # line 16
    GEMINI_3_FLASH_LITE_PREVIEW     = "gemini-3.1-flash-lite-preview"      # line 17
    GEMINI_2_5_FLASH                = "gemini-2.5-flash"                   # line 18
    # ... (insert GEMINI_3_5_FLASH near the other 3.x entries, e.g. between line 17 and 18)
```

### Does NOT Exist

- ~~`GoogleModel.GEMINI_3_5_FLASH`~~ — does not exist yet; this task creates it.
- ~~`GoogleModel.GEMINI_3_5_FLASH_PREVIEW`~~ — the model name is exactly `gemini-3.5-flash` (no `-preview` suffix per Google's deprecations page). Do NOT add a preview variant.
- ~~`VertexAIModel.GEMINI_3_5_FLASH`~~ — out of scope (deferred to spec §8 Open Questions).
- ~~`gemini-3.5-flash-preview`~~, ~~`gemini-3-5-flash`~~, ~~`gemini3.5-flash`~~ — none of these are valid; the canonical identifier is `gemini-3.5-flash`.

---

## Implementation Notes

### Pattern to Follow

Look at the existing entries at `models/google.py:11-25` — they follow the convention `GEMINI_<MAJOR>_<MINOR>_<VARIANT> = "gemini-<major>.<minor>-<variant>"`. Insert the new entry alphabetically next to the other 3.x non-image entries (e.g. just after `GEMINI_3_FLASH_LITE_PREVIEW` on line 17).

### Key Constraints

- Do NOT add an alias (e.g. `GEMINI_FLASH_LATEST_STABLE = "gemini-3.5-flash"`) unless explicitly requested — keep this change minimal.
- Do NOT renumber or reformat the surrounding lines.
- Do NOT touch any other section of `models/google.py` (it contains 580+ lines of unrelated Voice/Music/Video models).

### References in Codebase

- `packages/ai-parrot/src/parrot/models/google.py:9-39` — enum definition (the only file to modify).
- `packages/ai-parrot/src/parrot/clients/google/client.py:115` — uses `GoogleModel.GEMINI_3_FLASH_PREVIEW.value`; analogous patterns exist for other enum entries (informational only — do not modify in this task).

---

## Acceptance Criteria

- [ ] `GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"`.
- [ ] `GoogleModel("gemini-3.5-flash") is GoogleModel.GEMINI_3_5_FLASH`.
- [ ] Existing tests in `packages/ai-parrot/tests/test_google_models.py` (if any) still pass.
- [ ] `from parrot.models.google import GoogleModel` still resolves without error.
- [ ] No other lines in `models/google.py` are modified (verify with `git diff`).

---

## Test Specification

```python
# packages/ai-parrot/tests/test_google_models.py
from parrot.models.google import GoogleModel


def test_google_model_enum_has_gemini_3_5_flash():
    """GEMINI_3_5_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"


def test_google_model_lookup_by_value():
    """The new entry is reachable via Enum(value) lookup."""
    assert GoogleModel("gemini-3.5-flash") is GoogleModel.GEMINI_3_5_FLASH
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/google-genai-combined-tools-and-schema.spec.md` for full context.
2. **Verify the Codebase Contract**:
   - `grep -n "GEMINI_3" packages/ai-parrot/src/parrot/models/google.py` — confirm the listed entries still match. If a recent commit reorganised the enum, update this task's contract first.
3. **Implement**: insert one line into the enum. No more, no less.
4. **Run the test**: `cd packages/ai-parrot && pytest tests/test_google_models.py -v`.
5. **Verify scope**: `git diff packages/ai-parrot/src/parrot/models/google.py` should show ONE added line.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-27
**Notes**: Added `GEMINI_3_5_FLASH = "gemini-3.5-flash"` to GoogleModel enum after GEMINI_3_FLASH_LITE_PREVIEW. Created `packages/ai-parrot/tests/test_google_models.py` with 2 tests; both pass.

**Deviations from spec**: none
