# TASK-3304: Test-scope kernel — datatypes, mirror selector, validation-contract parser

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First half of spec **Module 1** (test-scope kernel core). Creates the stdlib-only package
`parrot/flows/dev_loop/test_scope/` that every other FEAT-563 task builds on:

- `datatypes.py` — the frozen dataclasses of spec §2 "Data Models" (named `datatypes.py`, not
  `types.py`, so it never shadows the stdlib `types` module).
- `mirror.py` — `QANode._pytest_targets` and helpers **moved verbatim** as module functions
  (`QANode` itself is re-wired later by TASK-3311; this task does NOT touch `qa.py`).
- `contract.py` — `## Validation Commands` parsing and over-broad pytest detection (M9/M3 share it).

The core must import with the standard library only (AC3): the native Claude hook runs under the
system `python3` and imports this package **by path** as top-level `test_scope` (spec §2 Overview).

---

## Scope

- Create `test_scope/__init__.py` re-exporting the public names of `datatypes`, `mirror`, `contract`
  (relative imports only; must NOT import `models.py`, which does not exist yet).
- Create `test_scope/datatypes.py` with `TestTarget`, `PytestInvocation`, `ScopePlan`, `CoreHit`,
  `LedgerEntry`, `AttemptContext` exactly as spec §2 (field names, order, comments).
- Create `test_scope/mirror.py` with `pytest_targets`, `pytest_target_for`, `deepest_existing_dir`,
  `prune_nested` (bodies moved verbatim from `nodes/qa.py:625-717`) and new `distribution_of`.
- Create `test_scope/contract.py` with `VALIDATION_HEADING`, `parse_validation_commands`, `is_broad_pytest`.
- Create the kernel test package `packages/ai-parrot/tests/flows/dev_loop/test_scope/` with parity,
  contract and stdlib-only tests.

**NOT in scope**: policy/planner (TASK-3305), context/ledger (TASK-3306), impact (TASK-3307),
`plan_tests`/`changed_files` (TASK-3308 — the only other task allowed to edit `__init__.py`),
modifying `nodes/qa.py` (TASK-3311), Pydantic models (TASK-3310).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` | CREATE | Stdlib-only re-exports |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | CREATE | Frozen dataclasses (spec §2 Data Models) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` | CREATE | Mirror selector moved from `QANode` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | CREATE | Validation Commands parser + broad-pytest detector |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/__init__.py` | CREATE | Test package marker (empty) |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py` | CREATE | Parity with QANode helpers + `distribution_of` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py` | CREATE | Parser + broad matrix |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py` | CREATE | AC3 isolated-interpreter import |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Source modules: STDLIB ONLY (dataclasses, os, pathlib, re, shlex, typing). Relative imports between kernel modules.
# Tests only:
from parrot.flows.dev_loop.nodes.qa import QANode  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:139 (used by tests/flows/dev_loop/test_qa_default_criteria.py:21)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py  (source of the moved logic — read it, copy bodies verbatim)
class QANode(DevLoopNode):                                                                          # L139
    @classmethod
    def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:                    # L587-630 (decorator L587, def L588)
        targets: set = set()                                                                        # L625
        for path in files: target = cls._pytest_target_for(path, worktree_path) ...                 # L626-629
        return cls._prune_nested(targets)                                                           # L630
    @classmethod
    def _pytest_target_for(cls, path: str, worktree_path: str) -> Optional[str]:                    # L633-676
        parts = PurePosixPath(path).parts                                                           # L644
        if parts and parts[0] == "tests": ...  # root tree rules                                    # L645-656
        tests_root = f"packages/{parts[1]}/tests"                                                   # L659
    @staticmethod
    def _deepest_existing_dir(tests_root: str, subdirs: Tuple[str, ...], worktree_path: str) -> str:  # L679-700
    @staticmethod
    def _prune_nested(targets: set) -> List[str]:                                                   # L703-717
        return sorted(t for t in targets if not any(t.startswith(f"{other}/") for other in targets))  # L717

# packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py — fixtures/tests to mirror for parity
def worktree(tmp_path): ...     # L24-30: packages/{ai-parrot,ai-parrot-tools}/tests + ai-parrot-visualizations/src (no tests)
def mirrored(worktree): ...     # L201-206: adds packages/ai-parrot/tests/flows/dev_loop and tests/loaders
def test_pytest_targets_are_deduped_and_sorted(worktree)                     # L183
def test_source_file_maps_to_mirrored_test_subtree(mirrored)                 # L209
def test_mapping_walks_up_to_the_deepest_directory_that_exists(mirrored)     # L218
def test_changed_test_module_is_its_own_target(mirrored)                     # L228
def test_target_covered_by_an_ancestor_is_pruned(mirrored)                   # L238
def test_deleted_test_module_falls_back_to_the_package_root(mirrored)        # L251
def test_root_level_test_module_is_its_own_target(mirrored)                  # L283
def test_deleted_root_test_module_falls_back_to_the_root_tree(mirrored)      # L292
def test_root_test_without_a_root_tree_maps_to_nothing(worktree)             # L298

# packages/ai-parrot/tests/__init__.py, tests/flows/__init__.py, tests/flows/dev_loop/__init__.py — exist (empty): test dirs are packages
# packages/ai-parrot/pyproject.toml:997 — [tool.pytest.ini_options] asyncio_mode = "auto"
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.test_scope`~~ — created by this task
- ~~`test_scope/types.py`~~ — deliberately named `datatypes.py`
- ~~`test_scope/models.py`~~ — TASK-3310; `__init__.py` must never import it (AC3)
- ~~`plan_tests`, `changed_files`, `ScopePolicy`, `build_plan`~~ — TASK-3305/3308; do not stub them here
- ~~`packages/ai-parrot/tests/flows/dev_loop/test_scope/`~~ — the kernel test package is `test_scope/`
- ~~a shared "validation commands" parser~~ — `sdd_coder/fidelity.py:29 parse_task_files` parses only `## Files to Create / Modify`; follow its section-slicing style, do not import it (it is not stdlib-isolated)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._pytest_targets",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._pytest_target_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._deepest_existing_dir",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._prune_nested"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# The moved code is QANode's, verbatim — only `cls.`/staticmethod plumbing becomes plain function calls.
def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]:
    targets: set[str] = set()
    for path in files:
        target = pytest_target_for(path, worktree_path)
        if target:
            targets.add(target)
    return prune_nested(targets)
