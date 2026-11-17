# TASK-5731: Verify optional live plans require successful proof

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement M6 offline proof-policy and budget tests using existing harness APIs and synthetic evidence.

## Scope

- Implement M6 offline proof-policy and budget tests using existing harness APIs and synthetic evidence.
- Parameterize node outcomes and phases independently; absent or failed required proof never passes.
- Patch LLMFactory.create to capture budget identity across two answer clients and multiple fresh extraction clients.
- Keep this task test-only; report a verified generic-harness defect before expanding implementation scope.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py` | MODIFY | Regression coverage |
| `packages/ai-parrot-server/tests/unit/e2e/test_runner.py` | MODIFY | Regression coverage |
| `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py` | MODIFY | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
import pytest
from pathlib import Path
from parrot.e2e import live as e2e_live
from parrot.e2e.models import E2EPlan, ScenarioSpec, ScenarioResult, LiveBudget
from parrot.e2e.evidence import verify_evidence
```

### Dependency-created Imports

No unimplemented import is assumed before its dependency is complete.

### Existing Signatures to Use

- `sym:packages/ai-parrot-server/src/parrot/e2e/live.py#resolve_plan_budget` — `packages/ai-parrot-server/src/parrot/e2e/live.py:288`: `def resolve_plan_budget(env: Optional[Mapping[str, str]]=None) -> LiveBudget`
- `sym:packages/ai-parrot-server/src/parrot/e2e/live.py#require_live_opt_in` — `packages/ai-parrot-server/src/parrot/e2e/live.py:169`: `def require_live_opt_in(*, budget: Optional[LiveBudget]=None, env: Optional[Mapping[str, str]]=None) -> LiveOptIn`
- `sym:packages/ai-parrot-server/src/parrot/e2e/live.py#build_live_generation_budget` — `packages/ai-parrot-server/src/parrot/e2e/live.py:250`: `def build_live_generation_budget(opt_in: LiveOptIn, *, budget: Optional[LiveBudget]=None) -> 'GenerationBudget'`
- `sym:packages/ai-parrot-server/src/parrot/e2e/live.py#build_live_client` — `packages/ai-parrot-server/src/parrot/e2e/live.py:313`: `def build_live_client(opt_in: LiveOptIn, generation_budget: 'GenerationBudget') -> 'AbstractClient'`
- `sym:packages/ai-parrot-server/src/parrot/e2e/models.py#E2EPlan` — `packages/ai-parrot-server/src/parrot/e2e/models.py:227`: `class E2EPlan(_E2EBaseModel)`
- `sym:packages/ai-parrot-server/src/parrot/e2e/models.py#ScenarioSpec` — `packages/ai-parrot-server/src/parrot/e2e/models.py:164`: `class ScenarioSpec(_E2EBaseModel)`
- `sym:packages/ai-parrot-server/src/parrot/e2e/models.py#ScenarioResult` — `packages/ai-parrot-server/src/parrot/e2e/models.py:461`: `class ScenarioResult(_E2EBaseModel)`
- `sym:packages/ai-parrot-server/src/parrot/e2e/models.py#LiveBudget` — `packages/ai-parrot-server/src/parrot/e2e/models.py:120`: `class LiveBudget(_E2EBaseModel)`
- `sym:packages/ai-parrot-server/src/parrot/e2e/runner.py#_verdict_status` — `packages/ai-parrot-server/src/parrot/e2e/runner.py:347`: `def _verdict_status(plan: E2EPlan, results: list[ScenarioResult], cleanup_results: dict[str, bool], source_unchanged: bool, interrupted_exit: int | None) -> tuple[str, int, bool]`
- `sym:packages/ai-parrot-server/src/parrot/e2e/evidence.py#verify_evidence` — `packages/ai-parrot-server/src/parrot/e2e/evidence.py:502`: `async def verify_evidence(plan_path: Path, *, worktree: Path) -> VerificationResult`

### Does NOT Exist

- A plan alone does not instrument arbitrary BasicAgent clients; shared budget injection must be explicit.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_runner.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_evidence.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/e2e/live.py#resolve_plan_budget",
    "sym:packages/ai-parrot-server/src/parrot/e2e/live.py#require_live_opt_in",
    "sym:packages/ai-parrot-server/src/parrot/e2e/live.py#build_live_generation_budget",
    "sym:packages/ai-parrot-server/src/parrot/e2e/live.py#build_live_client",
    "sym:packages/ai-parrot-server/src/parrot/e2e/models.py#E2EPlan",
    "sym:packages/ai-parrot-server/src/parrot/e2e/models.py#ScenarioSpec",
    "sym:packages/ai-parrot-server/src/parrot/e2e/models.py#ScenarioResult",
    "sym:packages/ai-parrot-server/src/parrot/e2e/models.py#LiveBudget",
    "sym:packages/ai-parrot-server/src/parrot/e2e/runner.py#_verdict_status",
    "sym:packages/ai-parrot-server/src/parrot/e2e/evidence.py#verify_evidence"
  ]
}
```

## Implementation Notes

Independent test-only work against existing E2EPlan, ScenarioSpec and live helpers.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py` (MODIFY)

