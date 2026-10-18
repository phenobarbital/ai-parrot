# TASK-4441: Lint the `test_contract` index header in check_task_graph

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4440
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (lint half), §5 AC3. `/sdd-task` runs `check_task_graph.py` before committing an index
(see `.claude/commands/sdd-task.md` §4b), so this is where a bad contract is caught at decomposition time
instead of silently narrowing a run later.

---

## Scope

- Add `_check_test_contract(data, root, tasks)` and call it from `check_graph()` next to the existing
  `_check_validation_contract` call.
- Findings (new codes):
  - `test-contract-malformed` (error) — `contract_from_index_header` raised `ValueError`.
  - `test-contract-operand-missing` (error) — an operand's file part does not exist under `root` AND is not
    declared (as CREATE or MODIFY) by any task of this index.
  - `test-contract-real-llm` (error) — an operand's file lives under a `real_llm` auto-marked directory
    (path segment `real_llm`) — the parser already rejects the marker name.
  - `test-contract-task-tests-uncovered` (warning) — a task's own validation test file is not under any
    contract operand's file (helps catch under-declared contracts; spec §7 risk).
- Update the module docstring's Errors/Warnings list.
- Tests in `tests/sdd_scripts/test_check_task_graph.py`.

**NOT in scope**: the existing `validation_contract: "required"` semantics — unchanged. Parsing logic
(TASK-4440). The `/sdd-task` doc change (TASK-4443).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_task_graph.py` | MODIFY | `_check_test_contract` + call site + docstring |
| `tests/sdd_scripts/test_check_task_graph.py` | MODIFY | New tests for the four codes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# check_task_graph.py already loads the kernel contract module by path:
def _load_contract():  # check_task_graph.py:~195-206 → importlib.import_module("test_scope.contract")
# After TASK-4440, that module exposes:
contract.contract_from_index_header(header) -> TestContract | None   # raises ValueError when malformed
contract.parse_validation_commands(task_md) -> list[list[str]]
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py
VALIDATION_CONTRACT = "required"                                                  # line 58
class Finding(BaseModel): level, code, tasks, message                             # line 69
class _Task(BaseModel): id, depends_on, parallel, notes, text, files: dict[str,bool]  # line 93
def _pytest_operands(argv: list[str]) -> list[str]:  # line 209 (strips ::node)
def _check_validation_contract(tasks, root, required) -> list[Finding]:           # line 225
def check_graph(index_path: Path, root: Path) -> GraphReport:                     # line 300
#   line 424-426:
#   report.findings.extend(
#       _check_validation_contract(tasks, root, data.get("validation_contract") == VALIDATION_CONTRACT)
#   )
```

### Does NOT Exist
- ~~`_check_test_contract`~~ — created here
- ~~a `test_contract` key in any existing index~~ — only FEAT-699's own index carries one at first

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/check_task_graph.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_check_task_graph.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#check_graph",
    "sym:scripts/sdd/check_task_graph.py#_check_validation_contract",
    "sym:scripts/sdd/check_task_graph.py#Finding"
  ]
}
```

---

## Implementation Notes

- A legacy index without `test_contract` yields ZERO new findings (backward compatibility, spec §5).
- `test-contract-task-tests-uncovered` compares file parts only (`op.split("::", 1)[0]`); a contract file
  operand covers a task test of the same file; a node operand covers only that same file too.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_check_test_contract` below `_check_validation_contract` — *why*: same loader, same Finding style.
2. Call it from `check_graph` right after the existing validation-contract extend — *why*: one report.
3. Add tests for each code plus "legacy index → no findings".

### `scripts/sdd/check_task_graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def check_graph(index_path: Path, root: Path) -> GraphReport:' check_task_graph.py)
# BEFORE — insert above `def check_graph(index_path: Path, root: Path) -> GraphReport:` (verified: check_task_graph.py:300)
def _check_test_contract(data: dict, root: Path, tasks: dict[str, _Task]) -> list[Finding]:
    """FEAT-699: lint the per-spec index header's cached ``test_contract`` (absent ⇒ no findings).

    Args:
        data: The parsed index JSON (header + tasks).
        root: Repository root for existence checks.
        tasks: Parsed tasks (``text`` and ``files`` populated).

    Returns:
        Findings: test-contract-malformed, test-contract-operand-missing, test-contract-real-llm,
        test-contract-task-tests-uncovered.
    """
    contract_mod = _load_contract()
    try:
        contract = contract_mod.contract_from_index_header(data)
    except ValueError as exc:
        return [Finding(level="error", code="test-contract-malformed", message=f"test_contract: {exc}")]
    if contract is None:
        return []
    findings: list[Finding] = []
    declared = {path for task in tasks.values() for path in task.files}
    # FILL IN: operand-missing / real-llm / task-tests-uncovered loops — bounded by Scope codes + Notes
    return findings
```
```python
# occurrences: 1 (verified: grep -c '_check_validation_contract(tasks, root, data.get("validation_contract") == VALIDATION_CONTRACT)' check_task_graph.py)
# AFTER — insert below the closing `)` of the `report.findings.extend(_check_validation_contract(...))` call (verified: check_task_graph.py:424-426)
    report.findings.extend(_check_test_contract(data, root, tasks))
```

### FILL IN checklist
- [ ] the three content checks in `_check_test_contract`
- [ ] docstring list of codes at the top of the module
- [ ] tests: malformed, missing operand, declared-but-not-yet-created operand is OK, real_llm dir, uncovered warning, legacy index

---

## Acceptance Criteria

- [ ] Each of the four codes fires on a minimal fixture index and nothing fires for a legacy index.
- [ ] An operand created by one of the index's own tasks is NOT reported missing.
- [ ] Existing `test_check_task_graph.py` tests still pass.
- [ ] `ruff check scripts/sdd/check_task_graph.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_check_task_graph.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_check_task_graph.py (append)
def test_test_contract_findings(tmp_path):
    """Write an index with a test_contract (built with contract_to_header so the digest is real)
    whose operand is missing on disk → test-contract-operand-missing error."""
    # FILL IN: reuse this module's existing fixture helpers for index/task files

def test_legacy_index_has_no_test_contract_findings(tmp_path):
    ...  # FILL IN
```

---

## Agent Instructions

Standard (see `sdd/templates/task.md`). Close with
`scripts/sdd/close_task.sh TASK-4441 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