```

### Key Constraints
- **Stdlib only** in every `test_scope/*.py` of this task; relative imports (`from .datatypes import …`).
- Google docstrings + type hints; no logging in the kernel (no `parrot` logger config under system python).
- `TestTarget` gets class attribute `__test__ = False` (no annotation, so it is not a dataclass field) —
  otherwise pytest tries to collect it from test modules that import it.
- `LedgerEntry.core_blobs: dict[str, str]` stays a dict (spec fixed it); never hash a `LedgerEntry`.
- Mirror behaviour must be byte-for-byte identical to QANode's (parity tests call both).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:587-717` — logic to move
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:13-45` — markdown section slicing style
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:7-16` — stdlib-only module precedent

---

## Implementation Blueprint

### Steps (in order)
1. Create `datatypes.py` from spec §2 Data Models — *why*: every later kernel module imports these names.
2. Create `mirror.py` copying the bodies of `qa.py:625-717` — *why*: moving (not rewriting) keeps QANode behaviour; parity tests prove it.
3. Add `distribution_of` — *why*: the planner groups by distribution (AC11).
4. Create `contract.py` — *why*: TASK-3309 guard and TASK-3315 lint both need one parser/detector.
5. Create `__init__.py` re-exports (no models) — *why*: AC3 isolation, stable import surface.
6. Write the tests, run them — *why*: parity + AC3 evidence.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` (CREATE)
```python
"""Frozen, stdlib-only data carriers for the test-scope kernel (FEAT-563)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestTarget:
    """One pytest operand selected for a plan."""

    __test__ = False  # not a pytest test class

    path: str  # repo-relative file, dir or node id
    distribution: str  # "<dist>" or "root"
    reason: str  # "declared" | "mirror" | "import" | "core" | "escalated"


@dataclass(frozen=True)
class PytestInvocation:
    """One pytest command for exactly one distribution."""

    distribution: str
    argv: tuple[str, ...]  # full argv starting with "pytest"
    targets: tuple[TestTarget, ...]


@dataclass(frozen=True)
class CoreHit:
    """A changed core source module that triggers escalation."""

    path: str
    module: str
    fanin: int
    forced: bool
    distributions: tuple[str, ...]


@dataclass(frozen=True)
class ScopePlan:
    """The per-tier selection result."""

    tier: str  # "task" | "merge" | "feature"
    invocations: tuple[PytestInvocation, ...]
    escalated: tuple[str, ...]
    core_hits: tuple[CoreHit, ...]
    skipped_escalations: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class LedgerEntry:
    """Last green escalated run for one distribution."""

    distribution: str
    core_blobs: dict[str, str]  # core file path -> git blob hash


@dataclass(frozen=True)
class AttemptContext:
    """Written by the sdd-coder engine into an attempt's per-worktree git dir."""

    tier: str
    task_id: str
    task_file: str
    base_ref: str
```
**Why this shape**: names and fields are fixed by spec §2 (TASK-3305..3314 depend on them). `CoreHit` is
declared before `ScopePlan` so no forward-reference string is needed. Do not add Pydantic.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` (CREATE)
```python
"""Mirror-of-directories test selection, moved verbatim from QANode (FEAT-563 M1)."""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import PurePosixPath


def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]:
    """Map changed files to the narrowest existing test targets (was QANode._pytest_targets, qa.py:588)."""
    targets: set[str] = set()
    for path in files:
        target = pytest_target_for(path, worktree_path)
        if target:
            targets.add(target)
    return prune_nested(targets)


def pytest_target_for(path: str, worktree_path: str) -> str | None:
    """Resolve one changed path to its narrowest existing test target (was qa.py:633)."""
    parts = PurePosixPath(path).parts
    # FILL IN: copy qa.py:645-676 verbatim, replacing `cls._deepest_existing_dir` with `deepest_existing_dir` — bounded by parity tests (AC4)
    raise NotImplementedError


def deepest_existing_dir(tests_root: str, subdirs: tuple[str, ...], worktree_path: str) -> str:
    """Walk tests_root/subdirs upwards to the first existing directory (was qa.py:679)."""
    for depth in range(len(subdirs), 0, -1):
        candidate = "/".join((tests_root, *subdirs[:depth]))
        if os.path.isdir(os.path.join(worktree_path, candidate)):
            return candidate
    return tests_root


def prune_nested(targets: set[str]) -> list[str]:
    """Drop targets already covered by a broader target; sorted (was qa.py:703)."""
    return sorted(t for t in targets if not any(t.startswith(f"{other}/") for other in targets))


def distribution_of(path: str) -> str:
    """Return '<dist>' for packages/<dist>/…, 'root' for tests/…; raise ValueError otherwise."""
    parts = PurePosixPath(path).parts
    # FILL IN: "root" when parts[0] == "tests"; parts[1] when parts[0] == "packages" and len(parts) >= 2;
    #          otherwise raise ValueError(f"not a test-bearing path: {path}") — bounded by AC11
    raise NotImplementedError
```
**Why this shape**: signatures fixed by spec §3 M1 skeleton. Carry over the original docstring rationale
(root tree, missing tests dir → None, deleted modules) as comments when copying the body.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` (CREATE)
```python
"""`## Validation Commands` parsing and over-broad pytest detection (FEAT-563 M1/M9)."""
from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from pathlib import PurePosixPath

VALIDATION_HEADING: str = "## Validation Commands"
_HEADING_RE = re.compile(r"^## Validation Commands\s*$", re.M)
_NEXT_HEADING_RE = re.compile(r"^## ", re.M)
_BULLET_CMD_RE = re.compile(r"^\s*[-*]\s+`([^`]+)`")
_PYTEST_MODULE_FORMS = (("python", "-m", "pytest"), ("python3", "-m", "pytest"))


def parse_validation_commands(task_md: str) -> list[list[str]]:
    """Backticked commands under '## Validation Commands' (bullets), shlex-split; [] when absent."""
    match = _HEADING_RE.search(task_md)
    if not match:
        return []
    body = task_md[match.end():]
    nxt = _NEXT_HEADING_RE.search(body)
    body = body[: nxt.start()] if nxt else body
    commands: list[list[str]] = []
    for line in body.splitlines():
        # FILL IN: match _BULLET_CMD_RE, shlex.split the group; skip lines that fail to split (ValueError) — bounded by test_parse_validation_commands
        pass
    return commands


def _pytest_operands(argv: Sequence[str]) -> list[str] | None:
    """Positional operands of a pytest argv, or None when argv is not a pytest invocation."""
    # FILL IN: accept argv[0] basename "pytest", or a _PYTEST_MODULE_FORMS prefix (basename of argv[0]);
    #          skip options and their values for "-m", "-k", "-c", "-p", "-o", "-n", "--rootdir", "--confcutdir", "--tb", "--ignore";
    #          return remaining non-option tokens — bounded by test_is_broad_pytest_matrix
    raise NotImplementedError


def is_broad_pytest(argv: Sequence[str]) -> bool:
    """True for pytest with no path operand or an operand in {., tests, packages/<dist>/tests} or a parent."""
    operands = _pytest_operands(argv)
    if operands is None:
        return False
    if not operands:
        return True
    for op in operands:
        path = PurePosixPath(op.split("::", 1)[0].rstrip("/") or ".")
        parts = path.parts
        # FILL IN: broad when parts in {(), (".",), ("tests",), ("packages",)} or
        #          (len(parts) == 2 and parts[0] == "packages") or (len(parts) == 3 and parts[0] == "packages" and parts[2] == "tests");
        #          node ids ("::") are never broad — bounded by spec §2 Overview item 5
        pass
    return False
```
**Why this shape**: one detector for guard (TASK-3309) and lint (TASK-3315). `packages/<dist>` and
`packages` are "a parent of" a package tests root, so they are broad too.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` (CREATE)
```python
"""Deterministic test-scope kernel for the SDD cycle (FEAT-563).

Stdlib-only: importable as ``parrot.flows.dev_loop.test_scope`` and, by path, as top-level
``test_scope`` from the system-python native hook. Never import ``models`` (Pydantic) here.
"""
from .contract import VALIDATION_HEADING, is_broad_pytest, parse_validation_commands
from .datatypes import AttemptContext, CoreHit, LedgerEntry, PytestInvocation, ScopePlan, TestTarget
from .mirror import deepest_existing_dir, distribution_of, prune_nested, pytest_target_for, pytest_targets

__all__ = [
    "AttemptContext", "CoreHit", "LedgerEntry", "PytestInvocation", "ScopePlan", "TestTarget",
    "VALIDATION_HEADING", "deepest_existing_dir", "distribution_of", "is_broad_pytest",
    "parse_validation_commands", "prune_nested", "pytest_target_for", "pytest_targets",
]
```
**Why**: stable surface; TASK-3308 appends `plan_tests`, `changed_files` to imports and `__all__`.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/__init__.py` (CREATE)
```python
```
**Why**: sibling test dirs are packages (`tests/flows/dev_loop/__init__.py` exists); keep module names unique.

### FILL IN checklist
- [ ] `mirror.py::pytest_target_for` — verbatim copy of qa.py:645-676; bounded by parity (AC4)
- [ ] `mirror.py::distribution_of` — root/dist/ValueError; bounded by AC11
- [ ] `contract.py::parse_validation_commands` — bullet regex + shlex; bounded by test
- [ ] `contract.py::_pytest_operands` — option skipping; bounded by broad matrix
- [ ] `contract.py::is_broad_pytest` — broad path set; bounded by spec §2 item 5
- [ ] Test bodies in the three test modules below

---

## Acceptance Criteria

- [ ] `test_scope` core imports with the standard library only — `test_core_is_stdlib_only` passes (spec AC3)
- [ ] `mirror.pytest_targets` returns exactly what `QANode._pytest_targets` returns for every scenario of `test_qa_default_criteria.py:183-300` (spec AC4 groundwork)
- [ ] `is_broad_pytest` matrix: bare, `.`, `tests`, `packages/x`, `packages/x/tests`, `python -m pytest` → broad; files, node ids, sub-directories (`packages/x/tests/flows`) → not broad
- [ ] `parse_validation_commands` returns `[]` without the section and parses backticked bullets otherwise
- [ ] `nodes/qa.py` is unchanged by this task
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/` clean

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py
import pytest

from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.test_scope import distribution_of, pytest_targets


@pytest.fixture
def mirrored(tmp_path):
    """Same layout as test_qa_default_criteria.py `worktree` + `mirrored` fixtures."""
    for pkg in ("ai-parrot", "ai-parrot-tools"):
        (tmp_path / "packages" / pkg / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot-visualizations" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot" / "tests" / "flows" / "dev_loop").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot" / "tests" / "loaders").mkdir(parents=True)
    return tmp_path


@pytest.mark.parametrize("files", [
    ["packages/ai-parrot-tools/src/a.py", "packages/ai-parrot/src/b.py", "scripts/sdd/reserve_ids.py"],
    ["packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py"],
    ["packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py"],
    ["packages/ai-parrot/tests/loaders/test_gone.py"],
    ["packages/ai-parrot-visualizations/src/parrot/outputs/x.py"],
    ["tests/test_missing_root.py"],
])
def test_mirror_parity_with_qanode_fixtures(mirrored, files):
    assert pytest_targets(files, str(mirrored)) == QANode._pytest_targets(files, str(mirrored))


def test_distribution_of():
    assert distribution_of("packages/ai-parrot/tests/x.py") == "ai-parrot"
    assert distribution_of("tests/sdd_scripts/test_x.py") == "root"
    with pytest.raises(ValueError):
        distribution_of("scripts/sdd/x.py")


# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py
from parrot.flows.dev_loop.test_scope import is_broad_pytest, parse_validation_commands

TASK_MD = "## Acceptance Criteria\n- [ ] x\n\n## Validation Commands\n\n- `pytest tests/a.py -q`\n- `pytest tests/b.py::test_x`\n\n## Test Specification\n- `pytest nope.py`\n"


def test_parse_validation_commands():
    assert parse_validation_commands(TASK_MD) == [["pytest", "tests/a.py", "-q"], ["pytest", "tests/b.py::test_x"]]
    assert parse_validation_commands("## Scope\n") == []


@pytest.mark.parametrize("argv,broad", [
    (["pytest"], True), (["pytest", "-q"], True), (["pytest", "."], True), (["pytest", "tests"], True),
    (["pytest", "packages/ai-parrot/tests"], True), (["pytest", "packages/ai-parrot"], True),
    (["python", "-m", "pytest", "-q"], True), (["pytest", "-m", "not e2e", "tests/"], True),
    (["pytest", "tests/sdd_scripts/test_x.py"], False), (["pytest", "packages/ai-parrot/tests/flows"], False),
    (["pytest", "tests/a.py::test_b"], False), (["ruff", "check", "."], False),
])
def test_is_broad_pytest_matrix(argv, broad):
    assert is_broad_pytest(argv) is broad


# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py
import subprocess
import sys
from pathlib import Path

import parrot.flows.dev_loop as dev_loop


def test_core_is_stdlib_only():
    """AC3: importable by path under an isolated interpreter without site-packages."""
    dl = str(Path(dev_loop.__file__).parent)
    code = (
        "import sys; sys.path.insert(0, %r); import test_scope; "
        "assert 'pydantic' not in sys.modules; assert 'parrot' not in sys.modules" % dl
    )
    proc = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
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
7. **Move this file** to `tasks/completed/TASK-3304-kernel-datatypes-mirror-contract.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (sonnet, sequential fallback — TASK-3304 was routed `complex`
by the complexity gate with `complex_model_unavailable`; no roster seat was eligible for
`complex` work, so the user explicitly authorized implementing it directly)
**Date**: 2026-09-17
**Notes**: Created the four `test_scope/` kernel modules exactly per the Implementation
Blueprint: `datatypes.py` verbatim from spec §2; `mirror.py` with `pytest_target_for` and
`distribution_of` bodies filled in per the FILL IN markers, verified line-for-line against
`nodes/qa.py:625-717` (read first, confirmed unchanged from the Codebase Contract) before
copying; `contract.py` with `parse_validation_commands`, `_pytest_operands`, and
`is_broad_pytest` filled in and hand-traced against every row of the `test_is_broad_pytest_matrix`
parametrize table and the `test_parse_validation_commands` fixture before running pytest, to
catch logic errors up front; `__init__.py` verbatim re-export list (no `models` import, per
AC3). Created the four test modules verbatim from the Test Specification block. All 21 tests
pass (`pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/ -q`), including the
`test_core_is_stdlib_only` isolated-interpreter (`-I -S`) AC3 check, `ruff check` clean on both
new directories, and `nodes/qa.py` confirmed untouched (`git status --porcelain` on that file
returns nothing).

**Environment note (not a task deviation, not committed):** running the scoped tests initially
failed with `ModuleNotFoundError: No module named 'parrot.utils.types'` (then, after one fix,
`'parrot.utils.parsers.toml'`) — a pre-existing, unrelated environment issue confirmed by
running an EXISTING sibling test (`test_qa_default_criteria.py`) which failed identically
before any of my changes. Root cause: these are compiled Cython `.so` extensions that exist
only in the main checkout (build artifacts, `.gitignore:7` `*.so`, never git-tracked), and the
repo-root `conftest.py`'s worktree-precedence `sys.path`/`parrot.__path__` prepending shadows
the main-checkout's compiled `parrot.utils` package with this worktree's source-only
`packages/ai-parrot/src/parrot/utils/` (which has the `.pyx` but no `.so`). Per
`CLAUDE.md`/`worktree-management.md` (never mutate the shared venv, never `uv sync` in a
worktree), I did **not** touch the shared environment — I created two `symlink`s, inside this
worktree only, from the main checkout's already-built `.cpython-312-x86_64-linux-gnu.so` files
(matching this venv's Python 3.12) to the identical relative path in this worktree:
`packages/ai-parrot/src/parrot/utils/types.cpython-312-x86_64-linux-gnu.so` and
`packages/ai-parrot/src/parrot/utils/parsers/toml.cpython-312-x86_64-linux-gnu.so`. Both are
gitignored (confirmed via `git status --porcelain` showing nothing for that directory) and
were not staged or committed — they are a local-only fix so tests can run in this worktree,
exactly mirroring what a normal build step would have produced here.

**Deviations from spec**: none in file scope (only the eight listed files were created/no
`nodes/qa.py` changes). The two `.so` symlinks above are NOT tracked and NOT part of this
task's file list; flagging them for the orchestrator/`/sdd-done` in case another worktree hits
the same pre-existing environment gap.

**Deviations from spec**: `datatypes.py` holds the core dataclasses (spec updated). The test package is `tests/flows/dev_loop/test_scope/` so the mirror selector maps `src/.../dev_loop/test_scope/*` onto it (a differently named dir would fall back to all of `tests/flows/dev_loop`).
