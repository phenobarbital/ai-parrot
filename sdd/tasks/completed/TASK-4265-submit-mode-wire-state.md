# TASK-4265: Wire + state — StartSession.submit_mode, AnswersReady, state and snapshot field

**Feature**: FEAT-656 — Audio form client-submit mode (voice collects, the host submits)
**Spec**: `sdd/specs/audio-form-client-submit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 (Wire, State) / M1. Every later task consumes the symbols this one creates: `StartSession.submit_mode`, `AnswersReady`, `AudioSessionState.submit_mode`, `AudioSnapshot.submit_mode`.

---

## Scope

- Add `submit_mode: Literal["server", "client"] = "server"` to `StartSession` (G1).
- Add outbound `AnswersReady(_Wire)` next to `FormComplete` and add it to the `WireMessage` union.
- Add `submit_mode` to `AudioSessionState` (`extra="forbid"` model) and to `AudioSnapshot`, both defaulting to `"server"` so old snapshots and existing tests keep validating (AC1).
- Tests: default, wire shape, union membership, state/snapshot round-trip.

**NOT in scope**: the v2 guard and the engine branch (TASK-4266); the adapter (TASK-4267).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` | MODIFY | `StartSession.submit_mode`, `AnswersReady`, `WireMessage` member |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | `AudioSessionState.submit_mode` + docstring |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` | MODIFY | `AudioSnapshot.submit_mode` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py` | MODIFY | default / wire / union tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py` | MODIFY | state field default test |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` | MODIFY | snapshot round-trip keeps submit_mode |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-10-12 (`grep -c` re-run at tasking time). Use VERBATIM; verify anything not listed.

### Verified Imports
```python
from typing import Annotated, Any, Literal, Union          # verified: audio/events.py:10 (Literal, Any already imported)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter  # verified: audio/events.py:12
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py
class StartSession(_Inbound):          # :93 ; last field `enumerate_options: bool | None = None` at :106
class FormComplete(_Wire):             # :428  (type, submission_id, answers, stored_in, plausibility_summary)
class SessionEnded(_Wire):             # :436
WireMessage = Union[... FormComplete, SessionEnded, Error, Pong]   # :~500-524, `    FormComplete,` at :520
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py
class AudioSessionState(BaseModel):    # :258 ; `    protocol_version: int = 1` at :315 ; docstring line `protocol_version: Wire protocol version (1 = legacy).` at :288
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py
class AudioSnapshot(BaseModel):        # :40 ; `    flagged: dict[str, int] = Field(default_factory=dict)` at :55 ; `    submission_id: str` at :56
```

### Does NOT Exist
- ~~`submit_mode`~~, ~~`AnswersReady`~~ — anywhere in the package today; created here.
- ~~an `answers_ready` entry in `_V2_ONLY_TYPES` (audio_ws.py)~~ — not needed: client mode requires v2 (TASK-4266 guard).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#StartSession",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#FormComplete",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionState",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py#AudioSnapshot"
  ]
}
```

---

## Implementation Blueprint

> Executor-ready starting point: write each block nearly verbatim, complete every `# FILL IN:`. Never change a
> signature, class name or path the blueprint fixes.

### Steps (in order)
1. Add the `submit_mode` field to `StartSession` — *why*: opt-in per session; default keeps AC1.
2. Add `AnswersReady` and its union member — *why*: the host reads `answers_ready` as the terminal message of a client-mode session.
3. Add the state and snapshot fields with `"server"` defaults — *why*: both models are `extra="forbid"` and old snapshots lack the key.
4. Write the tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    enumerate_options: bool | None = None' packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py)
# AFTER — insert below `    enumerate_options: bool | None = None` (verified: packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py:106)
    submit_mode: Literal["server", "client"] = "server"  # "client": review_confirm replies answers_ready, nothing is persisted

# occurrences: 1 (verified: grep -cF 'class SessionEnded(_Wire):' packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py)
# BEFORE — insert above `class SessionEnded(_Wire):` (verified: packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py:436), after FormComplete
class AnswersReady(_Wire):
    """Client-submit mode terminal message: validated answers for the host to submit (never logged, S8)."""

    type: Literal["answers_ready"] = "answers_ready"
    data: dict[str, Any]
    plausibility_summary: dict[str, Any] | None = None

# occurrences: 1 (verified: grep -cF '    FormComplete,' packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py)
# AFTER — insert below `    FormComplete,` inside WireMessage (verified: packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py:520)
    AnswersReady,
```
**Why**: spec §2.1 and Data Models verbatim. `AnswersReady` is defined before `WireMessage`, so the union resolves.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    protocol_version: int = 1' packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py)
# AFTER — insert below `    protocol_version: int = 1` (verified: packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py:315)
    submit_mode: Literal["server", "client"] = "server"
# FILL IN: add `Literal` to the typing import if absent — bounded by the existing import line (grep first)
# FILL IN: add a `submit_mode:` line to the Attributes docstring after the `protocol_version:` line (:288) — bounded by Google style
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    flagged: dict[str, int] = Field(default_factory=dict)' packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py)
# AFTER — insert below that line (verified: packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py:55)
    submit_mode: Literal["server", "client"] = "server"  # a resumed session keeps its mode (AC4)
# FILL IN: add `Literal` to the typing import if absent — bounded by the existing import block
```
**Why**: default `"server"` keeps pre-existing Redis snapshots valid.

### Tests
# FILL IN: add tests per the Test Specification to the three test files — bounded by AC1–AC5 of this task

### FILL IN checklist
- [ ] `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` / `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py`: `Literal` import present — bounded by not duplicating imports
- [ ] test bodies — bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `StartSession` parses with and without `submit_mode`; default `"server"`; a bad value is rejected (v2 `extra="forbid"` strictness unchanged)
- [ ] `AnswersReady(data={...}).to_wire()` has `type == "answers_ready"`, `data`, `plausibility_summary: None`; it is a `WireMessage` member
- [ ] `AudioSessionState()` and `AudioSnapshot` default `submit_mode` to `"server"`; a `"client"` snapshot round-trips through `model_dump(mode="json")`/`model_validate`
- [ ] Existing events/models/session_store tests pass unchanged (AC1)
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py -q`

---

## Test Specification

```python
def test_start_session_submit_mode_default():
    assert StartSession(type="start_session", form_uid="f").submit_mode == "server"

def test_answers_ready_wire():
    w = AnswersReady(data={"qty": 1}).to_wire()
    assert w == {"type": "answers_ready", "data": {"qty": 1}, "plausibility_summary": None}

def test_snapshot_keeps_submit_mode():
    # FILL IN: build an AudioSnapshot(submit_mode="client", ...) with the file's existing helper, round-trip it
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-client-submit --feature-id FEAT-656`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/audio-form-client-submit.json`. FEAT-653/654/655 touch the same files: land after them and rebase
   (spec §7); anchors below are by text, so re-run each `grep -c` before editing.
4. **Verify the Codebase Contract** before writing ANY code; if anything drifted, update the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4265 audio-form-client-submit verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential, no MCP coder seats)
**Date**: 2026-10-12
**Notes**: Added StartSession.submit_mode, AnswersReady (+WireMessage), state/snapshot fields. Mutation-checked (union member, default, snapshot field, state field). ruff not installed in venv: not run.

**Deviations from spec**: Spec example shows plausibility_summary:null on the wire; _Wire.to_wire uses exclude_none so the key is omitted when None (v1 parity). Tests assert omission.
