# TASK-4965: Selector must not emit conftest.py / helper modules as pytest operands

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:55ad6c71c101`

---

## Context

`coder_run_validation(tier=merge)` for FEAT-778 chunk 0 emitted
`pytest ... packages/ai-parrot/tests/experts/conftest.py`. A conftest-only operand
collects zero tests, pytest exits 5, and the merge tier reports `failed` although
every real suite passed. Every FEAT-778 chunk that adds or touches a conftest
reports red.

Root cause (verified): the pytest runner adapter
(`test_scope/runners/pytest.py:41`) maps changed files through
`mirror.pytest_file_targets` → `pytest_file_target_for`
(`test_scope/mirror.py:89`). That function returns ANY existing `.py` under a
`tests/` tree as its own target — `conftest.py` and helper modules included.

## Scope

- In `pytest_file_target_for`, return a path under a `tests/` tree only when its
  basename is a pytest test module (`test_*.py` or `*_test.py`); otherwise `None`.
- Add unit tests covering conftest.py, a helper module, and the unchanged
  test-module pass-through.

**NOT in scope**: `pytest_target_for` (directory mapping), the test_contract cache,
treating exit 5 as skipped, any FEAT-778 expert code.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` | MODIFY | filter non-test modules in `pytest_file_target_for` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py` | MODIFY | regression tests |

## Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.mirror import pytest_file_target_for, pytest_file_targets  # mirror.py:84,89
```
`mirror.py` already imports `os`, `Sequence`, `PurePosixPath` (lines 5–7).

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py
def pytest_file_targets(files: Sequence[str], worktree_path: str) -> list[str]:      # line 84
def pytest_file_target_for(path: str, worktree_path: str) -> str | None:             # line 89
#   line 111:  if parts[0] == "tests":
#   line 112:      return "/".join(parts)
#   line 118:  if rest[0] == "tests":
#   line 119:      return "/".join(parts)
```
Caller: `runners/pytest.py:41  return pytest_file_targets(list(changed), str(worktree))`.

### Does NOT Exist
- No `is_test_module` / `_is_test_file` helper anywhere in `test_scope/` — create a private one.
- No pytest `python_files` config is read by the kernel; hard-code `test_*.py` / `*_test.py`.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py#pytest_file_target_for"
  ]
}
```

## Implementation Blueprint

### Steps (in order)
1. Add `_is_test_module(name)` above `pytest_file_target_for` — because both `tests` branches need it.
2. Replace both `return "/".join(parts)` under a `tests` check with a guarded return — because those are the only paths that leak non-test modules.
3. Add regression tests; run validation.

### `mirror.py` (MODIFY)
```python
# BEFORE — insert above `def pytest_file_target_for(path: str, worktree_path: str) -> str | None:`
# occurrences: 1 (verified: grep -c 'def pytest_file_target_for' mirror.py)
def _is_test_module(name: str) -> bool:
    """Return True when ``name`` is a file pytest collects tests from (``test_*.py`` / ``*_test.py``)."""
    return name.startswith("test_") or name.endswith("_test.py")
```
```python
# REPLACE (occurrences of `return "/".join(parts)`: 2, lines 112 and 119 — both inside pytest_file_target_for)
        return "/".join(parts) if _is_test_module(parts[-1]) else None
```
**Why**: a conftest.py or helper is infrastructure; as an operand it collects
nothing and pytest exits 5. Returning `None` drops it; the suites that use it are
still selected via their own test modules / the contract.

### `test_mirror.py` (MODIFY — append)
```python
def test_file_target_skips_conftest(tmp_path):
    # FILL IN: create packages/ai-parrot/tests/experts/conftest.py and tests/conftest.py
    #          under tmp_path; assert pytest_file_target_for(...) is None for both — bounded by AC1
    ...

def test_file_target_skips_helper_module(tmp_path):
    # FILL IN: helper e.g. tests/x/helpers.py → None — bounded by AC2
    ...

def test_file_target_keeps_test_module(tmp_path):
    # FILL IN: test_foo.py and foo_test.py map to themselves — bounded by AC3
    ...
```

### FILL IN checklist
- [ ] three test bodies (match the file's existing fixture/import style)

## Acceptance Criteria
- AC1 `pytest_file_target_for` returns `None` for any `conftest.py` (root `tests/` and `packages/<dist>/tests/`).
- AC2 returns `None` for non-test helper modules under a tests tree.
- AC3 `test_*.py` / `*_test.py` still map to themselves; existing `test_mirror.py` tests pass.
- AC4 `ruff check` clean on both files.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`

## Agent Instructions
Implement exactly the two files. After merge, the issue `issue:55ad6c71c101` is closed by `/sdd-done FEAT-778`.

## Completion Note
_(fill on completion)_
