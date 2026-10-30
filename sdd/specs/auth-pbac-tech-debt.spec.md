---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [auth, pbac, tests, tech-debt, ledger-fix]
---

# Feature Specification: auth-pbac-tech-debt

**Feature ID**: FEAT-779
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Opus 5.5, via /sdd-fix)
**Status**: approved
**Target version**: 1.2.6

> **Source**: work-ledger group `fixgroup:5efa232d2769`, routed to the SDD lane by
> `wikitoolkit ledger plan-fix` (two files → not fast-lane eligible).
> Resolves `issue:3628027c5a15`. The other issue in the group, `issue:1be3b34eafb1`
> (cosmetic reformatting churn in a past `pbac.py` diff), is awareness-only and is
> explicitly out of scope.

---

## 1. Motivation & Business Requirements

### Problem Statement

Commit `51885b4be` ("fix pbac declaration") turned `parrot.auth.pbac.setup_pbac` into a plain
synchronous `def` that returns `(pdp, evaluator, guardian)`. Every production caller already calls it
synchronously. `packages/ai-parrot/tests/auth/test_pbac_setup.py` was not updated: five tests still do
`await setup_pbac(...)` and fail on `dev` with
`TypeError: object tuple can't be used in 'await' expression`:

- `test_setup_pbac_returns_none_when_dir_missing`
- `test_setup_pbac_empty_dir_initializes_zero_policies`
- `test_setup_pbac_with_policies_loads_and_registers`
- `test_setup_pbac_cache_ttl_applied`
- `test_setup_pbac_navigator_auth_unavailable`

The module docstring of `parrot/auth/pbac.py` also still calls `setup_pbac()` an "async helper".

### Goals
- The whole of `test_pbac_setup.py` passes on `dev`.
- The `pbac.py` module docstring describes `setup_pbac()` as synchronous.

### Non-Goals (explicitly out of scope)
- Any production behaviour change to `setup_pbac` or its callers.
- Reverting the cosmetic reformatting tracked by `issue:1be3b34eafb1`.
- Rewriting `test_setup_pbac_navigator_auth_unavailable` so it stops patching the function under test
  (it is tautological today; only the stale `await` is fixed here).

---

## 2. Architectural Design

### Overview
Test-and-docstring fix. The five affected tests become plain synchronous tests (drop
`@pytest.mark.asyncio`, `async def` → `def`, drop `await`), matching the existing synchronous
`test_setup_pbac_is_idempotent_per_app` in the same file. The `AsyncMock` import becomes unused and is
removed; `pytest_plugins = ["anyio"]` is left as is.

### Integration Points
None — no production code path changes.

### Data Models / New Public Interfaces
None.

---

## 3. Module Breakdown

### Module 1: Stale PBAC setup tests + docstring
- **Path**: `packages/ai-parrot/tests/auth/test_pbac_setup.py`, `packages/ai-parrot/src/parrot/auth/pbac.py`
- **Responsibility**: make the five tests call `setup_pbac` synchronously; reword the module docstring
  line "the ``setup_pbac()`` async helper" to "the synchronous ``setup_pbac()`` helper".
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests
The existing tests in `test_pbac_setup.py` are the specification; no new tests are added.

### Validation Contract

tests:
- packages/ai-parrot/tests/auth/test_pbac_setup.py
markers: none

### Test Data / Fixtures
Existing fixtures in the file (`sample_policies_dir`, `empty_policies_dir`); none added.

---

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/auth/test_pbac_setup.py` passes (6 tests, 0 failures).
- [ ] `grep -c "await setup_pbac\|await pbac_module.setup_pbac" packages/ai-parrot/tests/auth/test_pbac_setup.py` is 0.
- [ ] The `pbac.py` module docstring no longer calls `setup_pbac()` async.
- [ ] No other line of `pbac.py` changes.
- [ ] `ruff check` is clean on both files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.auth.pbac import setup_pbac  # verified: packages/ai-parrot/src/parrot/auth/pbac.py:69
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/pbac.py:69
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]":
```

### Does NOT Exist (Anti-Hallucination)
- ~~`async def setup_pbac`~~ — it is synchronous since `51885b4be`; there is no async variant.

### Edit Sites (Blueprint Anchors)

Verified against: `847895f74`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pbac.py` | MODIFY | `This module provides the ``setup_pbac()`` async helper that boots the full` | `pbac.py:3` | 1 |
| `packages/ai-parrot/tests/auth/test_pbac_setup.py` | MODIFY | `await setup_pbac(` / `await pbac_module.setup_pbac(` | `test_pbac_setup.py:54,85,117,150,172` | 5 |

---

## 7. Implementation Notes & Constraints

### Known Risks / Gotchas
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`; a bare `pytest` imports the
  main checkout.
- Format only the touched hunks; do not run a whole-file formatter on `pbac.py` (that is exactly the
  churn `issue:1be3b34eafb1` warns about).

---

## 8. Open Questions

None.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-10-30 | Claude Opus 5.5 (/sdd-fix) | Initial spec from ledger group `fixgroup:5efa232d2769` |
