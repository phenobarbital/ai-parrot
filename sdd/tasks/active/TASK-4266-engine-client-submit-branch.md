# TASK-4266: Engine — v2 guard, client branch emitting AnswersReady, resume keeps submit_mode

**Feature**: FEAT-656 — Audio form client-submit mode (voice collects, the host submits)
**Spec**: `sdd/specs/audio-form-client-submit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4265
**Assigned-to**: unassigned

---

## Context

Spec §2.1 (guard), §2.3 (engine) / M2. The engine stays pure: `on_review_confirm` still emits `Submit`; only `on_submit_done` gains a branch, and `on_start`/snapshot/`_resume` carry the mode.

---

## Scope

- `on_start`: reject `submit_mode == "client"` with `protocol_version < 2` via `Error(code="INVALID_MESSAGE", message="submit_mode client requires protocol v2")` (AC5), BEFORE any state change; otherwise store `state.submit_mode`. Apply the same guard on the resume path.
- `on_submit_done`: when `outcome` carries `client_data`, emit `AnswersReady(data=outcome["client_data"], plausibility_summary=...)`, set `completed=True`, `phase=COMPLETE`. The `errors` branch is untouched and shared (AC3). The server `FormComplete` branch is untouched.
- `snapshot()` writes `submit_mode`; `_resume` restores it from the snapshot (AC4).
- Tests in `test_audio_engine_review_resume.py`.

**NOT in scope**: the adapter validate-only path and `attach_verdicts` (TASK-4267); docs (TASK-4268).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | guard, state, client branch in `on_submit_done`, snapshot/resume |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py` | MODIFY | engine client-mode tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-10-12 (`grep -c` re-run at tasking time). Use VERBATIM; verify anything not listed.

### Verified Imports
```python
# engine imports its wire models in one block (FormComplete at packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py:35, SubmitDone at :65)
from .events import AnswersReady   # created by TASK-4265 — add to that existing import block (grep the block first)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py
class AudioFormSession:
    def on_start(self, ev: StartSession) -> list[Outbound]            # :169 ; sets state.locale (:175) / protocol_version (:176)
    def on_review_confirm(self, ev: ReviewConfirm) -> list[Outbound]  # :905 — unchanged
    def _submit(self) -> list[Outbound]                               # :925 — emits Submit(data, context); unchanged
    def on_submit_done(self, ev: SubmitDone) -> list[Outbound]        # :1100 ; `        if not errors:` at :1108 is the success branch
    def snapshot(self) -> AudioSnapshot                               # :977 ; builds AudioSnapshot(... user_id=self.state.user_id, tenant=self.state.tenant)
    def _resume(self, ev: StartSession) -> list[Outbound]             # :1049 ; restores locale/protocol_version at :1083-1084
# SubmitDone.outcome: dict — {"errors": {...}} | {"submission_id":..., "stored_in":...} | (new) {"client_data": {...}, "plausibility_summary"?: ...}
```

### Does NOT Exist
- ~~`Phase.CLIENT_SUBMIT` / a new phase~~ — client mode reuses SUBMITTING then COMPLETE.
- ~~a second Submit-like IORequest~~ — `Submit` is reused; the adapter decides by `state.submit_mode`.
- ~~`outcome["plausibility_summary"]` today~~ — optional new key; engine must tolerate it being absent (use `.get`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#SubmitDone",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#FormComplete"
  ]
}
```

---

## Implementation Blueprint

> Executor-ready starting point: write each block nearly verbatim, complete every `# FILL IN:`. Never change a
> signature, class name or path the blueprint fixes.

### Steps (in order)
1. Add the v2 guard + state assignment in `on_start` — *why*: AC5, and a rejected start must leave the session IDLE.
2. Add the `client_data` branch to `on_submit_done` ahead of the `FormComplete` return — *why*: AC2; keeps the errors branch shared (AC3).
3. Write `submit_mode` in `snapshot()` and restore it in `_resume` — *why*: AC4.
4. Write the tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -cF '        self.state.locale = ev.locale' packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py) — lines :175 (on_start) and :1083 (_resume)
# FILL IN: disambiguate — quote enough surrounding context (2–3 lines) to make the anchor unique
# on_start, BEFORE `self.state.locale = ev.locale` (:175), after the `if ev.resume_session_id: return self._resume(ev)` lines:
        if ev.submit_mode == "client" and ev.protocol_version < 2:
            return [Error(code="INVALID_MESSAGE", message="submit_mode client requires protocol v2")]
# on_start, AFTER `self.state.protocol_version = ev.protocol_version` (first occurrence, :176):
        self.state.submit_mode = ev.submit_mode
# _resume: the same guard at the TOP of `_resume` (before `_check_resume`), and AFTER `self.state.protocol_version = ev.protocol_version` (second occurrence, :1084):
        self.state.submit_mode = snap.submit_mode   # the saved mode wins; the resuming start_session cannot change it
# FILL IN: decide whether a resume StartSession whose submit_mode differs from snap.submit_mode errors or is ignored — bounded by AC4 (saved mode wins; do not raise)

# occurrences: 1 (verified: grep -cF '        if not errors:' packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py) — anchor line :1108
# AFTER — insert ABOVE `        if not errors:` (:1108):
        client_data = outcome.get("client_data")
        if client_data is not None and not errors:
            self.state.completed = True
            self.state.phase = Phase.COMPLETE
            return [AnswersReady(data=dict(client_data), plausibility_summary=outcome.get("plausibility_summary"))]

# occurrences: 1 (verified: grep -cF '            tenant=self.state.tenant,' packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py) — anchor :1010 inside snapshot()
# AFTER — insert below it:
            submit_mode=self.state.submit_mode,
```
**Why**: the guard sits before any mutation so an INVALID_MESSAGE start can be retried; `client_data` is checked first so the success path keeps working untouched for server mode. Do not touch `on_review_confirm`/`_submit`.

### Tests (`packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py`)
# FILL IN: reuse `_make`, `_start`, `_answer_all`, `_types` from the file — bounded by the Test Specification below

### FILL IN checklist
- [ ] `on_start` guard placement — bounded by AC5 (no state mutation on rejection)
- [ ] resume-with-different-submit_mode behaviour — bounded by AC4
- [ ] test bodies — bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `StartSession(submit_mode="client", protocol_version=1)` → exactly one `Error(INVALID_MESSAGE)`, phase stays IDLE (AC5)
- [ ] `on_submit_done(SubmitDone(outcome={"client_data": {...}}))` → `[AnswersReady]`, `completed is True`, phase COMPLETE (AC2)
- [ ] `outcome={"errors": {...}}` in client mode → `ValidationErrors` + re-ask of the first failing field, identical to server mode (AC3)
- [ ] snapshot → `from_snapshot` → resume preserves `submit_mode == "client"` (AC4)
- [ ] Existing engine tests pass unchanged (AC1)
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`

---

## Test Specification

```python
def test_client_mode_requires_v2():
    s = _make(); out = s.handle(StartSession(type="start_session", form_uid="f", submit_mode="client", protocol_version=1))
    assert [type(o).__name__ for o in out] == ["Error"] and out[0].code == "INVALID_MESSAGE"

def test_client_data_emits_answers_ready_and_completes():
    # FILL IN: drive to SUBMITTING with _answer_all + review_confirm, then feed SubmitDone(outcome={"client_data": {"a": 1}})
    ...

def test_resume_keeps_submit_mode():
    # FILL IN: snapshot a client-mode session, from_snapshot + _start(resume=...), assert s.state.submit_mode == "client"
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4266 audio-form-client-submit verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
