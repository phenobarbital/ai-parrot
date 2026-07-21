---
type: Wiki Overview
title: 'TASK-1480: GoogleModel Computer-Use Entries'
id: doc:sdd-tasks-completed-task-1480-google-model-entries-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 6. Adds computer-use model entries to the GoogleModel
  enum
relates_to:
- concept: mod:parrot.models.google
  rel: mentions
---

# TASK-1480: GoogleModel Computer-Use Entries

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. Adds computer-use model entries to the GoogleModel enum
so they can be referenced by name throughout AI-Parrot.

---

## Scope

- Add `GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"` to GoogleModel
- Add `GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"` to GoogleModel
- Verify the enum entries resolve correctly

**NOT in scope**: client behavior changes (TASK-1479), toolkit, agent.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/google.py` | MODIFY | Add 2 enum entries |
| `packages/ai-parrot/tests/clients/test_google_models.py` | CREATE or MODIFY | Test new entries |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.google import GoogleModel  # verified: models/google.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/google.py:9
class GoogleModel(Enum):
    GEMINI_FLASH_LATEST = "gemini-flash-latest"          # line 11
    # ... 29 entries total, lines 11-37
    LYRIA = "models/lyria-realtime-exp"                  # line 37
```

### Does NOT Exist
- ~~`GoogleModel.GEMINI_COMPUTER_USE`~~ — does not exist yet (you add it)

---

## Implementation Notes

Add the entries after the existing model entries, before LYRIA or at the end.

```python
GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"
GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"
```

---

## Acceptance Criteria

- [ ] `GoogleModel.GEMINI_COMPUTER_USE.value == "gemini-2.5-computer-use-preview-10-2025"`
- [ ] `GoogleModel.GEMINI_3_FLASH_COMPUTER_USE.value == "gemini-3-flash-preview"`
- [ ] Existing enum entries unchanged
- [ ] No import errors

---

## Completion Note

Added `GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"` and `GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"` to the `GoogleModel` enum. `GEMINI_COMPUTER_USE` has the same value as the existing `GEMINI_COMPUTER_USE_PREVIEW` entry and thus becomes an enum alias (accessible via `GoogleModel.__members__['GEMINI_COMPUTER_USE']`). `GEMINI_3_FLASH_COMPUTER_USE` is a new unique entry. Tests use `__members__` lookup to correctly exercise the alias behavior. All 5 tests pass.
