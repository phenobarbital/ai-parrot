# TASK-4529: `ValidationVerdict` builder and `select_tests.py --verdict`

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4523, TASK-4524
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The verdict is the only payload a seat sees: counts per runner, cached, failures with
`new_red|baseline_red|unknown` and a ≤30-line excerpt (brainstorm Q7 — junit text, or the adapter's own parse).
`--verdict` makes the CLI print only the verdict JSON; it is the native-seat rewrite target (TASK-4534).

---

## Scope

- Create `test_scope/verdict.py`: `build_verdict`, `excerpt_of`, `verdict_to_json`, `verdict_from_json`, `render_for_prompt` per spec skeleton.
- `select_tests.py`: add `--verdict` (implies `--run`) and `--log-dir` (default `artifacts/logs/validation/`); run each invocation with its adapter's `cwd`, report path and `parse_report`; stdout = verdict JSON only (plan + child output go to the log file); exit 0 passed / 1 failed|timed_out / 2 usage|blocked.
- When the task plan is empty under `--verdict`, print a `blocked` verdict whose note is `guard.BLOCK_MESSAGE` and exit 2.

**NOT in scope**: Supervisor use (TASK-4530); seat surfaces (TASK-4533/4534).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py` | CREATE | builder + codec |
| `scripts/sdd/select_tests.py` | MODIFY | --verdict mode |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_verdict.py` | CREATE | builder tests |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | --verdict tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from .datatypes import BaselineVerdict, Failure, RunReport, RunnerSummary, ValidationVerdict  # TASK-4520
from .runners.base import EXCERPT_MAX_LINES  # TASK-4521
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py
parser.add_argument("--run", action="store_true")      # line 47
parser.add_argument("--json", action="store_true")     # line 48
def main(argv=None) -> int                             # line 111 — `if args.json:` line 165; run loop ~205-280 uses subprocess.run(argv, cwd=worktree)
#   empty task plan ⇒ prints guard_mod.BLOCK_MESSAGE, return 2   (~lines 158-162)
#   baseline: `import test_scope.baseline as baseline` after the loop (~line 296)
```

### Does NOT Exist
- ~~`--verdict`, `--log-dir`~~ — added here
- ~~a shebang on select_tests.py~~ — none; invoked via python

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py",
      "action": "CREATE"
    },
    {
      "path": "scripts/sdd/select_tests.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_verdict.py",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_select_tests.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#main"
  ]
}
```

---

## Implementation Notes

- Status rules (spec §3 M5): any `timed_out` ⇒ `timed_out`; any `unavailable`/`no_report` with non-zero exit ⇒ `failed`; failures ⇒ `failed` unless every failure is `baseline_red`; else `passed`.
- Non-pytest failures are always `unknown`; add note `no baseline for <runner>`.
- `render_for_prompt` is deterministic markdown starting with `## Validation verdict`.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. verdict.py + tests — *why*: pure function, easy to freeze.
2. CLI `--verdict` — *why*: native rewrite target.
3. CLI tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py` (CREATE)
```python
"""Validation verdict: the only test payload a coder seat sees (FEAT-709 M5). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .datatypes import BaselineVerdict, Failure, RunReport, RunnerSummary, ValidationVerdict
from .runners.base import EXCERPT_MAX_LINES

VERDICT_SCHEMA: int = 1


def excerpt_of(text: str, *, max_lines: int = EXCERPT_MAX_LINES) -> str:
    """Last ``max_lines`` lines of ``text`` (the traceback tail carries the assertion)."""
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-max_lines:])


def build_verdict(*, tier: str, reports: Sequence[RunReport], baseline: Sequence[BaselineVerdict] = (),
                  cached: Sequence[str] = (), notes: Sequence[str] = (), evidence: Sequence[str] = ()) -> ValidationVerdict:
    """Status precedence: timed_out > failed > passed; baseline-red-only failures pass."""
    # FILL IN: RunnerSummary per report (cached count = len of cached targets belonging to that suite);
    #          Failure per failed/error node (verdict from baseline map for pytest, else "unknown");
    #          status rules from the task's Implementation Notes
    raise NotImplementedError


def verdict_to_json(verdict: ValidationVerdict) -> dict[str, object]: ...
def verdict_from_json(payload: Mapping[str, object]) -> ValidationVerdict: ...
def render_for_prompt(verdict: ValidationVerdict) -> str: ...
# FILL IN: the three bodies above (dataclasses.asdict-equivalent with tuples ⇒ lists; inverse; markdown block)
```
**Why**: Pure functions; the supervisor (TASK-4530) and the CLI share them.

### FILL IN checklist
- [ ] `build_verdict`
- [ ] json codec
- [ ] `render_for_prompt`
- [ ] CLI `--verdict` / `--log-dir` / exit codes
- [ ] tests

---

## Acceptance Criteria

- [ ] `excerpt_of` bounds to 30 lines.
- [ ] Baseline-red-only failures ⇒ `passed`.
- [ ] `--verdict` stdout parses as JSON and nothing else is printed.
- [ ] Empty task plan under `--verdict` ⇒ blocked verdict, exit 2.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_verdict.py -q`
- `pytest tests/sdd_scripts/test_select_tests.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4529 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); implemented by gpt-5.6-sol (codex), 1 attempt, 331.7s
**Date**: 2026-10-20
**Notes**: Merge-tier validation: only 5 pre-existing bwrap failures + test_background_contract.py (owned by TASK-4530). Closed via close_task.sh.

**Deviations from spec**: none
