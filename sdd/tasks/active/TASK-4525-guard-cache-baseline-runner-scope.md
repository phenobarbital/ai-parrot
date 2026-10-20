# TASK-4525: Runner-aware guard (`verdict` action) and pytest-only green cache / baseline

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4524, TASK-4526, TASK-4527, TASK-4528
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (guard half) and codex S4/S5. The guard stops returning `rewrite` (which re-ran the
plan and leaked stdout) and returns `verdict` with the verdict command argv for a lone broad runner command
inside an attempt. Green cache and baseline must never see non-pytest targets.

---

## Scope

- `GuardOutcome.action` gains `verdict`; `rewrite` is retired. Add `VERDICT_ARGV`.
- `guard_argv`/`guard_bash`: recognise any registered runner via `adapter_for_argv`; broad + attempt context + non-empty task plan ⇒ `verdict`; empty plan ⇒ `block` (unchanged message); else allow. `guard_bash` keeps its compound handling (lone commands only rewritten — brainstorm Q6).
- `green_cache.filter_cached` / `record_green`: operate only on targets/nodes of pytest invocations; others pass through untouched.
- `baseline.classify_failures`: node ids not belonging to a pytest invocation ⇒ `unknown` without a checkout (add `runner_of: Mapping[str,str] | None` kwarg).

**NOT in scope**: Callers of the guard (dispatcher TASK-4533, native hook TASK-4534); the verdict command itself (TASK-4529).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | verdict action |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | MODIFY | pytest-only |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | pytest-only |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py` | MODIFY | verdict tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py` | MODIFY | non-pytest passthrough |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py` | MODIFY | unknown for non-pytest |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from .runners.registry import RunnerRegistry, load_registry  # TASK-4521
from .contract import is_broad_pytest  # contract.py:151 (kept for the pytest adapter)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py
BLOCK_MESSAGE: str                                   # line 15
class GuardOutcome: action, argvs, message           # line 24 — "allow" | "rewrite" | "block"
def _is_pytest_argv(argv) -> bool                    # line 32
def _task_plan(worktree: Path) -> ScopePlan | None   # line 44
def guard_argv(argv, *, worktree: Path) -> GuardOutcome          # line 60 — rewrite branch builds argvs from plan.invocations (line ~73)
def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]   # line 102
# NOTE: `        argvs = tuple(inv.argv for inv in plan.invocations)` occurs 2× (guard_argv and guard_bash)
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py
def _is_cacheable(target: str) -> bool               # line 49 — `.py` only
def filter_cached(worktree, plan, *, namespace, contract=None, policy=None, index=None) -> ScopePlan   # line 156
def record_green(worktree, *, namespace, plan, nodes, unmapped=0, baseline_reds=(), index=None) -> None   # line 223
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py
def _classify_group(checkout, dist, nodeids, timeout_s, tmp_dir) -> dict[str, BaselineVerdict]   # line 96 — always runs pytest
def classify_failures(*, worktree, base_ref, failed_nodeids, timeout_s, scratch=None) -> tuple[BaselineVerdict, ...]   # line 156
```

### Does NOT Exist
- ~~`GuardOutcome.action == "verdict"`~~ — added here
- ~~`VERDICT_ARGV`~~ — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py#guard_argv",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py#guard_bash",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py#GuardOutcome",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#filter_cached",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#record_green",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py#classify_failures"
  ]
}
```

---

## Implementation Notes

- `VERDICT_ARGV = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")` — `select_tests.py` has NO shebang (line 1 is a docstring); always invoke through `python`.
- Keep the `except Exception: return allow` envelopes — a broken guard never breaks a seat.
- `guard_bash` verdict rendering: `cd <root> && python scripts/sdd/select_tests.py … --worktree <root>` (the cd mirrors worktree_environment._scope_guard).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Guard: registry recognition + `verdict` action — *why*: S4.
2. Cache/baseline runner filters — *why*: S5.
3. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _is_pytest_argv(' …/guard.py)
# ADD below BLOCK_MESSAGE (guard.py:15):
VERDICT_ARGV: tuple[str, ...] = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")

# REPLACE _is_pytest_argv (guard.py:32) with:
def _runner_for(argv: Sequence[str], *, worktree: Path) -> "RunnerAdapter | None":
    """The registered runner this argv invokes, or None (registry load failure ⇒ None, never raise)."""
    # FILL IN: load_registry(worktree).adapter_for_argv(argv); except ValueError ⇒ None

# guard_argv (guard.py:60): replace the `rewrite` branch:
#   if plan.invocations: return GuardOutcome(action="verdict",
#       argvs=((*VERDICT_ARGV, "--worktree", str(worktree)),),
#       message=f"`{shlex.join(argv)}` runs through the validation verdict (tier=task)")
# occurrences of `        argvs = tuple(inv.argv for inv in plan.invocations)`: 2 — the one inside guard_argv is
# preceded by `            return GuardOutcome(action="block", message=BLOCK_MESSAGE)`; edit both branches.
```
**Why**: `rewrite` disappears from the vocabulary; callers in TASK-4533/4534 handle `verdict`.

### FILL IN checklist
- [ ] `_runner_for`
- [ ] `guard_argv` / `guard_bash` verdict branches
- [ ] green_cache filters
- [ ] baseline `runner_of` handling
- [ ] tests

---

## Acceptance Criteria

- [ ] Lone broad `pytest` and `vitest run` inside an attempt ⇒ `verdict` with `python scripts/sdd/select_tests.py …`.
- [ ] Compound bash commands ⇒ allow (unchanged).
- [ ] Non-pytest targets are never dropped by `filter_cached` nor recorded by `record_green`.
- [ ] Non-pytest failed node ids classify `unknown` with no baseline checkout created.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4525 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
