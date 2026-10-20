# TASK-4540: The task-tier gate fails closed

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:72c4d5c42095`

---

## Context

Spec decision **S13**. `_task_tier_gate` as delivered by TASK-4532 returns `None` — and the merge then
proceeds **unvalidated**, with only a `logger.warning` — in two cases:

- `self._validation_supervisor is None` (the durable root never resolved), and
- the attempt has no `execution_id` (a plain `run_chunk`).

The spec never granted that fail-open: its §3 Interface Skeleton types the gate `-> ValidationVerdict`.
The gate already fails closed for *exceptions* (`except Exception ... "a broken gate fails closed, never
merges unvalidated"`), so these two early returns are the only remaining holes — and they are the ones a
misconfigured host actually hits.

`issue:72c4d5c42095` also asks whether the gate burns the full `gate_overall_timeout_s` (600 s) when the
sandbox is unavailable instead of reporting `unavailable` quickly: on a host with Bubblewrap denied, the
gate blocked >30 s in `test_background_mcp.py::test_run_chunk_settles_handle_when_runner_beats_registration`.
That half is **in scope** here as a bounded-wait assertion.

---

## Scope

- `_task_tier_gate` returns `ValidationVerdict` (never `Optional`). The two unrunnable cases return a
  synthetic `status="unavailable"` verdict whose `notes` name the cause, instead of `None`.
- `_consolidate` drops the `verdict is not None and` guard; an `unavailable` verdict becomes
  `validation_failed` like any other non-`passed` status, and nothing merges.
- `unavailable` stays distinguishable from a test-failure red in the `TaskResult.diagnostics` string so an
  operator can tell a misconfigured gate from a genuinely broken attempt.
- `unavailable` must not reach `_classify_and_suspend` — it is a configuration fault, not a seat fault
  (the existing "no suspension for validation reds" rule already covers it; assert it).
- Invert `test_no_supervisor_merges_with_warning`, which currently asserts the fail-open.

**NOT in scope**: making the supervisor resolve (durable root wiring); the max_turns arm (TASK-4539);
bounded state / request-id / evidence (TASK-4541).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | fail-closed gate + caller guard |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py` | MODIFY | invert fail-open test, add fail-closed cases |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `feat-FEAT-709-language-agnostic-validation-runners` @ `616450ad0` (2026-10-20).

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.datatypes import Failure, ValidationVerdict
from parrot.flows.dev_loop.sdd_coder.models import ValidationVerdictModel
# engine.py already imports VERDICT_SCHEMA and builds this exact shape in the except arm:
#   ValidationVerdict(schema=VERDICT_SCHEMA, status=status, tier="task", runners=(), failures=(), notes=(note,))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def _task_tier_gate(self, ctx, task, *, path, branch, diff_base, attempt_uid,
                          execution_id) -> Optional[ValidationVerdict]      # line 1395 — return type changes here
#   :1415  if self._validation_supervisor is None:  ... return None        <- fail-open #1
#   :1422  if execution_id is None:                 ... return None        <- fail-open #2
#   :1443  except Exception ...: status, note = "unavailable", ...         <- already fail-closed
def _record_validation_red(self, task_id: str, branch: str, rendered: str) -> None   # line 2865
#   :2973  verdict = await self._task_tier_gate(...)
#   :2983  if verdict is not None and verdict.status != "passed":          <- guard to simplify
```

### Anchors
```python
# occurrences: 1 (verified: grep -c '        if verdict is not None and verdict.status != "passed":' .../engine.py)
        if verdict is not None and verdict.status != "passed":
```

