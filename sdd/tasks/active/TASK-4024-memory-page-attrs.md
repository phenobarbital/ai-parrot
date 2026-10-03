# TASK-4024: InMemoryWikiStore attrs parity and persistence

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4023
**Assigned-to**: unassigned

---

## Context

Complete M1 for the memory/file backend. Mirror SQLite attrs semantics in indexed page rows and persisted bundles. Preserve attrs across reloads and successful compare-and-swap; replacement with empty attrs clears stale values. Do not mutate caller-owned mappings; expose attrs through get_page, get_attrs, filtered stubs and attrs_pages.

---

## Scope

Complete M1 for the memory/file backend. Mirror SQLite attrs semantics in indexed page rows and persisted bundles. Preserve attrs across reloads and successful compare-and-swap; replacement with empty attrs clears stale values. Do not mutate caller-owned mappings; expose attrs through get_page, get_attrs, filtered stubs and attrs_pages.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` | MODIFY | The backend is also a file store; passing RAM-only tests is insufficient. |
| `packages/ai-parrot/tests/knowledge/wiki/test_memory_attrs.py` | CREATE | Exercise temporary bundles and parity edge cases. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Mapping, Sequence  # stdlib or existing pyproject dependency/test environment
from typing import Any  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.file_store as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:73
class InMemoryWikiStore(BaseWikiStore):

# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:377
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:

# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:503
    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: list[tuple[str, str, str]] | None = None,
    ) -> dict[str, Any]:

# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:575
    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None:

# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:716
    async def stats(self) -> dict[str, Any]:
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_memory_attrs.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_memory_attrs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore.upsert_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore.stats"
  ]
}
```

---

## Implementation Notes

TASK-4023: consumes WikiPageRecord.attrs and BaseWikiStore attrs contract

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` (MODIFY)

Anchor `class InMemoryWikiStore(BaseWikiStore):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:73`.

```python
from collections.abc import Mapping, Sequence
from typing import Any
# Add these overrides inside InMemoryWikiStore, preserving its existing methods.
async def get_attrs(self, concept_id: str) -> dict[str, str]:
    """Return attrs for an existing page, respecting backend routing."""
    # FILL IN: implement this task's read contract.
    raise NotImplementedError
async def list_by_attrs(
    self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
    since: str | None = None, until: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    """Return matching stubs with AND/IN/date filter semantics."""
    # FILL IN: implement filtering/fan-out per scope and AC.
    raise NotImplementedError
async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int:
    """Persist attrs for an existing writable page; never target foreign planes."""
    # FILL IN: merge/replace or local-only forwarding per scope and AC.
    raise NotImplementedError
# Extend InMemoryWikiStore with supports_attrs=True and the exact BaseWikiStore
# get_attrs/list_by_attrs/upsert_attrs signatures established by the dependency.
# FILL IN: include a copy of p.attrs in page-row construction and reload/persist paths.
# FILL IN: implement filtering and merge/replace against existing pages; AC2/AC18.
# FILL IN: count attr-bearing pages in stats and include attrs on fetched pages.
# Preserve existing delete/source-replace/CAS and bundle-write semantics.
```

**Why**: The backend is also a file store; passing RAM-only tests is insufficient.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_memory_attrs.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.file_store as subject


def test_memory_attrs_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify memory attrs contract."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_attrs_survive_bundle_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify attrs survive bundle reload."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Exercise temporary bundles and parity edge cases.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_memory_attrs.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] In-memory AND/IN/date predicates match the SQLite contract.
- [ ] Page removal/replacement and merge/replace updates retain no stale attrs.
- [ ] Persist/reopen preserves attrs, and returned mapping mutation cannot corrupt stored values.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_memory_attrs.py -q`
- `pytest tests/knowledge/wiki/test_file_store.py -q`

---

## Test Specification

- In-memory AND/IN/date predicates match the SQLite contract.
- Page removal/replacement and merge/replace updates retain no stale attrs.
- Persist/reopen preserves attrs, and returned mapping mutation cannot corrupt stored values.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4024`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
