# TASK-5272: Reject directory contract operands; drop declared directory targets

**Feature**: FEAT-830 — test-scope report fixes
**Spec**: `sdd/specs/test-scope-report-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bfb29d4ffe49`

---

## Context

Spec §1 item 1 / Module 1. A non-broad directory (e.g. `packages/ai-parrot/tests/flows`) is accepted as a
`test_contract` pytest operand by `_normalize_pytest`, then silently skipped by `plan_tests` as "missing on
disk"; a declared `pytest <directory>` Validation Command becomes a target, breaking "never a directory or
suite". Every contract reader (`parse_spec_contract`, `contract_from_index_header`, `lift_schema1`) goes through
`_normalize_pytest`, so one rule there closes the contract side, and `check_task_graph` already turns the
`ValueError` into `test-contract-malformed` (no change to `check_task_graph.py`).

---

## Scope

- Add a `.py` rule to `_normalize_pytest`: raise `ValueError` when an operand's file part does not end in `.py`.
- In `_declared_targets`, drop a **pytest** operand whose file part is a directory in the worktree and append
  the note `declared path is a directory, dropped: <operand>`.
- Write tests for both, plus a lint test proving a directory operand surfaces as `test-contract-malformed`.

**NOT in scope**: `check_task_graph.py` (unchanged — spec rev 0.2); the `plan_tests` contract loop
(select.py:185, unchanged); anything about `parrot-e2e` (FEAT-829); the cache namespace (TASK-5273).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `.py` rule in `_normalize_pytest` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | drop declared directory operands with a note |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py` | MODIFY | normalization tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py` | MODIFY | declared-directory test |
| `tests/sdd_scripts/test_check_task_graph.py` | MODIFY | lint test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import is_broad_pytest, parse_validation_commands  # verified: tests/flows/dev_loop/test_scope/test_contract.py:5
from parrot.flows.dev_loop.test_scope.contract import _normalize_pytest  # verified: test_scope/contract.py:209
from parrot.flows.dev_loop.test_scope import changed_files, plan_tests  # verified: tests/flows/dev_loop/test_scope/test_select.py:10
from scripts.sdd.check_task_graph import _load_contract, check_graph, main, module_of, parse_declared_files  # verified: tests/sdd_scripts/test_check_task_graph.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py
def is_broad_pytest(argv: Sequence[str], *, worktree: Path | None = None) -> bool:  # line 163
def _normalize_pytest(tests: Sequence[object], markers: Sequence[object]) -> RunnerContract:  # line 209
#   loop body: path = operand.split("::", 1)[0]  (line 220); unsafe check ends at line 225-227
def parse_spec_contract(text: str) -> TestContract | None  # used by test helper _test_contract_header
def contract_from_index_header(header, *, registry=None) -> TestContract | None:  # line 533; re-normalizes each block before the digest check (line 573)

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
def _declared_targets(declared, notes, *, worktree, registry=None, tier="task") -> list[TestTarget]:  # line 91
#   for operand in adapter.operands(argv) or ():   (line 115) ; adapter.kind is the runner kind ("pytest")

# tests/sdd_scripts/test_check_task_graph.py
def _repo(tmp_path, tasks, header=None) -> Path:  # line 23 — writes tasks + index, returns index path
def _test_contract_header(tests: list[str]) -> dict:  # line 69 — valid schema-2 header via parse_spec_contract
# check_graph(index, root).findings -> list[Finding(level, code, message)]
# packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py:493-495 — ValueError from
#   contract_from_index_header -> Finding(level="error", code="test-contract-malformed", message=f"test_contract: {exc}")
```

### Does NOT Exist
- ~~`test-contract-directory-operand`~~ — no such finding code; do not add one (spec rev 0.2).
- ~~`check_task_graph._check_directory_operand`~~ — not a function.
- ~~`TestTarget.is_dir`~~ — `TestTarget` is a plain dataclass (path, distribution, reason, runner).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_check_task_graph.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#_normalize_pytest",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#_declared_targets"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `test_scope/` is stdlib-only (loaded path-dependently by `select_tests` / `check_task_graph`).
- The `.py` check is a pure string check — no filesystem access in `_normalize_pytest`.
- The directory drop in `_declared_targets` applies only when `adapter.kind == "pytest"` — vitest/cargo
  targets are not files ending in `.py` and must keep their current behaviour.
- All 92 cached contracts on `dev` use only `.py` operands (scan at spec time), so no stored contract breaks.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `.py` rule in `_normalize_pytest` after the unsafe-operand check — *why*: it is the single choke
   point every contract reader passes through (AC-1, AC-2).
2. Update the `_normalize_pytest` docstring `Raises:` line — *why*: the contract changed.
3. Add the directory drop at the top of the operand loop in `_declared_targets` — *why*: a declared directory
   must never become a target (AC-3).
4. Write the three tests; run all Validation Commands — *why*: `test_spec_contract.py` / `test_contract_schema2.py`
   build contracts and would reveal any existing fixture that used a directory operand.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            raise ValueError(f"unsafe test contract operand: {operand!r}")' contract.py)
# AFTER — insert below `            raise ValueError(f"unsafe test contract operand: {operand!r}")` (verified: contract.py:227)
        if not path.endswith(".py"):
            raise ValueError(f"test contract operand must be a .py file or node, not a directory or suite: {operand!r}")
```
Docstring (contract.py:212-213) becomes:
```python
    Raises:
        ValueError: If an operand or marker cannot safely be used by pytest, or an operand's file part
            is not a ``.py`` file (a directory or suite is never a contract operand).
```
**Why**: `path` is already the `::`-stripped file part (line 220). The message must contain the operand so
`check_task_graph`'s `test-contract-malformed` finding names it.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        for operand in adapter.operands(argv) or ():' select.py)
# AFTER — insert as the FIRST statements inside `        for operand in adapter.operands(argv) or ():` (verified: select.py:115)
            if adapter.kind == "pytest" and (worktree / operand.split("::", 1)[0]).is_dir():
                notes.append(f"declared path is a directory, dropped: {operand}")
                continue