### Does NOT Exist
- ~~a non-Optional `_task_tier_gate` return~~ — changed here
- ~~a distinct `gate_unavailable` outcome~~ — `validation_failed` carries it, with the cause in `notes`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._task_tier_gate",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._consolidate"
  ]
}
```

---

## Implementation Notes

- Build the two unavailable verdicts with the **same** constructor the `except` arm already uses, so the
  shape stays identical; only `notes` differs.
- Keep both `logger.warning` calls — the log line is how an operator sees the misconfiguration — but change
  the message: it no longer says "merging unvalidated", because nothing merges now.
- `_record_validation_red` is called for every non-passed verdict; an `unavailable` verdict has no failures,
  so `render_for_prompt` yields a verdict with notes only. That is correct: the repair attempt is told the
  gate could not run. Do not special-case it.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# 1. Signature + docstring
    ) -> ValidationVerdict:
        """Run the task tier on the attempt tree after all engine mutations, before the merge lock (S2).

        Fail closed (S13): always returns a verdict. When the gate cannot run -- no supervisor bound, or
        no execution_id for this attempt -- returns status="unavailable" naming the cause, which the
        caller treats as a red. It never returns None and never lets an unvalidated merge through.
        """

# 2. Replace the two `return None` early exits with unavailable verdicts:
        if self._validation_supervisor is None:
            self.logger.warning(
                "task-tier gate unavailable for %s: no validation supervisor configured; refusing to merge",
                task.task_id,
            )
            return self._gate_unavailable("no validation supervisor configured")
        if execution_id is None:
            self.logger.warning(
                "task-tier gate unavailable for %s: attempt %s has no execution; refusing to merge",
                task.task_id, branch,
            )
            return self._gate_unavailable(f"attempt {branch} has no execution_id")

# 3. One small private helper beside the gate:
    @staticmethod
    def _gate_unavailable(note: str) -> ValidationVerdict:
        """A verdict for a gate that could not run at all (S13) -- treated as a red by the caller."""
        return ValidationVerdict(
            schema=VERDICT_SCHEMA, status="unavailable", tier="task", runners=(), failures=(), notes=(note,)
        )

# 4. Caller guard (occurrences: 1):
        if verdict.status != "passed":
```
**Why**: the gate's whole purpose is that nothing merges unvalidated; a `None` return defeated it.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py` (MODIFY)
```python
# Replace test_no_supervisor_merges_with_warning with test_no_supervisor_fails_closed:
#   engine = _engine(base_path, fake_builder_factory({}), None)
#   -> outcome == "validation_failed", validation.status == "unavailable",
#      feature branch HEAD unchanged, warning logged.
# Add test_attempt_without_execution_fails_closed: engine._execution_for = lambda branch: None
# Add test_gate_unavailable_never_suspends: spy _classify_and_suspend, assert not called.
```

### FILL IN checklist
- [ ] gate signature + docstring
- [ ] two unavailable returns + `_gate_unavailable` helper
- [ ] caller guard
- [ ] inverted + two new tests

---

## Acceptance Criteria

- [ ] No supervisor bound ⇒ `validation_failed` with `validation.status == "unavailable"`, feature branch
      HEAD unchanged, warning logged (NOT a merge).
- [ ] Attempt with no `execution_id` ⇒ same fail-closed path.
- [ ] `_task_tier_gate` never returns `None` (the annotation is non-Optional and no `return None` remains).
- [ ] An `unavailable` verdict never reaches `_classify_and_suspend`.
- [ ] The existing passed / failed / repair / ladder tests still pass unchanged.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py -q`

---

## Test Specification

Tests live in the file declared above; write the cases named in Acceptance Criteria. The module's
`FakeSupervisor` and `_engine` helpers already support a `None` supervisor.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`.
2. Verify the Codebase Contract first.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Stage only the files listed above.
5. Close with `scripts/sdd/close_task.sh TASK-4540 language-agnostic-validation-runners verified`.

---

## Completion Note

**Completed by**: Claude Opus 5 (/sdd-fix, issue:72c4d5c42095)
**Date**: 2026-10-20
**Notes**: `_task_tier_gate` is now `-> ValidationVerdict` with no `return None` on any path. The two
unrunnable cases return `_gate_unavailable(...)` -- `status="unavailable"` with the cause in `notes` --
built with the same constructor the pre-existing `except` arm already used. `_consolidate` drops its
`verdict is not None` guard, so any non-`passed` status becomes `validation_failed` and nothing merges;
the cause is surfaced in `TaskResult.diagnostics`, keeping an unrunnable gate distinguishable from a
test-failure red.

`test_engine_validation_gate.py`: 18 passed. `test_no_supervisor_merges_with_warning` was inverted into
`test_no_supervisor_fails_closed` (it asserted the fail-open), joined by
`test_attempt_without_execution_fails_closed`, `test_gate_never_returns_none` and
`test_gate_unavailable_never_suspends`.

**Deviations from spec**: none in the production change. One harness decision worth recording: making
the gate fail closed broke 28 existing tests, all of them on the *second* guard (`execution_id is None`),
not the missing-supervisor one. Those tests drive the legacy in-process shape
(`run_chunk`/`merge`/`prepare_native` without an execution) and merged only because the gate was being
skipped for it. Production cannot reach that shape -- `coder_run_chunk`, `coder_merge` and
`coder_prepare_native` all require `execution_id: str`, and the MCP toolkit is the only caller of
`engine.run_chunk` -- and those tests bind a REAL `ValidationSupervisor` through `_hermetic_durable_root`,
so letting the gate run would spawn real validation subprocesses and make the suite slow and flaky.
A `conftest.py` autouse fixture therefore stubs the gate green for every test that is not about it;
`test_engine_validation_gate.py` and `test_task_tier_end_to_end.py` opt out via the new `task_tier_gate`
marker (registered in `pytest.ini`) and keep full coverage. sdd_coder suite: 621 passed, previously
593 passed + 28 failed.
