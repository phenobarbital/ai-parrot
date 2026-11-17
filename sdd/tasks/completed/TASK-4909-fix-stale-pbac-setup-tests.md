# TASK-4909: Fix stale `await setup_pbac` tests and pbac docstring

**Feature**: FEAT-779 — auth-pbac-tech-debt
**Spec**: `sdd/specs/auth-pbac-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:3628027c5a15`

---

## Context

Commit `51885b4be` made `parrot.auth.pbac.setup_pbac` synchronous. Five tests in
`packages/ai-parrot/tests/auth/test_pbac_setup.py` still `await` it and fail on `dev` with
`TypeError: object tuple can't be used in 'await' expression`. The module docstring of `pbac.py` still
calls it an "async helper". Production code is correct; only the tests and one docstring line are stale.
Implements spec §3 Module 1.

---

## Scope

- Convert the five async tests to plain sync tests: remove `@pytest.mark.asyncio`, change `async def` to
  `def`, remove `await`.
- Remove the now-unused `AsyncMock` import.
- Reword `pbac.py` line 3 so it describes `setup_pbac()` as synchronous.

**NOT in scope**: any production code change; reformatting other lines of `pbac.py`
(`issue:1be3b34eafb1`); rewriting `test_setup_pbac_navigator_auth_unavailable`'s mocking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/auth/test_pbac_setup.py` | MODIFY | drop stale `await`/async markers |
| `packages/ai-parrot/src/parrot/auth/pbac.py` | MODIFY | one docstring line |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.pbac import setup_pbac  # verified: packages/ai-parrot/src/parrot/auth/pbac.py:69
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/pbac.py:69
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]":
```

### Does NOT Exist
- ~~`async def setup_pbac`~~ — synchronous since `51885b4be`; no async variant exists.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/auth/test_pbac_setup.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/pbac.py", "action": "MODIFY"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/auth/pbac.py#setup_pbac"]
}
```

---

## Implementation Notes

### Pattern to Follow
`test_setup_pbac_is_idempotent_per_app` in the same file already calls `setup_pbac` synchronously.

### Key Constraints
- Do NOT run `black`/a formatter over the whole of `pbac.py` — only line 3 changes (avoid the churn
  `issue:1be3b34eafb1` describes).
- Run tests with `PYTHONPATH=packages/ai-parrot/src` from the worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `pbac.py` line 3 — because the docstring is the only stale text in production code.
2. In the test file, for each of the 5 tests: delete the `@pytest.mark.asyncio` line, `async def` → `def`,
   remove `await ` — because `setup_pbac` returns a tuple, which cannot be awaited.
3. Change the import to `from unittest.mock import MagicMock, patch` — because `AsyncMock` becomes unused.
4. Run the Validation Commands and `ruff check` on both files.

### `packages/ai-parrot/src/parrot/auth/pbac.py` (MODIFY)
```python
# REPLACE `This module provides the ``setup_pbac()`` async helper that boots the full`
# occurrences: 1 (verified: grep -c 'async helper that boots the full' pbac.py) — line 3
This module provides the synchronous ``setup_pbac()`` helper that boots the full
```
**Why**: the function is a plain `def`; the docstring misleads callers into awaiting it.

### `packages/ai-parrot/tests/auth/test_pbac_setup.py` (MODIFY)
```python
# occurrences: 5 await sites (lines 54, 85, 117, 150, 172), 5 asyncio markers (46, 61, 95, 127, 158)
# Example (line 46-54):
def test_setup_pbac_returns_none_when_dir_missing(tmp_path: Path):
    ...
    pdp, evaluator, guardian = setup_pbac(app, policy_dir=missing)
# line 172:
                    result = pbac_module.setup_pbac(app, policy_dir=tmpdir)
```
**Why**: matches the synchronous signature; no assertion changes.

### FILL IN checklist
- [ ] all 5 tests converted; `grep -c "await " test_pbac_setup.py` is 0

---

## Acceptance Criteria

- [ ] `test_pbac_setup.py` passes: 6 tests, 0 failures.
- [ ] No `await setup_pbac` / `await pbac_module.setup_pbac` remains.
- [ ] `pbac.py` diff is exactly the docstring line.
- [ ] `ruff check` clean on both files.

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_pbac_setup.py -q`

---

## Test Specification

The existing six tests in `test_pbac_setup.py` are the specification; no new tests.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug auth-pbac-tech-debt --feature-id FEAT-779`).
2. Mark `in-progress` in `sdd/tasks/index/auth-pbac-tech-debt.json`, commit only that file.
3. Implement from the blueprint, run the Validation Commands.
4. Commit code (only the two files), close with `scripts/sdd/close_task.sh TASK-4909 auth-pbac-tech-debt verified`,
   fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-opus-5-5 via /sdd-fix (session ea963be2)
**Date**: 2026-10-30
**Notes**: Converted 4 stale async tests to sync calls of `setup_pbac`, dropped the unused `AsyncMock`
import, reworded the `pbac.py` module docstring (line 3 only). Code commit `9b1cb1be2`.
`pytest packages/ai-parrot/tests/auth/test_pbac_setup.py -q` → 6 passed; `ruff check` clean on both files.

**Deviations from spec**: `test_setup_pbac_navigator_auth_unavailable` had to be rewritten, not just
de-awaited — the spec listed this as a non-goal, but removing `await` alone left it failing:
it patched `builtins.__import__` to always raise (so its own `from parrot.auth import pbac` failed) and
mocked the function under test. It now imports `pbac` first, sets `sys.modules["navigator_auth.abac.pdp"]`
to `None`, forces `PARROT_SAAS_MODE=False`, and calls the real `setup_pbac`, asserting the
`(None, None, None)` fail-open triple.
