---
type: Wiki Overview
title: 'TASK-1599: Relocate StructuredOutputMessage out of livekit_agent/'
id: doc:sdd-tasks-completed-task-1599-relocate-structured-output-message-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Phase C worker package `liveavatar/livekit_agent/` is being deleted
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1599: Relocate StructuredOutputMessage out of livekit_agent/

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The Phase C worker package `liveavatar/livekit_agent/` is being deleted
(TASK-1600), but `StructuredOutputMessage` (its event envelope) is shared by the
**kept** structured-output path (Mode A/B/C → `OutputBridge` → Redis →
`/ws/userinfo`). It must be moved to a non-Phase-C module **before** the package
is deleted, or `output_bridge.py` / `output_transport.py` break. (Spec §3.4, §6.)

---

## Scope

- Move `StructuredOutputMessage` (the Pydantic model) from
  `liveavatar/livekit_agent/models.py` into `liveavatar/models.py`.
- Update every non-deleted importer to import from the new location.
- Re-export `StructuredOutputMessage` from `liveavatar/__init__.py`.
- Leave `AvatarJobMetadata` where it is (it is Phase-C-only and dies with
  TASK-1600).

**NOT in scope**: deleting the `livekit_agent/` package (TASK-1600); changing the
model's fields.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` | MODIFY | Add `StructuredOutputMessage` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/models.py` | MODIFY | Remove `StructuredOutputMessage` (keep `AvatarJobMetadata` until TASK-1600) |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_bridge.py` | MODIFY | Import from `..models` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py` | MODIFY | Import from `..models` if it references the symbol |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export `StructuredOutputMessage` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent_models.py` | MODIFY | Update import path (or move assertions) |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# liveavatar/livekit_agent/models.py:42  (current location)
class StructuredOutputMessage(BaseModel):
    type: str            # line 57  — one of {chart, data, canvas, tool_call}
    session_id: str      # line 61
    payload: Dict[str, Any]  # line 65
    turn_id: Optional[str] = None  # line 69

# liveavatar/output_bridge.py:19  imports StructuredOutputMessage (update this)
# liveavatar/models.py  — target module; already defines LiveAvatarConfig (:18),
#   AvatarSessionHandle (:86), FullModeConfig (:131), FullModeSessionHandle (:160)
```

### Does NOT Exist
- ~~a second copy of `StructuredOutputMessage`~~ — there is exactly one (livekit_agent/models.py:42)
- ~~`StructuredOutputMessage` in `parrot.models.responses`~~ — that's `AIMessage`, unrelated

---

## Implementation Notes

- Keep the class definition byte-identical; only the module changes.
- `fullmode_observer.py:214` also imports it, but that file is deleted in
  TASK-1602 — do not spend effort fixing it.
- After the move: `python -c "from parrot.integrations.liveavatar import StructuredOutputMessage"` must succeed.

---

## Acceptance Criteria

- [ ] `StructuredOutputMessage` lives in `liveavatar/models.py` and is gone from `livekit_agent/models.py`.
- [ ] `from parrot.integrations.liveavatar import StructuredOutputMessage` works.
- [ ] `output_bridge.py` imports it from `..models`.
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_output*.py -q` passes.
- [ ] No remaining non-deleted import of `livekit_agent.models.StructuredOutputMessage`.

---

## Agent Instructions
Standard SDD flow (verify contract, implement, test, move to completed, update index, fill completion note).

## Completion Note
Implemented 2026-06-19. `StructuredOutputMessage` moved from
`livekit_agent/models.py` to `liveavatar/models.py`. Updated:
- `output_bridge.py` now imports from `..models`
- `livekit_agent/models.py` retains only `AvatarJobMetadata`
- `livekit_agent/__init__.py` re-exports only `AvatarJobMetadata`
- `liveavatar/__init__.py` re-exports `StructuredOutputMessage`
- Test files updated to new import path
All 12 tests pass (`test_output_bridge`, `test_output_transport`, `test_livekit_agent_models`).
