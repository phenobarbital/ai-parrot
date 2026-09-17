# TASK-3310: Pydantic boundary models + `scripts/sdd/select_tests.py` CLI

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3308
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 4** (§3 Module 4 skeleton, §2 "New Public Interfaces" CLI, AC2, AC9c, AC11, AC13).
Markdown agents (`qa-runner`, `sdd-worker`, `/sdd-done` — rewritten in TASK-3319) and the evidence task
(TASK-3320) call the kernel through this CLI; QANode (TASK-3311) consumes `ScopePlanModel`.

Two fixed decisions from the plan:
- `test_scope/models.py` is the **only** kernel module that imports pydantic (AC3).
- The CLI must **not import `parrot`** (navconfig `os.chdir` on import, heavy init). It loads the kernel **by
  path** as top-level `test_scope` from `<repo root>/packages/ai-parrot/src/parrot/flows/dev_loop`. Never
  import the kernel under both names in one process (distinct class identities).

`--run` records green **core** escalations in the ledger so the next merge/feature plan skips them (AC9c).

---

## Scope

- Create `test_scope/models.py`: `TestTargetModel`, `PytestInvocationModel`, `CoreHitModel`, `ScopePlanModel`
  (+ `from_plan`), exactly per spec §3 Module 4.
- Create `scripts/sdd/select_tests.py` with `main(argv) -> int`:
  - `--tier {task,merge,feature}` (required), `--base` (default `origin/dev`), `--task-file` (repeatable),
    `--worktree` (default cwd), `--run`, `--json`.
  - Plan: `plan_tests(worktree, changed_files=changed_files(worktree, base), tier, declared=<parsed from each task file>)`.
  - Output: `--json` → `ScopePlanModel.from_plan(plan).model_dump_json(indent=2)`; otherwise one shell-ready
    line per invocation (`shlex.join`) plus notes / escalations / skipped escalations as `#` comment lines.
  - `--run`: run each invocation sequentially (`subprocess.run(argv, cwd=worktree)`), stream output; for every
    **core**-escalated distribution whose invocation exited 0, call `record_green_escalation(worktree, [dist],
    [hit.path for hit in plan.core_hits if dist in hit.distributions])`.
  - Exit codes: 0 success; 1 any invocation failed; 2 usage error or empty **task**-tier plan.
- Create `tests/sdd_scripts/test_select_tests.py` incl. the fixture-monorepo integration test (spec §4
  `test_select_tests_on_fixture_monorepo`).

**NOT in scope**: QANode wiring (3311), markdown agent changes (3319), seat guards (3312–3314), editing
`scripts/sdd/__init__.py` (already exists, empty).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py` | CREATE | Pydantic mirrors of `ScopePlan` |
| `scripts/sdd/select_tests.py` | CREATE | Tier CLI (`--tier/--base/--task-file/--worktree/--run/--json`) |
| `tests/sdd_scripts/test_select_tests.py` | CREATE | CLI + fixture-monorepo integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: used by scripts/sdd/check_task_graph.py (from pydantic import BaseModel, Field)
import argparse, json, shlex, subprocess, sys  # stdlib
from pathlib import Path
from typing import Literal
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py:318-331 — CLI convention to copy (argparse, --json, print with noqa T201, int exit)
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint per-spec task graphs (depends_on / parallel).")
    ...
    print(json.dumps([r.model_dump() for r in reports], indent=2))  # noqa: T201 - CLI output
    return 1 if any(r.errors for r in reports) else 0

if __name__ == "__main__":
    raise SystemExit(main())

# tests/sdd_scripts/test_check_task_graph.py:6 — test import convention
from scripts.sdd.check_task_graph import check_graph, main, module_of, parse_declared_files
```
- `scripts/sdd/__init__.py` exists (empty); `scripts/__init__.py` does NOT (namespace import `scripts.sdd` works from repo root).
- `tests/sdd_scripts/__init__.py` exists.

