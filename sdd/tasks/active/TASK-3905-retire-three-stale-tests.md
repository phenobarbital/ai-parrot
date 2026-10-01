# TASK-3905: Repair/retire the three remaining stale test modules

**Feature**: FEAT-617 — Unpoison `packages/ai-parrot/tests` collection (merge-gate unblock)
**Spec**: `sdd/specs/manager-test-bot-cleanup-lifecycle-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Three of the 4 **genuinely stale** collection errors behind `issue:c3c59277ef77`
(the 4th is TASK-3904; the other 14 are conftest stub artifacts owned by TASK-3903).
Each has a different, independently-verified disposition — this task does all three
because together they are well under an hour and they share no file with any other
task.

| File | Error | Verified cause | Disposition |
|---|---|---|---|
| `tests/test_exceptions.py` | `FileNotFoundError: packages/ai-parrot/parrot/exceptions.py` | Line 17 predates the uv-workspace `src/` layout. Real file is `packages/ai-parrot/src/parrot/exceptions.py` (confirmed present) | **Fix the path** |
| `tests/agents/test_expense_approval.py` | `FileNotFoundError: agents/expense_approval.py` | `/agents/` is gitignored (`.gitignore:293`) **and** the file was deleted in `1fac04add` ("removed test unused agents"). It can never resolve in CI or a fresh worktree | **Module-level skip guard** |
| `tests/test_cryptoquant_integration.py` | `ModuleNotFoundError: parrot.tools.cryptoquant` | `find packages -name '*cryptoquant*'` returns **zero** matches — the toolkit is gone from the workspace | **Delete** (confirmed by the user 2026-10-01) |

`discovered_from: issue:c3c59277ef77`

## Scope

Apply the three dispositions above.

**NOT in scope**:
- `test_save_learned_skill_tool.py` (TASK-3904) or the conftest fix (TASK-3903).
- Restoring the deleted `agents/expense_approval.py` fixture or the CryptoQuant toolkit.
- Converting `test_exceptions.py` to import `parrot.exceptions` normally — it loads the
  `.py` by path **on purpose**, to bypass a compiled `.so` (comment at `test_exceptions.py:15`).
  Preserve that intent; only the path is wrong.
- Any change under `src/` (spec AC9).

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/tests/test_exceptions.py` | MODIFY | correct the `src/` path |
| `packages/ai-parrot/tests/agents/test_expense_approval.py` | MODIFY | add module-level skip guard |
| `packages/ai-parrot/tests/test_cryptoquant_integration.py` | DELETE | toolkit no longer exists |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import importlib.util   # already imported: test_exceptions.py, test_expense_approval.py
from pathlib import Path  # already imported in both files
import pytest             # already imported in both files
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/test_exceptions.py:17
_PY_PATH = Path(__file__).parent.parent / "parrot" / "exceptions.py"
# __file__ = packages/ai-parrot/tests/test_exceptions.py
#   .parent        -> packages/ai-parrot/tests
#   .parent.parent -> packages/ai-parrot          => packages/ai-parrot/parrot/exceptions.py  (WRONG)
#   correct target -> packages/ai-parrot/src/parrot/exceptions.py  (VERIFIED present)

# packages/ai-parrot/tests/agents/test_expense_approval.py:35-36
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENT_PATH = _REPO_ROOT / "agents" / "expense_approval.py"   # ABSENT, and /agents/ is gitignored

# packages/ai-parrot/tests/test_cryptoquant_integration.py:4
from parrot.tools.cryptoquant import CryptoQuantToolkit        # module does not exist anywhere
```

### Does NOT Exist
- ~~`packages/ai-parrot/parrot/exceptions.py`~~ — pre-workspace path; real file is under `src/`
- ~~`agents/expense_approval.py`~~ — deleted in `1fac04add`; `/agents/` gitignored at `.gitignore:293`
- ~~`parrot.tools.cryptoquant`~~ / ~~`CryptoQuantToolkit`~~ — zero matches under `packages/`
- ~~`parrot_tools.cryptoquant`~~ — also absent (the `parrot.tools.<x>` → `parrot_tools.<x>` finder has nothing to resolve to)
- ~~`pytest.skip(...)` without `allow_module_level=True`~~ — raises `Failed: Using pytest.skip outside of a test is not allowed` at module scope

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/tests/test_exceptions.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/agents/test_expense_approval.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/test_cryptoquant_integration.py", "action": "MODIFY" }
  ],
  "contract_symbols": []
}
```
*(`test_cryptoquant_integration.py` is a deletion; the schema has no DELETE action, so
it is declared MODIFY — the file is removed, not edited.)*

## Implementation Notes

### Pattern to Follow
`pytest.skip(reason, allow_module_level=True)` is the standard module-scope guard for a
test whose external fixture may be absent. Guard on the path, not on a `try/except`
around the loader, so the skip reason can name the missing file.

### Key Constraints
- `test_exceptions.py` must keep loading the `.py` **by path** (bypassing a compiled
  `.so`) — that is the module's entire point; only the path literal changes.
- The skip guard must leave `test_expense_approval.py` fully functional for a developer
  who *does* have `agents/expense_approval.py` locally.
- No `src/` changes (spec AC9).

### References in Codebase
- `.gitignore:293` — `/agents/`
- `1fac04add` — "removed test unused agents"

## Implementation Blueprint

### Steps (in order)
1. Fix the `test_exceptions.py` path to point into `src/` — because the real module
   moved there with the uv-workspace layout and the test has not followed.
