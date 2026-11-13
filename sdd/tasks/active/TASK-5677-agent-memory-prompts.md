# TASK-5677: Coder source and packaged prompt evidence contract

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-5676
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes DevelopmentOutput.checked_patterns and verified review API from TASK-5676

## Context

Implement the bounded M5 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Checked evidence and structured citations (`.claude/agents/sdd-coder.md`).
- Verified review guidance including zero-fix deliveries (`.claude/agents/sdd-worker.md`).
- Packaged coder parity (`packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md`).
- Packaged worker parity (`packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`).
- Packaged/source parity and structured evidence guidance (`packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-coder.md` | MODIFY | Checked evidence and structured citations |
| `.claude/agents/sdd-worker.md` | MODIFY | Verified review guidance including zero-fix deliveries |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md` | MODIFY | Packaged coder parity |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | Packaged worker parity |
| `packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py` | CREATE | Packaged/source parity and structured evidence guidance |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
import pytest
```

### Existing Signatures and Anchors

- `.claude/agents/sdd-coder.md:126`: `### a.1) Apply Previous Delivery Feedback` (exact-line occurrence count 1).
- `.claude/agents/sdd-worker.md:495`: `**Measure every reviewed delivery**, even if no fixes were needed: call `coder_record_review(feature, worktree,` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md:126`: `### a.1) Apply Previous Delivery Feedback` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:495`: `**Measure every reviewed delivery**, even if no fixes were needed: call `coder_record_review(feature, worktree,` (exact-line occurrence count 1).

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/agents/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `.claude/agents/sdd-coder.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -F -x -c -- '### a.1) Apply Previous Delivery Feedback' .claude/agents/sdd-coder.md)
# MODIFY anchor at .claude/agents/sdd-coder.md:126: ### a.1) Apply Previous Delivery Feedback
Require checked_patterns to reference actually delivered versions and engine-verifiable checks.
Keep citations in the structured channel; do not render them into the user-visible answer.
An independently verified zero-fix delivery may be successful without a fabricated fix commit.
Keep coder_record_feedback, coder_record_review, execution_id and review_ref contracts intact.
Do not convert experience.pitfall lessons or cohort statistics into trusted per-memory outcomes.
```

**Why:** Installed and source prompts must agree so coder deliveries use the same evidence schema on every machine.

### `.claude/agents/sdd-worker.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -F -x -c -- '**Measure every reviewed delivery**, even if no fixes were needed: call `coder_record_review(feature, worktree,' .claude/agents/sdd-worker.md)
# MODIFY anchor at .claude/agents/sdd-worker.md:495: **Measure every reviewed delivery**, even if no fixes were needed: call `coder_record_review(feature, worktree,
Require checked_patterns to reference actually delivered versions and engine-verifiable checks.
Keep citations in the structured channel; do not render them into the user-visible answer.
An independently verified zero-fix delivery may be successful without a fabricated fix commit.
Keep coder_record_feedback, coder_record_review, execution_id and review_ref contracts intact.
Do not convert experience.pitfall lessons or cohort statistics into trusted per-memory outcomes.
```

**Why:** Installed and source prompts must agree so coder deliveries use the same evidence schema on every machine.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -F -x -c -- '### a.1) Apply Previous Delivery Feedback' packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md)
# MODIFY anchor at packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md:126: ### a.1) Apply Previous Delivery Feedback
Require checked_patterns to reference actually delivered versions and engine-verifiable checks.
Keep citations in the structured channel; do not render them into the user-visible answer.
An independently verified zero-fix delivery may be successful without a fabricated fix commit.
Keep coder_record_feedback, coder_record_review, execution_id and review_ref contracts intact.
Do not convert experience.pitfall lessons or cohort statistics into trusted per-memory outcomes.
```

**Why:** Installed and source prompts must agree so coder deliveries use the same evidence schema on every machine.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -F -x -c -- '**Measure every reviewed delivery**, even if no fixes were needed: call `coder_record_review(feature, worktree,' packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md)
# MODIFY anchor at packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:495: **Measure every reviewed delivery**, even if no fixes were needed: call `coder_record_review(feature, worktree,
Require checked_patterns to reference actually delivered versions and engine-verifiable checks.
Keep citations in the structured channel; do not render them into the user-visible answer.
An independently verified zero-fix delivery may be successful without a fabricated fix commit.
Keep coder_record_feedback, coder_record_review, execution_id and review_ref contracts intact.
Do not convert experience.pitfall lessons or cohort statistics into trusted per-memory outcomes.
```

**Why:** Installed and source prompts must agree so coder deliveries use the same evidence schema on every machine.

### `packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py` (CREATE)

```python
"""Behavioral acceptance tests for Coder source and packaged prompt evidence contract."""
import pytest

def test_source_and_packaged_prompt_parity() -> None:
    """Verify source and packaged prompt parity."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_structured_evidence_and_zero_fix_contract() -> None:
    """Verify structured evidence and zero fix contract."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Installed and source prompts must agree so coder deliveries use the same evidence schema on every machine.

### FILL IN checklist

- [ ] `.claude/agents/sdd-coder.md` — Checked evidence and structured citations; bounded by the acceptance criteria below.
- [ ] `.claude/agents/sdd-worker.md` — Verified review guidance including zero-fix deliveries; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md` — Packaged coder parity; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` — Packaged worker parity; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py` — Packaged/source parity and structured evidence guidance; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC11/AC16: source and installed prompt copies agree on structured checked evidence, no exposed citations and real zero-fix verification.
- [ ] AC16: public feedback/review signatures, execution_id and review_ref remain intact; no fictional fixes or automatic FEAT-887 lesson conversion.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_prompt_contract.py -q`

## Test Specification

- `source_and_packaged_prompt_parity`: AC11/AC16: source and installed prompt copies agree on structured checked evidence, no exposed citations and real zero-fix verification.
- `structured_evidence_and_zero_fix_contract`: AC16: public feedback/review signatures, execution_id and review_ref remain intact; no fictional fixes or automatic FEAT-887 lesson conversion.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.
