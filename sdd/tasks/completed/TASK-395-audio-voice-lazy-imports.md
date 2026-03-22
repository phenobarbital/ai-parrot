# TASK-395: Audio/Voice Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

Audio and voice processing modules import `pydub`, `whisperx`, and `moviepy` at module level. These require ffmpeg and other system dependencies. They should be lazy-imported since most users don't need audio processing.

Implements: Spec Module 10 — Audio/Voice Lazy Imports.

---

## Scope

- Convert top-level imports to `lazy_import()` in:
  - `parrot/voice/transcriber/transcriber.py` — pydub → `lazy_import("pydub", extra="audio")`
  - `parrot/loaders/basevideo.py` — pydub, moviepy → `lazy_import(..., extra="loaders")`
- Search for other files importing pydub/whisperx/moviepy and convert.

**NOT in scope**: pydub in clients (TASK-388).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/voice/transcriber/transcriber.py` | MODIFY | Lazy-import pydub |
| `parrot/loaders/basevideo.py` | MODIFY | Lazy-import pydub, moviepy |

---

## Implementation Notes

### Key Constraints
- pydub requires ffmpeg system binary — not a pip dependency issue but still heavy
- whisperx/moviepy are in `[loaders]` extra, pydub core usage moves to `[audio]`
- Voice transcriber must be importable without pydub

---

## Acceptance Criteria

- [ ] All listed files importable without pydub/moviepy installed
- [ ] Audio/voice functionality works when deps are installed
- [ ] Missing dep raises appropriate `pip install ai-parrot[audio]` or `ai-parrot[loaders]`
- [ ] All existing tests pass with deps installed

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-395-audio-voice-lazy-imports.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-03-22
**Notes**: Converted pydub imports in transcriber.py and pydub/moviepy imports in basevideo.py to use lazy_import(). TYPE_CHECKING block imports in basevideo.py left as-is (not executed at runtime). Also searched for other pydub/moviepy/whisperx importers; generation.py already had try/except pattern at module level and method-level imports inside methods — no change needed.

**Deviations from spec**: none