2. Add the skip guard to `test_expense_approval.py` **above** `_load_agent_module()`,
   so collection stops before the loader ever touches the missing path.
3. `git rm` the cryptoquant test — because the toolkit it covers is gone, so the file
   asserts nothing.
4. Confirm all three files are accounted for: two collect (one as `skipped`), one is gone.

### `packages/ai-parrot/tests/test_exceptions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_PY_PATH = Path(__file__).parent.parent / "parrot" / "exceptions.py"' packages/ai-parrot/tests/test_exceptions.py)
# REPLACE the line `_PY_PATH = Path(__file__).parent.parent / "parrot" / "exceptions.py"` (verified: packages/ai-parrot/tests/test_exceptions.py:17)
# FEAT-617: the uv-workspace layout moved the package under src/; this test still
# loads the .py by path on purpose (bypassing any stale compiled .so — see above).
_PY_PATH = Path(__file__).parent.parent / "src" / "parrot" / "exceptions.py"
```
**Why**: `.parent.parent` is `packages/ai-parrot`; the real module is at
`packages/ai-parrot/src/parrot/exceptions.py`. Inserting the `"src"` segment is the
whole fix — the surrounding `spec_from_file_location` machinery (lines 18-20) is
correct and must not change.

### `packages/ai-parrot/tests/agents/test_expense_approval.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_AGENT_PATH = _REPO_ROOT / "agents" / "expense_approval.py"' packages/ai-parrot/tests/agents/test_expense_approval.py)
# AFTER — insert below `_AGENT_PATH = _REPO_ROOT / "agents" / "expense_approval.py"` (verified: packages/ai-parrot/tests/agents/test_expense_approval.py:36)

# FEAT-617 (issue:c3c59277ef77): /agents/ is gitignored (.gitignore:293) and
# expense_approval.py was deleted in 1fac04add, so this module can never resolve in
# CI or a fresh worktree — it raised FileNotFoundError at COLLECTION time, taking the
# whole tree's collection down with it. Skip cleanly instead; the tests below still
# run for anyone who has the agent file locally.
if not _AGENT_PATH.is_file():
    pytest.skip(
        f"agents/expense_approval.py not present at {_AGENT_PATH} "
        "(/agents/ is gitignored); skipping agent wiring tests",
        allow_module_level=True,
    )
```
**Why**: the guard must sit after `_AGENT_PATH` is defined and before any code that
dereferences it, so collection short-circuits. `allow_module_level=True` is mandatory —
a bare `pytest.skip()` at module scope raises `Failed` instead of skipping. Confirm
`pytest` is imported at the top of the file; add the import if it is not.

### `packages/ai-parrot/tests/test_cryptoquant_integration.py` (DELETE)
```bash
# occurrences: 1 (verified: grep -c 'from parrot.tools.cryptoquant import CryptoQuantToolkit' packages/ai-parrot/tests/test_cryptoquant_integration.py)
# Re-confirm the toolkit is genuinely absent BEFORE deleting — do not delete on faith:
find packages -name '*cryptoquant*' -not -path '*/node_modules/*'   # MUST print nothing
git rm packages/ai-parrot/tests/test_cryptoquant_integration.py
```
**Why**: a test for code that no longer exists is not coverage. The `find` re-check is
mandatory because this is the one irreversible step in the feature; if it prints
anything, **stop** and report rather than deleting.

### FILL IN checklist
- [ ] Confirm `pytest` is imported in `test_expense_approval.py` (add if missing)
- [ ] Re-run the `find` re-check before `git rm`
- [ ] Confirm `test_exceptions.py` tests actually pass, not just collect

## Acceptance Criteria

- [ ] **AC-1** `test_exceptions.py` collects **and its tests pass** against `src/parrot/exceptions.py`
- [ ] **AC-2** `test_expense_approval.py` collects with 0 errors and reports **skipped** (not failed) when the agent file is absent
- [ ] **AC-3** `test_cryptoquant_integration.py` no longer exists; `find packages -name '*cryptoquant*'` is empty
- [ ] **AC-4** These three files contribute **0** collection errors (down from 3)
- [ ] **AC-5** `ruff check` clean on the two modified files
- [ ] **AC-6** No file under `src/` is modified (spec AC9)

## Validation Commands
- `pytest packages/ai-parrot/tests/test_exceptions.py -q`
- `pytest packages/ai-parrot/tests/agents/test_expense_approval.py -q -rs`
- `pytest packages/ai-parrot/tests/test_exceptions.py packages/ai-parrot/tests/agents/test_expense_approval.py --collect-only -q`

## Test Specification

No new tests. The deliverable is that two existing modules collect correctly and one
is retired:

| File | Expected after |
|---|---|
| `test_exceptions.py` | collects; existing assertions pass against the `src/` module |
| `test_expense_approval.py` | collects; `skipped` with a reason naming the missing path |
| `test_cryptoquant_integration.py` | absent from the tree |

## Agent Instructions

1. Test-only change. Do not touch `src/`.
2. **The `git rm` is the one irreversible action in this feature.** Re-run the `find`
   re-check immediately before it and abort if it prints anything.
3. For `test_exceptions.py`, verify the tests *pass* — not merely that the path exists.
   If they fail against the `src/` module, that is a real finding: record it in the
   Completion Note rather than adjusting assertions.
4. Run with `PYTHONPATH=packages/ai-parrot/src`.
5. Independent of TASK-3903 and TASK-3904 — no shared files.

## Completion Note

<!-- filled in on completion -->
**Completed by**:
**Date**:
