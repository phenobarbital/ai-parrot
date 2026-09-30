# TASK-3889: Nonempty bookstore title fallback

**Feature**: FEAT-615 — Bookstore re-index via staging tree + atomic PageIndex rename
**Spec**: `sdd/specs/bookstore-reindex-atomic-swap.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement M4 by stripping title and choosing stem-derived, stripped raw stem, then Untitled fallback before the existing collision algorithm. Keep returned titles nonblank even for whitespace-only title and stem.

## Scope

Implement M4 by stripping title and choosing stem-derived, stripped raw stem, then Untitled fallback before the existing collision algorithm. Keep returned titles nonblank even for whitespace-only title and stem.

**NOT in scope**: Other feature modules, cross-process locking, global delete_tree cleanup changes, dependencies or shared test configuration changes.

**Parallelism**: Uses existing disambiguate_title and _stem_to_title; owns carding.py and a new test_title_fallback.py. Separate test file avoids overlap with the staging task’s test_library.py.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` | MODIFY | Nonempty bookstore title fallback |
| `packages/ai-parrot/tests/knowledge/bookstore/test_title_fallback.py` | CREATE | Focused regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against current dev source; recheck after dependencies land.

### Verified Imports

```python
import pytest
from parrot.knowledge.bookstore.carding import disambiguate_title
from parrot.knowledge.bookstore.models import TocEntry
```

Standard-library additions need no dependency. pytest is already declared in the workspace; existing module imports were reread.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:94`: `def disambiguate_title(title: str, taken: set[str], *, toc_entries: list[TocEntry], stem: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:88`: `def _stem_to_title(stem: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:98`: `class TocEntry(BaseModel):`

### Does NOT Exist

test_title_fallback.py does not exist and is created here. No new title service or public fallback API is needed.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_title_fallback.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#disambiguate_title",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#_stem_to_title",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#TocEntry"
  ]
}
```

## Implementation Notes

Create only the new focused test file; do not edit test_library.py. Execute its three existing disambiguation node IDs as regression checks. stem.strip() tightens the spec fallback expression to fulfill the stated never-whitespace acceptance criterion.

No Delegation Contract: test bodies and failure branches still require implementation judgment. Blueprint gaps are planning instructions; completed code must contain no placeholders.

## Implementation Blueprint

### Steps (in order)

1. Normalize the title before the first collision check — empty LLM output must not become a display title.
2. Retain ToC/stem/counter disambiguation and test collisions with the fallback — normalization must preserve uniqueness.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` (MODIFY)

- `    if title.casefold() not in taken:` — packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:102, occurrences: 1 (verified with `grep -F -c`).

```python
# Insert immediately BEFORE the unique collision-check anchor.
title = title.strip() or _stem_to_title(stem) or stem.strip() or "Untitled"
# Keep the existing collision logic. Extend docstring to describe normalization.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/tests/knowledge/bookstore/test_title_fallback.py` (CREATE)


```python
"""Nonempty and collision-safe bookstore display titles."""
import pytest
from parrot.knowledge.bookstore.carding import disambiguate_title

@pytest.mark.parametrize("title", ["", "  ", "\t\n"])
def test_disambiguate_title_empty_falls_back_to_stem(title: str) -> None:
    """Blank drafts use a de-slugified filename stem."""
    # FILL IN: assert async_python yields Async Python — AC1.

def test_disambiguate_title_empty_stem_is_untitled() -> None:
    """An empty or whitespace-only stem still yields a nonblank title."""
    # FILL IN: cover empty, whitespace-only, punctuation and raw-stem fallback — AC1.

def test_disambiguate_title_normalizes_before_collision() -> None:
    """Normalized and fallback titles still obey collision rules."""
    # FILL IN: assert uniqueness for taken normalized/fallback values — AC2/AC3.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_title_fallback.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.

## Acceptance Criteria

- [ ] AC1: Empty or whitespace title uses de-slugified stem; if it is empty use a nonblank stripped stem or Untitled.
- [ ] AC2: Whitespace around nonblank titles is removed; casefold collision behavior and existing disambiguation order remain intact.
- [ ] AC3: Fallback values also pass through collision handling and never return an empty or whitespace-only string.
- [ ] Run black (120 columns) and ruff check on touched Python files; retain existing unrelated formatting. Store validation logs in artifacts/logs/.

## Validation Commands

Activate the project venv and export `PYTHONPATH=packages/ai-parrot/src` before running these commands.

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_title_fallback.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py::test_disambiguate_title_not_taken_is_unchanged -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py::test_disambiguate_title_uses_first_distinct_toc_entry -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py::test_disambiguate_title_falls_back_to_stem_then_counter -q`

## Test Specification

Create only the new focused test file; do not edit test_library.py. Execute its three existing disambiguation node IDs as regression checks. stem.strip() tightens the spec fallback expression to fulfill the stated never-whitespace acceptance criterion.

## Agent Instructions

1. Use `$sdd-start TASK-3889` to provision the feature worktree. Never implement on dev.
2. Read the spec and check dependencies are done in `sdd/tasks/index/bookstore-reindex-atomic-swap.json`.
3. Reverify contracts, set in-progress state and implement only declared files.
4. Complete all blueprint gaps, run file-scoped validations and commit scoped code.
5. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the implementation HEAD; it owns the completion note and active-to-completed move. Commit SDD state separately. Do not manually close the ledger issue; FEAT-615 closeout owns that evidence.

## Completion Note

Pending; populated by finalize_task after verified implementation.