```python
# Anchor: class TestRequireLiveOptIn:
# occurrences: 1; grep -F -c verified at packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py:57
# INSERT new tests at module scope before this definition; preserve it.
def test_shared_budget_covers_sessions_and_extraction() -> None:
    """All answer and extraction clients receive the same generation budget."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

def test_missing_prerequisites_prevent_all_client_construction() -> None:
    """Opt-in validation fails before any real client construction."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Preserve existing regressions while adding focused behavior checks.

### `packages/ai-parrot-server/tests/unit/e2e/test_runner.py` (MODIFY)

```python
# Anchor: def test_required_missing_or_blocked_coverage_is_blocked() -> None:
# occurrences: 1; grep -F -c verified at packages/ai-parrot-server/tests/unit/e2e/test_runner.py:44
# INSERT new tests at module scope before this definition; preserve it.
def test_optional_live_plan_requires_successful_proof() -> None:
    """Optional plans reject missing/skipped/failed required live nodes."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Preserve existing regressions while adding focused behavior checks.

### `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py` (MODIFY)

```python
# Anchor: async def test_verify_evidence_policy_none_returns_pass_without_touching_evidence(git_worktree: Path) -> None:
# occurrences: 1; grep -F -c verified at packages/ai-parrot-server/tests/unit/e2e/test_evidence.py:221
# INSERT module-level test; reuse git_worktree, _write_plan, _seed_matching_evidence.
async def test_optional_live_plan_requires_successful_proof(git_worktree: Path) -> None:
    """Reject unsuccessful required live evidence under optional plan policy."""
    # FILL IN: parameterize missing/skipped/failed/passed nodes and setup/call/teardown failures.
    # Use policy="optional", tier="live", required=True, empty targets and matching identities.
    # Invoke real verify_evidence; forged aggregate PASS cannot mask bad required phase evidence.
    raise NotImplementedError
```

**Why**: Synthetic evidence isolates proof policy without provider or Redis dependencies.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot-server/tests/unit/e2e/test_runner.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: Optional plan plus required live scenario validates; runner/verifier accept only complete successful proof.
- [ ] **AC-2**: A forged aggregate PASS cannot mask failed setup/call/teardown; missing/skipped required nodes fail proof.
- [ ] **AC-3**: Every constructed client receives the same budget object; invalid opt-in constructs none.
- [ ] **AC-4**: Tests remain offline and touch only temp repositories and doubles.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py packages/ai-parrot-server/tests/unit/e2e/test_runner.py packages/ai-parrot-server/tests/unit/e2e/test_evidence.py -q`

## Test Specification

Use named blueprint cases as the acceptance matrix. Cover the adversarial boundaries in Scope/ACs and preserve existing regressions.

## Agent Instructions

1. Use the host session and feature worktree provisioned by `parrot sdd worktree ensure --slug user-memory-recall-e2e --feature-id FEAT-904`; never implement on dev.
2. Read the spec and confirm every dependency is done in `sdd/tasks/index/user-memory-recall-e2e.json`.
3. Re-verify contracts and use sdd-start lifecycle; never silently expand target files.
4. Activate the shared venv and set PYTHONPATH=packages/ai-parrot/src for worktree tests; never uv sync there.
5. Run scoped validation and applicable lint; retain logs in artifacts/logs/.
6. Commit implementation, then use parrot sdd task finalize with real TaskCompletionEvidence and exact implementation HEAD.
7. Inspect generated Completion Note and active-to-completed move; commit only task SDD state. Do not hand-edit completion state or push from the worker.

## Completion Note

Pending; the task finalizer generates this after implementation and validation.


## Completion Note

Implemented by native sonnet seat, 1 attempt. Tests only. Task-tier validation first failed on a wrong "missing" expectation in test_runner.py (coder fixed it; engine re-committed on second merge). Merge-tier: 82 passed. Deferred finding: issue:23db163eea94 (runner._verdict_status lacks check_phases=True).
