# TASK-3309: Test-scope kernel — over-broad pytest guard (argv + bash)

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3308
**Assigned-to**: unassigned

---

## Context

Implements the guard half of spec **Module 3** (§2 Overview item 5, §3 Module 3 `guard.py` skeleton,
G4, R1, R2, R4, AC5). The three seat adapters — MCP (TASK-3312), native Claude hook (TASK-3313) and
codex deny hook (TASK-3314) — all delegate the *decision* to this module:

- **allow** when there is no attempt context (outside an `sdd-coder` attempt) or the command is not an
  over-broad pytest;
- **rewrite** an over-broad pytest to the **task-tier** plan (declared `## Validation Commands` ∪ mirror of
  the attempt's changed files);
- **block** when that plan is empty (brainstorm decision, R4).

`guard.py` is stdlib-only kernel core: the native hook imports it as top-level `test_scope.guard` under the
system `python3`.

---

## Scope

- Create `test_scope/guard.py` with `GuardOutcome`, `guard_argv`, `guard_bash` (signatures fixed by spec).
- Task-tier plan = `plan_tests(tier="task", changed_files=changed_files(worktree, ctx.base_ref),
  declared=parse_validation_commands(<task file text>))`; the task file path is `ctx.task_file` relative to the worktree.
- `guard_argv`: recognise `pytest …`, `python -m pytest …`, `python3 -m pytest …` (and absolute paths to those binaries).
- `guard_bash`: split a command into segments on `&&`, `||`, `;` and `|` using `shlex` (punctuation_chars);
  if any construct outside that subset appears (`$(`, backticks, heredoc `<<`, redirections to files, subshell parens),
  return `allow` + note (R2). Rewrite ONLY the broad pytest segment into a subshell that runs every
  invocation and exits with the OR of their exit codes (R1).
- Messages: rewrite → "rewritten `<orig>` → `<new>` (tier=task)"; block → "no scoped tests for this attempt — add
  test paths to the task's `## Validation Commands` or run a specific test file".
- Any unexpected exception inside the guard → `allow` (never break a seat, spec §7 Patterns).
- Tests in `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py`.

**NOT in scope**: wiring into `LLMCodeDispatcher` / `worktree_environment` / codex hooks (3312/3313/3314),
writing attempt contexts (3312/3313), models/CLI (3310).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | CREATE | `GuardOutcome`, `guard_argv`, `guard_bash` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py` | CREATE | Guard decision matrix tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# stdlib only (kernel core — AC3)
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
```

### Created by dependency tasks (verify on disk before use)
```python
# TASK-3304 test_scope/datatypes.py
class AttemptContext: tier: str; task_id: str; task_file: str; base_ref: str
class ScopePlan: tier; invocations: tuple[PytestInvocation, ...]; escalated; core_hits; skipped_escalations; notes
class PytestInvocation: distribution: str; argv: tuple[str, ...]; targets: tuple[TestTarget, ...]
# TASK-3304 test_scope/contract.py
def parse_validation_commands(task_md: str) -> list[list[str]]
def is_broad_pytest(argv: Sequence[str]) -> bool
# TASK-3306 test_scope/context.py
def read_attempt_context(worktree: Path) -> AttemptContext | None
# TASK-3308 test_scope/select.py (re-exported by __init__)
def changed_files(worktree: Path, base_ref: str) -> list[str]
def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str, declared=(), policy=None) -> ScopePlan
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py:250 — prior art for a documented shell subset
def parse_shell_subset(command: str) -> Optional[list[list[str]]]:
    """Parse a command if — and only if — it is in the documented subset. ... None when the command uses any
    construct outside the subset (in which case the guard makes no decision at all)."""
```
Do NOT import it (it lives in `parrot_tools`, not stdlib-importable from the hook) — mirror its
"outside the subset → no decision" philosophy.

### Does NOT Exist
- ~~`test_scope.guard`~~ — created by THIS task
- ~~a shell AST parser in the kernel~~ — use `shlex.shlex(command, posix=True, punctuation_chars=True)`
- ~~`GuardOutcome.rewritten_command`~~ — `guard_bash` returns the rewritten string as the 2nd tuple element
- ~~escalation at the task tier~~ — `plan_tests(tier="task")` never escalates

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
- Decision object first (`GuardOutcome`), adapters translate it (hint / deny / updatedInput).
- `guard_argv` returns `argvs` = one tuple per `PytestInvocation.argv` of the plan.

### Key Constraints
- Inactive without context: `read_attempt_context(worktree) is None` → `allow` with empty message.
- Never rewrite a scoped command (a file, node id or sub-directory) — only `is_broad_pytest(argv)` ones.
- Unreadable task file → treat declared as `[]` (still mirror), add nothing else.
- Rewritten bash must preserve segments before/after the pytest segment verbatim, including a trailing
  `| tail -n 50` pipe (apply it to the subshell).
- Exit-code aggregation in the subshell: `( a; r=$?; b; r=$((r|$?)); exit $r )`.
- stdlib only, relative imports, never raise out of `guard_argv` / `guard_bash`.

### References in Codebase
- Spec §7 R1 (cross-distribution runs), R2 (compound bash), R4 (empty → block)

---

## Implementation Blueprint

### Steps (in order)
1. Create `GuardOutcome` and a private `_pytest_argv(argv)` recogniser — *why*: both entry points share it.
2. Implement `_task_plan(worktree)` reading context + task file + changed files → `plan_tests(tier="task")` — *why*: single place for the task-tier decision.
3. Implement `guard_argv` — *why*: MCP seats pass argv lists.
4. Implement `guard_bash` segmentation + subshell rewrite — *why*: native seats pass one bash string.
5. Write the decision-matrix tests — *why*: AC5 core.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` (CREATE)
```python
"""Over-broad pytest guard for sdd-coder attempts (FEAT-563, spec Module 3)."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .context import read_attempt_context
from .contract import is_broad_pytest, parse_validation_commands
from .datatypes import ScopePlan
from .select import changed_files, plan_tests

BLOCK_MESSAGE: str = (
    "no scoped tests for this attempt — add test paths to the task's `## Validation Commands` "
    "or run a specific test file"
)
_ALLOW_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", "|"})


@dataclass(frozen=True)
class GuardOutcome:
    """Guard decision for one command."""

    action: str  # "allow" | "rewrite" | "block"
    argvs: tuple[tuple[str, ...], ...] = ()
    message: str = ""


def _is_pytest_argv(argv: Sequence[str]) -> bool:
    """True for pytest / python -m pytest / python3 -m pytest (basename match on argv[0])."""
    # FILL IN: basename(argv[0]) in {"pytest"} or (in {"python","python3"} and argv[1:3] == ["-m","pytest"]) — bounded by spec §2 item 5
    raise NotImplementedError


def _task_plan(worktree: Path) -> ScopePlan | None:
    """Task-tier plan for the active attempt, or None when no attempt context exists."""
    ctx = read_attempt_context(worktree)
    if ctx is None:
        return None
    # FILL IN: read (worktree / ctx.task_file) text → parse_validation_commands (OSError → []);
    #          plan_tests(worktree=worktree, changed_files=changed_files(worktree, ctx.base_ref), tier="task", declared=...)
    #          — bounded by spec Tiers table (task never escalates)
    raise NotImplementedError


def guard_argv(argv: Sequence[str], *, worktree: Path) -> GuardOutcome:
    """allow when no attempt context or not broad; else rewrite to the task-tier plan, or block when empty."""
    try:
        if not _is_pytest_argv(argv) or not is_broad_pytest(argv):
            return GuardOutcome(action="allow")
        plan = _task_plan(worktree)
        if plan is None:
            return GuardOutcome(action="allow")
        if not plan.invocations:
            return GuardOutcome(action="block", message=BLOCK_MESSAGE)
        argvs = tuple(inv.argv for inv in plan.invocations)
        rendered = " ; ".join(shlex.join(a) for a in argvs)
        return GuardOutcome(action="rewrite", argvs=argvs,
                            message=f"rewritten `{shlex.join(argv)}` → `{rendered}` (tier=task)")
    except Exception:  # noqa: BLE001 — a broken guard must never break a seat
        return GuardOutcome(action="allow")


def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]:
    """Same decision for a bash string; returns (outcome, rewritten command or None)."""
    # FILL IN: shlex.shlex(command, posix=True, punctuation_chars=True) with whitespace_split=True;
    #          any token outside words + _ALLOW_SEPARATORS, or "$(" / "`" / "<<" in command → (allow + note, None);
    #          find the first broad pytest segment, guard_argv it; rewrite → rebuild command with that segment replaced by
    #          "( a; r=$?; b; r=$((r|$?)); exit $r )" keeping other segments verbatim; block → (outcome, None)
    #          — bounded by R1, R2
    raise NotImplementedError
```
**Why this shape**: `GuardOutcome` fields and both function signatures are fixed by the spec skeleton.
`guard_argv` is complete except the recogniser and plan lookup because its control flow *is* the spec
decision table (allow / rewrite / block). The broad `except` is the spec's "never break the host" rule.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py` (CREATE)
```python
"""Decision matrix for test_scope.guard (FEAT-563 TASK-3309)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import guard as guard_mod
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan
from parrot.flows.dev_loop.test_scope.guard import guard_argv, guard_bash


def _plan(*argvs: tuple[str, ...]) -> ScopePlan:
    # FILL IN: build a ScopePlan(tier="task", invocations=tuple(PytestInvocation(distribution="a", argv=a, targets=()) ...), ...)
    #          using the exact field names of TASK-3304 datatypes
    raise NotImplementedError


@pytest.fixture
def with_plan(monkeypatch):
    def _set(plan):
        monkeypatch.setattr(guard_mod, "_task_plan", lambda worktree: plan)
    return _set
```

### FILL IN checklist
- [ ] `guard.py::_is_pytest_argv` — three invocation forms; bounded by spec §2 item 5
- [ ] `guard.py::_task_plan` — context + task file + changed files → task plan; bounded by Tiers table
- [ ] `guard.py::guard_bash` — segmentation, unparseable → allow, subshell OR rewrite; bounded by R1/R2
- [ ] `test_guard.py::_plan` + test bodies — see Test Specification

---

## Acceptance Criteria

- [ ] Broad pytest with no attempt context → `allow` (`test_guard_inactive_without_context`)
- [ ] Broad pytest with context → `rewrite` to declared ∪ mirror invocations (`test_guard_rewrites_to_declared_and_mirror`)
- [ ] Broad pytest with empty plan → `block` with `BLOCK_MESSAGE` (`test_guard_blocks_empty_plan`, R4)
- [ ] `cd x && pytest packages/a/tests | tail` rewrites only the pytest segment; heredoc / `$(` → allow (`test_guard_bash_compound_and_unparseable`, R2)
- [ ] Rewritten bash exits non-zero if any invocation fails (R1)
- [ ] Scoped commands (files, node ids, subdirs) are never rewritten
- [ ] `guard.py` is stdlib-only (AC3); `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py -q`

---

## Test Specification

```python
def test_guard_inactive_without_context(tmp_path, with_plan):
    with_plan(None)
    assert guard_argv(["pytest"], worktree=tmp_path).action == "allow"


def test_guard_rewrites_to_declared_and_mirror(tmp_path, with_plan):
    with_plan(_plan(("pytest", "-q", "packages/a/tests/test_x.py")))
    outcome = guard_argv(["pytest", "packages/a/tests"], worktree=tmp_path)
    assert outcome.action == "rewrite" and outcome.argvs[0][-1] == "packages/a/tests/test_x.py"


def test_guard_blocks_empty_plan(tmp_path, with_plan):
    with_plan(_plan())
    assert guard_argv(["python", "-m", "pytest"], worktree=tmp_path).action == "block"


def test_scoped_command_is_allowed(tmp_path, with_plan):
    with_plan(_plan(("pytest", "x")))
    assert guard_argv(["pytest", "packages/a/tests/test_x.py::t"], worktree=tmp_path).action == "allow"


def test_guard_bash_compound_and_unparseable(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py"), ("pytest", "b.py")))
    outcome, rewritten = guard_bash("cd sub && pytest packages/a/tests | tail -n 5", worktree=tmp_path)
    assert outcome.action == "rewrite" and rewritten.startswith("cd sub && (") and rewritten.endswith("| tail -n 5")
    outcome, rewritten = guard_bash("pytest $(echo tests)", worktree=tmp_path)
    assert outcome.action == "allow" and rewritten is None


def test_rewritten_bash_propagates_failure(tmp_path, with_plan):
    ...  # FILL IN: plan argvs ("false",) and ("true",) via monkeypatched plan; run rewritten with bash → returncode != 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3309-kernel-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (sonnet, sequential fallback — `complex_model_unavailable`, same
systemic roster gap as prior tasks; user-authorized direct implementation)
**Date**: 2026-09-17
**Notes**: Implemented all FILL INs. `_is_pytest_argv` — basename match on the three forms.
`_task_plan` — reads the attempt's task file (`OSError` → empty declared list, mirror still
runs), builds `changed_files(worktree, ctx.base_ref)`, calls `plan_tests(tier="task", ...)`.
`guard_bash` — rejects `$(`/backtick/`<<` via a direct substring check first (cheapest,
catches the unparseable-by-design cases before tokenizing); tokenizes with
`shlex.shlex(..., punctuation_chars=True)` (verified empirically that `"cd sub && pytest x |
tail -n 5"` tokenizes to `['cd','sub','&&','pytest','x','|','tail','-n','5']` before writing
the segmentation logic); any punctuation-only token NOT in the four allowed separators
(redirects, subshell parens, background `&`, …) → allow (outside the supported subset, R2);
locates the first segment that is both a pytest invocation and `is_broad_pytest`; rewrites
only that segment into a `_subshell` (`( a; r=$?; b; r=$((r|$?)); …; exit $r )`, R1) while
rejoining every other segment via `shlex.join`, preserving the original separators in order —
verified this reproduces `"cd sub && ( … ) | tail -n 5"` exactly. Wrote
`test_rewritten_bash_propagates_failure` (FILL IN) actually executing the rewritten string via
`bash -c` with `("false",)` + `("true",)` invocations to prove the OR-of-exit-codes aggregation
is not just string-shaped but behaviourally correct. All 6 new tests pass; full `test_scope`
suite now 51/51; `ruff check` clean; imports verified stdlib + relative-only.

**Deviations from spec**: none — only the two listed files were created.

**Deviations from spec**: none | describe if any