### Created by dependency tasks (verify on disk before use)
```python
# TASK-3304 test_scope/datatypes.py: TestTarget, PytestInvocation, ScopePlan (tier, invocations, escalated,
#   core_hits, skipped_escalations, notes), CoreHit (path, module, fanin, forced, distributions)
# TASK-3304 test_scope/contract.py: parse_validation_commands(task_md) -> list[list[str]]
# TASK-3306 test_scope/context.py: record_green_escalation(worktree, hit_dists, core_files) -> None
# TASK-3308 test_scope/__init__.py re-exports: plan_tests(*, worktree, changed_files, tier, declared=(), policy=None), changed_files(worktree, base_ref)
```

### Does NOT Exist
- ~~`scripts/sdd/select_tests.py`~~, ~~`test_scope.models`~~ — created by THIS task
- ~~`ScopePlanModel.to_plan()`~~ — only `from_plan` is specified
- ~~a pytest plugin / entry point~~ — the CLI builds argv lists only (spec Non-Goal Option C)
- ~~`scripts/__init__.py`~~ — do not create it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py",
      "action": "CREATE"
    },
    {
      "path": "scripts/sdd/select_tests.py",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_select_tests.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#main"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- `scripts/sdd/check_task_graph.py` for CLI shape and output conventions.
- `models.py` uses `from .datatypes import ScopePlan` (relative) so it works under both import names.
- The pytest session imports the kernel as `parrot.flows.dev_loop.test_scope` (other kernel tests) AND as top-level
  `test_scope` (this CLI): never pass objects between the two (distinct class identities) — the CLI only prints/returns ints.

### Key Constraints
- `select_tests.py` computes the kernel dir as `Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"`,
  inserts it at `sys.path[0]` **inside a function** (`_load_kernel()`), then `import test_scope` — never `import parrot`.
- `--worktree` defaults to `Path.cwd()`; relative task files resolve against it.
- Empty task-tier plan → print the guard block message and exit 2 (consistent with R4).
- Print with `# noqa: T201 - CLI output`; no logging config changes.
- Invocation output must not be captured in `--run` (agents need the real pytest output).

### References in Codebase
- `scripts/sdd/check_task_graph.py` — CLI conventions
- Spec §2 "New Public Interfaces" — CLI flags are fixed

---

## Implementation Blueprint

### Steps (in order)
1. Create `models.py` with the four Pydantic models and `ScopePlanModel.from_plan` — *why*: QANode and `--json` share one schema.
2. Create `select_tests.py` with `_load_kernel`, `_build_parser`, `main` — *why*: agents need one command per tier.
3. Implement `--run` + ledger recording — *why*: AC9c "paid once".
4. Write `test_select_tests.py` with a fixture monorepo — *why*: spec §4 integration test.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py` (CREATE)
```python
"""Pydantic boundary models for the test-scope kernel (FEAT-563). The ONLY kernel module importing pydantic."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .datatypes import ScopePlan


class TestTargetModel(BaseModel):
    """One selected test path and why it was selected."""

    __test__ = False  # not a pytest test class
    path: str
    distribution: str
    reason: Literal["declared", "mirror", "import", "core", "escalated"]


class PytestInvocationModel(BaseModel):
    """One per-distribution pytest invocation."""

    distribution: str
    argv: list[str]
    targets: list[TestTargetModel]


class CoreHitModel(BaseModel):
    """A changed core module that triggered escalation."""

    path: str
    module: str
    fanin: int
    forced: bool
    distributions: list[str]


class ScopePlanModel(BaseModel):
    """JSON-serialisable mirror of `ScopePlan`."""

    tier: Literal["task", "merge", "feature"]
    invocations: list[PytestInvocationModel]
    escalated: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    core_hits: list[CoreHitModel] = Field(default_factory=list)
    skipped_escalations: list[str] = Field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: ScopePlan) -> "ScopePlanModel":
        """Convert the stdlib dataclass plan into its Pydantic mirror."""
        # FILL IN: map dataclass fields 1:1 (tuples → lists); use dataclasses.asdict or explicit comprehension — bounded by field names above
        raise NotImplementedError
```
**Why this shape**: field names/types are fixed by spec §3 Module 4. `__test__ = False` stops pytest from
collecting `TestTargetModel` as a test class (name starts with `Test`).

### `scripts/sdd/select_tests.py` (CREATE)
```python
"""``select_tests.py`` — tier-scoped pytest plans for SDD agents (FEAT-563).

Usage:
    python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base origin/dev]
        [--task-file sdd/tasks/active/TASK-NNN-x.md ...] [--worktree .] [--run] [--json]
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"


