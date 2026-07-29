---
type: Wiki Overview
title: 'TASK-1351: Voice Module Extraction'
id: doc:sdd-tasks-completed-task-1351-voice-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move the entire `parrot/voice/` module (11 Python files, ~384 KB) to
relates_to:
- concept: mod:parrot.integrations.msteams.voice
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

# TASK-1351: Voice Module Extraction

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1344
**Assigned-to**: unassigned

---

## Context

Move the entire `parrot/voice/` module (11 Python files, ~384 KB) to
the satellite package. Voice has zero consumers outside of integrations
(only msteams/voice and telegram import from it). After this move,
`parrot.voice.*` resolves via PEP 420 namespace extension from the
satellite.

Implements **Spec Module 8**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/voice/` →
  `packages/ai-parrot-integrations/src/parrot/voice/`
  (11 files including `transcriber/` and `ui/` subdirs).
- Move related tests:
  - `packages/ai-parrot/tests/voice/`
- Remove `packages/ai-parrot/src/parrot/voice/` from core.
- Remove voice-related package-data entries from core pyproject if any.

**NOT in scope**: Changing voice logic. Updating pyproject extras
(done in TASK-1354).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/` | CREATE (move) | 11 Python files + subdirs |
| `packages/ai-parrot-integrations/tests/voice/` | CREATE (move) | Voice tests |
| `packages/ai-parrot/src/parrot/voice/` | DELETE | Removed from core |
| `packages/ai-parrot/tests/voice/` | DELETE | Tests moved |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Voice consumers (ALL within integrations — verified):
# parrot/integrations/telegram/models.py
# parrot/integrations/msteams/voice/ (4 files)
# No consumers outside integrations
```

### Does NOT Exist

- ~~`parrot.voice.VoiceBot`~~ — no such class; verify actual exports
- ~~External consumers of parrot.voice~~ — confirmed zero outside integrations

---

## Implementation Notes

### Key Constraints

- Voice contains `transcriber/` subdir with whisper-related code and
  `ui/` subdir — move everything.
- Voice uses `lazy_import("pydub", extra="audio")` pattern — preserve.
- The `[voice]` extra in satellite pyproject declares
  `faster-whisper` and `openai` as dependencies.

---

## Acceptance Criteria

- [ ] All 11 voice Python files present in satellite under `parrot/voice/`
- [ ] `from parrot.voice import ...` works via PEP 420
- [ ] Old `parrot/voice/` removed from core
- [ ] Voice tests pass in satellite
- [ ] `parrot.integrations.msteams.voice` still imports from `parrot.voice` correctly
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*
