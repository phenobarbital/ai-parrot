# TASK-4531: Pydantic verdict models, `validation_failed` outcome, brief fields and repair worktree base

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4529
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (models half) and codex S8. Adds the boundary models the engine and toolkit return,
the `validation_failed` outcome, the rendered-verdict fields on both briefs, `RunnerConfig`, and
`SubWorktreeManager.create(base=…)` so the same-seat repair starts from the failed attempt's branch.

---

## Scope

- `sdd_coder/models.py`: `TaskOutcome` + `"validation_failed"`; `FailureModel`, `RunnerSummaryModel`, `ValidationVerdictModel.from_kernel`; `RunnerConfig(gate_overall_timeout_s=600, same_seat_repair=True)` on `RosterConfig.runners`; `TaskResult.validation`; `NativePrep.validation_verdict`; `AttemptRecord.validation_status: str = ""`.
- `models/base.py`: `TaskScopedBrief.validation_verdict: str = ""` with a description.
- `worktree_manager.py`: `create(self, worker_id, *, base=None)` — `base` replaces `self.feature_branch` as the start point.

**NOT in scope**: Engine use of these (TASK-4532); toolkit literal (TASK-4532).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | models + outcome + config |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | TaskScopedBrief.validation_verdict |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` | MODIFY | create(base=…) |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | MODIFY | model tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py` | MODIFY | base= test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.datatypes import ValidationVerdict  # TASK-4520 (stdlib type; import inside from_kernel)
from pydantic import BaseModel, Field  # already imported in sdd_coder/models.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
TaskOutcome = Literal["queued","running","merged","merge_conflict","failed","fidelity_violation","retry_native","not_dispatched"]  # line 30
class RosterConfig(BaseModel):   # line 219 — lint: LintConfig (:225), feedback: FeedbackConfig (:226)
class AttemptRecord(BaseModel):  # line 312 — attempt: int = Field(..., ge=1, le=3)
class TaskResult(BaseModel):     # line 359 — … lint, native_retry
class NativePrep(BaseModel):     # line 376 — … coder_feedback: str = "" …
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class TaskScopedBrief(BaseModel):  # line 478 — research, task_id, coder_feedback (:488), task_file
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
class SubWorktreeManager:
    async def create(self, worker_id: str) -> str:   # line 143
    #   line ~165: "worktree", "add", "-b", branch, path, self.feature_branch, cwd=self.base_worktree
```

### Does NOT Exist
- ~~`TaskOutcome "validation_failed"`~~, ~~`TaskResult.validation`~~, ~~`RunnerConfig`~~ — added here
- ~~`SubWorktreeManager.create(base=…)`~~ — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#TaskResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#AttemptRecord",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#TaskScopedBrief",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py#SubWorktreeManager.create"
  ]
}
```

---

## Implementation Notes

- `from_kernel` imports the kernel type lazily (Pydantic side may import stdlib kernel; never the reverse).
- Every new field defaulted so existing JSON round-trips (`extra="forbid"` models!) keep validating.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Models — *why*: engine/toolkit return them.
2. Brief fields — *why*: verdict reaches the repair prompt.
3. `create(base=)` — *why*: S8.
4. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def create(self, worker_id: str) -> str:' …/worktree_manager.py)
# REPLACE the signature (worktree_manager.py:143) with:
    async def create(self, worker_id: str, *, base: Optional[str] = None) -> str:
# and in the `git worktree add` call (~line 165) replace `self.feature_branch` with `base or self.feature_branch`.
# FILL IN: docstring Args entry for `base` ("start point; defaults to the feature branch — FEAT-709 repair attempts")
```
**Why**: Default keeps every existing caller unchanged.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'TaskOutcome = Literal[' …/sdd_coder/models.py)
# add "validation_failed" as the last member of TaskOutcome (models.py:30-39)

class FailureModel(BaseModel):
    runner: str
    nodeid: str
    verdict: Literal["new_red", "baseline_red", "unknown"]
    excerpt: str


class RunnerSummaryModel(BaseModel):
    runner: str
    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    cached: int
    duration_s: float
    exit_code: int
    status: str


class ValidationVerdictModel(BaseModel):
    """Pydantic mirror of the kernel ValidationVerdict (FEAT-709)."""

    schema_version: int = Field(alias="schema")
    status: Literal["passed", "failed", "timed_out", "unavailable", "blocked"]
    tier: Literal["task", "merge", "feature"]
    runners: List[RunnerSummaryModel] = Field(default_factory=list)
    failures: List[FailureModel] = Field(default_factory=list)
    cached: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)

    @classmethod
    def from_kernel(cls, verdict: "ValidationVerdict") -> "ValidationVerdictModel":
        # FILL IN: via test_scope.verdict.verdict_to_json(verdict) then model_validate
        raise NotImplementedError


class RunnerConfig(BaseModel):
    gate_overall_timeout_s: int = Field(default=600, ge=1, le=7200)
    same_seat_repair: bool = True
```
**Why**: `schema` is a BaseModel attribute name — use `schema_version` with alias `schema` and `populate_by_name=True` (FILL IN model_config).

### FILL IN checklist
- [ ] `from_kernel`
- [ ] `model_config` populate_by_name
- [ ] `RosterConfig.runners`, `TaskResult.validation`, `NativePrep.validation_verdict`, `AttemptRecord.validation_status`
- [ ] `TaskScopedBrief.validation_verdict`
- [ ] tests

---

## Acceptance Criteria

- [ ] Existing model tests pass unchanged.
- [ ] `ValidationVerdictModel.from_kernel` round-trips a kernel verdict.
- [ ] `create(worker, base=<branch>)` forks from that branch (test via `git merge-base`).
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4531 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
