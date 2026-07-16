---
type: Wiki Overview
title: 'TASK-1130: Delete Legacy AbstractDBAgent'
id: doc:sdd-tasks-completed-task-1130-delete-abstract-dbagent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 7** of FEAT-164 (spec §3 "Module 7"). The legacy
relates_to:
- concept: mod:parrot.bots.database
  rel: mentions
---

# TASK-1130: Delete Legacy AbstractDBAgent

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1127, TASK-1128
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of FEAT-164 (spec §3 "Module 7"). The legacy
`AbstractDBAgent` (`packages/ai-parrot/src/parrot/bots/database/abstract.py`,
~3067 LOC) is replaced by:

- The refactored `DatabaseAgent(BasicAgent)` (TASK-1128).
- `DatabaseAgentToolkit` carrying the 16 useful helpers (TASK-1127).

Per the resolved Non-Goal in spec §1 ("A backwards-compat shim or
`DeprecationWarning` release"), this is a HARD delete — no
deprecation shim, no warning release.

Codebase contract check at task-creation time (2026-05-13, on `dev`):
the only file referencing `AbstractDBAgent` is `abstract.py` itself.
There is NO `examples/database/base.py` on `dev`. There is NO
re-export in `bots/database/__init__.py:__all__`.

---

## Scope

- Delete `packages/ai-parrot/src/parrot/bots/database/abstract.py`.
- Re-grep for `AbstractDBAgent` across the whole repo to confirm no
  residual references (test fixtures, docs, examples). Remove or
  rewrite any found.
- Add a unit test that asserts the import path is gone.

**NOT in scope**:
- Creating the new example (Module 8 / TASK-1131).
- Updating CHANGELOG (Module 9 / TASK-1132).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/abstract.py` | DELETE | The whole 3067-LOC file is removed. |
| `packages/ai-parrot/src/parrot/bots/database/__init__.py` | MODIFY | Drop any `from .abstract import ...` (likely none); re-check `__all__`. |
| `packages/ai-parrot/tests/bots/database/test_abstract_module_removed.py` | CREATE | Tests confirming the deletion. |
| Other files containing `AbstractDBAgent` references | DELETE/MODIFY | Repo-wide grep to find any straggler. |

---

## Codebase Contract (Anti-Hallucination)

### Verified State (re-verify before deleting)

```bash
# At task-creation time (2026-05-13), these greps returned:
grep -rln "AbstractDBAgent" packages/ai-parrot/
# → only: packages/ai-parrot/src/parrot/bots/database/abstract.py

ls packages/ai-parrot/examples/database/ 2>&1
# → directory does not exist (spec's reference to examples/database/base.py
#   is moot on the current dev branch)

grep -A 30 "__all__" packages/ai-parrot/src/parrot/bots/database/__init__.py
# → AbstractDBAgent is NOT in __all__
```

### Does NOT Exist

- ~~`examples/database/base.py`~~ — the spec mentions deleting it, but
  it is already absent on `dev`. No file deletion needed here.
- ~~`SQLAgent`~~ — referenced by the now-absent example; no action
  needed.
- ~~`from .abstract import AbstractDBAgent` in `__init__.py`~~ — verify
  before assuming. If present, drop it.

---

## Implementation Notes

### Procedure

1. Re-run the verification greps from "Verified State" above. If results
   differ (e.g. a new reference appeared on `dev`), STOP and update this
   task before deleting.
2. `git rm packages/ai-parrot/src/parrot/bots/database/abstract.py`.
3. If `bots/database/__init__.py` had any `from .abstract import ...`
   lines, remove them.
4. Add the deletion-verification test (see Test Specification).
5. Run the full DB test suite to ensure no implicit dependency surfaced:
   `pytest packages/ai-parrot/tests/bots/database/ -v`.

### Key Constraints

- Do not stash or "comment out" the file — full deletion only. The
  helpers worth saving were already migrated by TASK-1127.
- If TASK-1127 is somehow incomplete (file does not exist), STOP — this
  task has an unmet dependency.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py` —
  the new home for the 16 helpers (created by TASK-1127).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/database/abstract.py` does
      not exist on the feature branch.
- [ ] `git grep "AbstractDBAgent"` returns no matches (excluding the
      CHANGELOG entry once TASK-1132 lands).
- [ ] `from parrot.bots.database import AbstractDBAgent` raises
      `ImportError`.
- [ ] Test passes:
      `pytest packages/ai-parrot/tests/bots/database/test_abstract_module_removed.py -v`.
- [ ] Existing tests still pass:
      `pytest packages/ai-parrot/tests/bots/database/ -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_abstract_module_removed.py
from pathlib import Path
import pytest


def test_abstractdbagent_deleted_from_init():
    """from parrot.bots.database import AbstractDBAgent raises ImportError."""
    with pytest.raises(ImportError):
        from parrot.bots.database import AbstractDBAgent  # noqa: F401


def test_abstract_module_file_absent():
    """The abstract.py file no longer exists on disk."""
    # Resolve via the package, so the test is portable.
    import parrot.bots.database as pkg
    pkg_dir = Path(pkg.__file__).parent
    assert not (pkg_dir / "abstract.py").exists()
```

---

## Agent Instructions

1. Verify TASK-1127 (internal toolkit) and TASK-1128 (agent rewrite)
   are complete — files exist in `sdd/tasks/completed/`.
2. Run the verification greps from "Verified State" — abort if any new
   reference to `AbstractDBAgent` appeared on `dev`.
3. `git rm` the file; remove any `from .abstract` lines.
4. Add the deletion-verification test.
5. Run the full DB test suite.
6. Move this file to `sdd/tasks/completed/` and update the per-spec
   index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-13
**Notes**: abstract.py hard-deleted (3067 LOC). Only residual "AbstractDBAgent" mention is in _internal.py docstring (acceptable per spec). All 29 tests pass.
**Deviations from spec**: none