def _load_kernel() -> ModuleType:
    """Import the stdlib kernel by path as top-level `test_scope` (never `import parrot`)."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope  # noqa: PLC0415 — path-dependent import

    return test_scope


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan (and optionally run) tier-scoped pytest invocations.")
    parser.add_argument("--tier", required=True, choices=("task", "merge", "feature"))
    parser.add_argument("--base", default="origin/dev")
    parser.add_argument("--task-file", action="append", default=[], type=Path)
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: 0 ok, 1 an invocation failed, 2 usage error / empty task-tier plan."""
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return 2
    kernel = _load_kernel()
    worktree = args.worktree.resolve()
    # FILL IN: declared = [cmd for tf in args.task_file for cmd in kernel.contract.parse_validation_commands((worktree / tf).read_text())]
    #          plan = kernel.plan_tests(worktree=worktree, changed_files=kernel.changed_files(worktree, args.base), tier=args.tier, declared=declared)
    #          print --json (import test_scope.models lazily) or shell lines + "# note:" / "# escalated:" / "# skipped:" comments
    #          empty task plan → print guard.BLOCK_MESSAGE, return 2; not --run → return 0
    #          --run → subprocess.run each argv (cwd=worktree), record green core escalations, return 1 if any failed
    #          — bounded by spec §2 CLI, AC9c
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: follows `check_task_graph.py` CLI conventions; `_load_kernel` isolates the by-path
import so tests can call `main([...])` in-process. `argparse` exits with 2 on bad flags; we convert that
to a return value so tests do not need `pytest.raises(SystemExit)`.

### `tests/sdd_scripts/test_select_tests.py` (CREATE)
```python
"""Tests for scripts/sdd/select_tests.py (FEAT-563 TASK-3310)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.select_tests import main


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def fixture_monorepo(tmp_path: Path) -> Path:
    """git-initialised tree: packages/a/{src/pa/x.py,tests/test_x.py}, packages/b/…, tests/test_root.py, pytest.ini."""
    files = {
        "pytest.ini": "[pytest]\n",
        "packages/a/src/pa/x.py": "X = 1\n",
        "packages/a/tests/test_x.py": "def test_x():\n    assert True\n",
        "packages/b/src/pb/y.py": "from pa.x import X\n",
        "packages/b/tests/test_y.py": "def test_y():\n    assert True\n",
        "tests/test_root.py": "def test_root():\n    assert True\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path
```

### FILL IN checklist
- [ ] `models.py::ScopePlanModel.from_plan` — 1:1 field mapping; bounded by spec §3 Module 4
- [ ] `select_tests.py::main` — plan, output, empty-task exit 2, `--run`, ledger recording; bounded by spec §2 CLI / AC9c
- [ ] `test_select_tests.py` — bodies in Test Specification

---

## Acceptance Criteria

- [ ] `--json` output validates as `ScopePlanModel` and every argv carries the agent flags + marker expression (AC2)
- [ ] `--run` exit code: 0 when all pass, 1 when any invocation fails; empty task-tier plan exits 2 (`test_cli_json_and_exit_codes`)
- [ ] `--run` records green core escalations; a second `--tier merge` plan lists them under `skipped_escalations` (AC9c)
- [ ] Fixture monorepo: `--tier task/merge/feature` plans match expectations and `--run` executes (`test_select_tests_on_fixture_monorepo`)
- [ ] No plan contains an invocation spanning two distributions (AC11)
- [ ] `models.py` is the only kernel module importing pydantic (AC3); `select_tests.py` never imports `parrot`
- [ ] `ruff check scripts/sdd/select_tests.py packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py` clean