```
**Why**: broad directories are already dropped by `is_broad`; this covers the non-broad ones the issue names.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py` (MODIFY — append)
```python
from parrot.flows.dev_loop.test_scope.contract import _normalize_pytest


@pytest.mark.parametrize("operand", ["packages/ai-parrot/tests/flows", "tests/sdd_scripts", "tests/x.txt"])
def test_normalize_pytest_rejects_non_py_operands(operand: str) -> None:
    with pytest.raises(ValueError, match="must be a .py file"):
        _normalize_pytest([operand], [])


@pytest.mark.parametrize("operand", ["tests/test_a.py", "tests/test_a.py::test_b", "tests/test_a.py::C::test_d"])
def test_normalize_pytest_accepts_py_files_and_nodes(operand: str) -> None:
    # FILL IN: assert operand in _normalize_pytest([operand], []).targets — bounded by AC-1
    ...
```

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py` (MODIFY — append)
```python
def test_declared_directory_operand_is_dropped_with_note(tmp_path: Path) -> None:
    # FILL IN: build a worktree with packages/ai-parrot/tests/flows/test_x.py (reuse this module's _git /
    # repo helpers), call plan_tests(worktree=..., changed_files=[], tier="task",
    # declared=[["pytest", "packages/ai-parrot/tests/flows", "-q"]]); assert no invocation targets that
    # directory and "declared path is a directory, dropped: packages/ai-parrot/tests/flows" is in plan.notes
    # — bounded by AC-3
    ...
```

### `tests/sdd_scripts/test_check_task_graph.py` (MODIFY — append)
```python
def test_directory_contract_operand_is_malformed(tmp_path):
    """A cached contract naming a directory lints as test-contract-malformed (FEAT-830)."""
    (tmp_path / "tests/flows").mkdir(parents=True)
    header = _test_contract_header(["tests/flows/test_x.py"])
    header["test_contract"]["runners"][0]["targets"] = ["tests/flows"]
    index = _repo(tmp_path, [{"id": "TASK-1", "files": {"tests/flows/test_x.py": "CREATE"}}], header=header)
    findings = check_graph(index, tmp_path).findings
    # FILL IN: assert exactly one finding has code "test-contract-malformed", level "error", and
    # "tests/flows" in its message — bounded by AC-2
```
**Why**: normalization runs before the digest check (contract.py:573-575), so the stale digest never masks it.

### FILL IN checklist
- [ ] `test_normalize_pytest_accepts_py_files_and_nodes` — assertion; AC-1
- [ ] `test_declared_directory_operand_is_dropped_with_note` — fixture + assertions; AC-3
- [ ] `test_directory_contract_operand_is_malformed` — assertions; AC-2

---

## Acceptance Criteria

- [ ] AC-1 `_normalize_pytest` raises `ValueError` for a non-`.py` file part; `.py` files and node ids pass.
- [ ] AC-2 A header whose pytest target is a directory lints as `test-contract-malformed` naming the operand.
- [ ] AC-3 A declared `pytest <directory>` yields no target and the note `declared path is a directory, dropped: <operand>`.
- [ ] `ruff check` clean on the changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract_schema2.py -q`
- `pytest tests/sdd_scripts/test_check_task_graph.py -q`

---

## Test Specification

See the Blueprint test blocks above.

---

## Agent Instructions

1. Work in `feat-FEAT-830-test-scope-report-fixes`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Verify the Codebase Contract anchors (`grep -c`) before editing.
3. Implement from the Blueprint, complete every `FILL IN`, run the Validation Commands.
4. Commit only the listed files; close with `parrot sdd task close TASK-5272 test-scope-report-fixes verified`.

---

## Completion Note

*(Agent fills this in when done)*
