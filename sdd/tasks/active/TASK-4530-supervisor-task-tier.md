# TASK-4530: `ValidationSupervisor` task tier, per-runner deadlines and persisted verdict

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4529
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, codex S1 (verdict is a first-class supervisor receipt, persisted via
`ExecutionEvidenceStore.put_artifact` before it is returned) and S9 (per-invocation timeouts under an overall
cap; only unfinished invocations are `timed_out`; a partial run never writes the green cache).

---

## Scope

- `start(...)`: accept `tier="task"` — exactly one task id, explicit `base_ref` (fork SHA) and `attempt_uid`; plan declared ∪ mirror only (no contract, no green cache).
- Run each invocation with the adapter's `cwd`, report path and `registry.timeout_for(kind)`, bounded by the remaining overall `timeout_seconds`; parse with `adapter.parse_report`.
- Build the verdict with `build_verdict`, persist with `put_artifact`, attach its `EvidenceRef` id in `verdict.evidence`, then settle the receipt.
- Add `wait_verdict(execution_id, handle, timeout_s) -> ValidationVerdict`.
- `backend` label `"validation-subprocess"`; `record_green` only on a complete run and only for pytest reports.
- Add the §4 integration test `test_merge_tier_includes_vitest_runner` (fake adapter subprocess via a stub script).

**NOT in scope**: Engine gate (TASK-4532); `coder_run_validation` tier literal (TASK-4532).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | task tier + deadlines + verdict |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py` | CREATE | task tier tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | MODIFY | backend label + deadline regressions |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.verdict import build_verdict, verdict_to_json  # TASK-4529
from parrot.flows.dev_loop.test_scope.runners.registry import load_registry  # TASK-4521
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore  # evidence.py:154
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")         # line 76
_DEFAULT_BASE_REF = "origin/dev"                     # line 86
class ValidationSupervisor:                          # line 442
    async def start(self, *, feature, worktree, execution_id, task_ids, tier: Literal["merge","feature"], timeout_seconds, request_id, base_ref=None, index_path=None) -> BackgroundRegistration   # line 493
    #   line 505: `if tier not in ("merge", "feature"):`
    #   line ~575: backend="pytest-subprocess",
    #   line 631/636: first invocation argv + asyncio.create_subprocess_exec
    async def _plan_selection(...)                   # line 753
    async def _supervise(...)                        # line 868 — one deadline for all chained invocations (S9)
    def _argv_with_junit(...)                        # line 1021 (switched to with_report by TASK-4523)
    async def _record_test_results(...)              # line 1034
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py
class ExecutionEvidenceStore:                        # line 154
    async def put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef   # line 170 — takes a Pydantic model
```

### Does NOT Exist
- ~~`start(tier="task")`, `wait_verdict`, `attempt_uid` kwarg~~ — added here
- ~~a Pydantic verdict model~~ — `ValidationVerdictModel` lands in TASK-4531; HERE wrap the JSON in a minimal local `BaseModel` (`_VerdictArtifact(payload: dict)`) for `put_artifact`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor.start",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._plan_selection",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._supervise",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._record_test_results",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py#ExecutionEvidenceStore.put_artifact"
  ]
}
```

---

## Implementation Notes

- The task tier must NOT be part of `_payload_hash` differently: include `tier` (already) and `attempt_uid` so two attempts never share a handle.
- Every kernel call via `asyncio.to_thread`; subprocesses via `asyncio.create_subprocess_exec(cwd=worktree / invocation.cwd)`.
- Tests need the hermetic-root fixture from `tests/flows/dev_loop/sdd_coder/conftest.py` (memory: sdd-coder evidence store always-on).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Admission for `task` — *why*: one id + explicit base.
2. Per-invocation deadlines — *why*: S9.
3. Verdict build + persist + receipt — *why*: S1.
4. `wait_verdict` — *why*: gate and capability block on it.
5. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if tier not in ("merge", "feature"):' …/background.py)
# REPLACE the tier check (background.py:505-506) with:
        if tier not in ("task", "merge", "feature"):
            raise ValueError(f"tier must be 'task', 'merge' or 'feature', got {tier!r}")
        if tier == "task":
            if len(task_ids) != 1:
                raise ValueError("tier='task' admits exactly one task id")
            if not base_ref or not attempt_uid:
                raise ValueError("tier='task' requires an explicit base_ref (fork SHA) and attempt_uid")

# occurrences: 1 (verified: grep -c '            backend="pytest-subprocess",' …/background.py)
            backend="validation-subprocess",

# NEW public method on ValidationSupervisor:
    async def wait_verdict(self, execution_id: str, handle: str, timeout_s: float) -> "ValidationVerdict":
        """Block until ``handle`` settles; return the persisted verdict (status "timed_out" on deadline)."""
        # FILL IN: reuse self.wait(...) then load the verdict artifact linked from the receipt
```
**Why**: Signature additions follow spec §3 M6 exactly (`attempt_uid: Optional[str] = None` kwarg on `start`).

### FILL IN checklist
- [ ] `start` kwargs + task-tier planning path
- [ ] per-invocation timeout loop in `_supervise`
- [ ] verdict persistence + receipt link
- [ ] `wait_verdict`
- [ ] pytest-only `record_green` on complete runs
- [ ] tests incl. `test_merge_tier_includes_vitest_runner`

---

## Acceptance Criteria

- [ ] `tier="task"` with two ids or without base_ref/attempt_uid ⇒ `ValueError` before any spawn.
- [ ] A slow first invocation times out alone; the second still runs within the overall cap; verdict `timed_out`, finished evidence kept, no green cache write.
- [ ] `put_artifact` is awaited before the receipt settles; `wait_verdict` returns the stored verdict.
- [ ] Merge tier with a contract vitest block runs a `vitest:admin-ui` invocation.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4530 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