---

## Validation Commands
- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Test Specification

```python
def test_cli_json_and_exit_codes(fixture_monorepo, capsys):
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")
    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "merge"
    assert all(len({inv["distribution"]}) == 1 for inv in payload["invocations"])


def test_empty_task_plan_exits_2(fixture_monorepo):
    assert main(["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo)]) == 2


def test_bad_flag_exits_2():
    assert main(["--tier", "nope"]) == 2


def test_select_tests_on_fixture_monorepo(fixture_monorepo):
    ...  # FILL IN: modify packages/a/src/pa/x.py; --tier task --task-file <file with ## Validation Commands> --run → 0;
         #          make test_x fail → --run returns 1


def test_run_records_green_core_escalation(fixture_monorepo, capsys, monkeypatch):
    ...  # FILL IN: force core (monkeypatch policy threshold via kernel ScopePolicy default or CORE_PATHS) → --tier merge --run;
         #          second --json plan has "a" in skipped_escalations
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
7. **Move this file** to `tasks/completed/TASK-3310-models-and-select-tests-cli.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (sonnet, sequential fallback — `complex_model_unavailable`, same
systemic roster gap as prior tasks; user-authorized direct implementation)
**Date**: 2026-09-17
**Notes**: `models.py::ScopePlanModel.from_plan` — explicit 1:1 field-by-field construction
(not `dataclasses.asdict`, since `TestTarget.reason` needed the `Literal` type and nested
dataclasses need their own Pydantic model wrappers, not raw dicts). `select_tests.py::main` —
declared commands parsed from every `--task-file` via `kernel.contract.parse_validation_commands`;
plan built via `kernel.plan_tests`; empty **task**-tier plan → prints `guard.BLOCK_MESSAGE`
(imported lazily as `test_scope.guard`, since `guard.py` is never transitively imported by
`__init__.py` and needed an explicit path-dependent import) and exits 2; `--json` lazily
imports `test_scope.models` (keeping pydantic out of the default code path); `--run` executes
each invocation via `subprocess.run` (uncaptured, so agents see real pytest output) and, for
any invocation whose targets include a `reason == "core"` entry AND that exited 0, calls
`kernel.context.record_green_escalation` for that one distribution with its own core files
(not blindly for every `plan.core_hits` distribution — only ones that were ACTUALLY
core-escalated and green this run). Wrote `test_select_tests_on_fixture_monorepo` (task tier,
`--run`, pass then fail) and `test_run_records_green_core_escalation` (FILL IN tests): the
core-escalation test needed a working monkeypatch strategy — `ScopePolicy`'s dataclass-default
constants are baked into the generated `__init__`'s parameter defaults at class-definition
time, so patching `policy.py`'s module constants or even the class attribute post-import has
no effect on new instances; the test instead monkeypatches `test_scope.select.ScopePolicy`
(the name binding INSIDE the `select` module's own namespace, where `plan_tests` actually
calls `ScopePolicy()`) with a zero-arg factory returning a real `ScopePolicy(core_fanin_threshold=1)`.
Hit one real bug while writing that test: `capsys.readouterr()` called only once after TWO
`main()` calls returned the concatenated output of both (shell-line plan + subprocess pytest
output from the first `--run`, followed by the second call's JSON) — `json.loads` failed on
the combined string; fixed by draining `capsys` between the two calls. All 5 new tests pass;
full `test_scope` suite still 51/51 (unaffected — this task adds no kernel wiring, only a new
sibling module + CLI); `ruff check` clean; confirmed `models.py` is the only kernel file
importing pydantic (`grep -rl "import pydantic\|from pydantic" test_scope/`) and
`select_tests.py` never imports `parrot`.

**Deviations from spec**: none — only the three listed files were created.

**Deviations from spec**: none | describe if any
