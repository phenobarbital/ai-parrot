# TASK-5693: Redact and bound hook-path text before it is persisted

**Feature**: FEAT-887 — SDD Experience Memory (`experience.pitfall`)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5595, TASK-5596
**Assigned-to**: unassigned
**Discovered-from**: `issue:5632e784dae7`, `issue:b6be8a0fe492`

---

## Context

Deferred review findings on FEAT-887 (filed by the worker's review stage, folded back into the
feature by `/sdd-fix` before it ships). The spec (§2, Data Models: "Text fields are redacted and
truncated to their limits BEFORE event_id is computed"; Implementation Notes: "Redact before
storing") requires every text field to be redacted and bounded *before* storage. The hook path —
`transitions.on_outcome` and its helpers `_append_event`, `_add_pending`, `_append_paired_lesson` —
never calls `fastpath.redact()` or truncates anything. Redaction happens only on ingestion
(`models.validate_event`), which is too late: the raw text is already on disk.

Reproduced: a bearer token / `GH_TOKEN=...` lands in clear text in `.parrot/experience/events.jsonl`
and in the session file; a ~7 KB stderr makes `append_event` drop the `failure.observed` event
(`MAX_EVENT_BYTES = 4096`) while the raw text still persists in the session's `pending` list; and the
session state (`pending`, `seen_observations`, `observation_aliases`, `command_occurrences`,
`advice_cooldowns`) grows without bound until `update_session` refuses the 64 KiB cap — after which
the hook silently stops pairing and advising for the rest of the session. Events are appended inside
the session mutation, so a refused session write still leaves its events behind.

---

## Scope

- Redact and truncate `command` and `error` once, at the top of `on_outcome`, to the spec limits
  (`command_example`/`fix_example` ≤ 300 chars, `error_excerpt`/`symptom` ≤ 400 chars,
  `error_signature` = `normalize_error(error)`, the same bounds `models._normalize_payload` applies
  on ingestion). Every write — events and session state — uses only the bounded values.
- Keep lesson identity stable: the paired lesson id must still equal
  `lesson_id_for(failure_signature(executable, subcommand, error))` computed from the *full* error,
  so store the normalized signature in the pending entry instead of re-deriving it from the excerpt.
- `failure.observed.error_signature` and the paired draft's `trigger.error_signature` carry the
  normalized signature (not the raw error).
- Keep session state bounded: trim `seen_observations`, `observation_aliases`,
  `command_occurrences`, expired `advice_cooldowns` and `injections` so a long session never reaches
  the session-file cap.
- Append events only after the session write succeeded (collect them during the mutation), so a
  refused session write leaves no orphan events.
- Tests: a `TOKEN=...`/`Authorization: Bearer ...` command plus a 5 KB error driven through
  `experience_hook.handle_post` asserting both the on-disk event and the session file are redacted
  and bounded; a long session (hundreds of distinct observations) stays under the cap and still
  produces advice.

**NOT in scope**: new redaction patterns (TASK-5697), config-driven limits (TASK-5696), the plane
resolution (TASK-5694), the matcher (TASK-5695).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` | MODIFY | redact/bound at the top of `on_outcome`; bounded session state; deferred event appends |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py` | MODIFY | redaction, truncation, identity and bounded-session tests |
| `packages/ai-parrot/tests/sdd/test_experience_hook.py` | MODIFY | end-to-end `handle_post` redaction/truncation test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.experience.fastpath import (  # fastpath.py:210, 193, 226, 240, 295, 88, 177
    redact, normalize_error, failure_signature, lesson_id_for, append_event, update_session, leading_command,
)
from parrot.sdd.scripts.experience_hook import handle_post  # experience_hook.py:225
```

### Existing Signatures to Use
```python
# knowledge/wiki/experience/transitions.py:49
def on_outcome(plane_dir: Path, *, session: str, command: str, outcome: CommandOutcome, seat: str,
               matcher: Callable[[str, str, str], Mapping[str, Any] | None]) -> str | None
# transitions.py:239
def _add_pending(state: dict, executable: str, subcommand: str, command: str, error: str, observation_id: str) -> None
# transitions.py:325
def _append_paired_lesson(plane_dir: Path, pending: Mapping[str, str], fix_command: str, session: str,
                          observation_id: str, seat: str) -> None
# transitions.py:387
def _append_event(plane_dir, kind, lesson_id, session, observation_id, seat, payload) -> None
# fastpath.py:88  — returns None when the serialized state exceeds _MAX_SESSION_BYTES (64 KiB)
def update_session(plane_dir: Path, session_key: str, mutate: Callable[[dict], dict], *, timeout_s: float = 1.0) -> dict | None
# models.py:297 — the ingestion bounds this task mirrors on the write side
def _normalize_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]
```

### Does NOT Exist
- No `truncate()`/`clip()` helper in `fastpath.py` — add a private one in `transitions.py`.
- `transitions.py` must stay stdlib-only (it is imported by the isolated hook); do not import
  `models.py` or pydantic from it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_experience_hook.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py#on_outcome",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py#_add_pending",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py#_append_paired_lesson",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py#_append_event",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py#update_session",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py#redact"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Stdlib-only module; never raise out of `on_outcome` (fail open).
- Duplicate-observation handling must not change: a replayed observation is still a no-op.
- Advice text is unchanged (it is built from published stubs, not from the failing command).

---

## Implementation Blueprint

### Steps (in order)
1. Add `_COMMAND_LIMIT = 300`, `_EXCERPT_LIMIT = 400` and a `_bounded(text, limit)` helper
   (`redact`, collapse whitespace, cut to `limit`).
2. In `on_outcome`, after the type checks: `safe_command`, `safe_error`, `signature = normalize_error(error)`.
3. Pass the bounded values to `failure.observed`, `_add_pending` (plus `error_signature`) and
   `_append_paired_lesson` (fix command bounded too).
4. Make `_append_event` write into a per-call buffer; flush the buffer with `append_event` after
   `update_session` returned a state.
5. Add `_bound_state(state)` and call it at the end of every mutation path.

### FILL IN checklist
- [ ] limits mirror `_normalize_payload`
- [ ] lesson id identity preserved for long errors
- [ ] no event written when the session write is refused

---

## Acceptance Criteria

- [ ] No secret-bearing value from the command or error reaches `events.jsonl` or the session file.
- [ ] Event and session text respect the spec limits; a 5 KB error still records `failure.observed`.
- [ ] A session with hundreds of distinct observations stays below the session cap and still pairs/advises.
- [ ] A refused session write appends no events.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_experience_hook.py -q`

---

## Test Specification

```python
def test_on_outcome_redacts_and_bounds_persisted_text(tmp_path): ...
def test_paired_lesson_identity_uses_full_error_signature(tmp_path): ...
def test_long_session_state_stays_bounded(tmp_path): ...
def test_refused_session_write_appends_no_events(tmp_path, monkeypatch): ...
def test_hook_post_failure_redacts_token_and_truncates_large_error(tmp_path): ...
```

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` § "Implementing a task by hand" inside
`.parrot/worktrees/feat-FEAT-887-sdd-experience-memory`.

---

## Completion Note

*(Agent fills this in when done)*
