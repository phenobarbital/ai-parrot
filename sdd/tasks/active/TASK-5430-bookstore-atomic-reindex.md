# TASK-5430: Serialize import identity and preserve graph only with equal source and TOC

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5429
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Implement the complete source/allocation/book lock protocol in spec §2 using the previous task primitives.
- Acquire sorted canonical-path/hash locks before catalog identity lookup; bound all acquisition by one monotonic deadline. Re-read identity after book lock acquisition.
- For new IDs acquire configured-location allocation locks in canonical path order; include active staging bases in occupied slugs and create staging before releasing allocation.
- Hold source/book locks through staging publication, catalog upsert and invalidation, then release before optional relate_books.
- Preserve graph/community only with equal nonempty source_sha256 AND toc_digest; retain manual card rules. Cleanup staged work on BaseException without deleting a successfully published live tree after catalog failure.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` | MODIFY | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Optional  # verified: stdlib; existing library.py:27
from pathlib import Path  # verified: stdlib; existing library.py:26
from parrot.knowledge.bookstore.models import BookCard  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:152
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1061
async def add_book(
        self,
        file_path: str | Path,
        scope: str = "project",
        title: Optional[str] = None,
        authors: Optional[list[str]] = None,
        topics: Optional[list[str]] = None,
        force: bool = False,
        *,
        relate: bool = False,
    ) -> tuple[BookCard, str]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:254
def _all_taken_slugs(self) -> set[str]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1421
def _invalidate_graph(self, book_id: str) -> None:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:380
def find_by_sha(self, sha256: str) -> Optional[BookCard]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:386
def find_by_path(self, source_path: str) -> Optional[BookCard]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:741
async def rename_tree(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py:203
async def publish(self) -> PublishReport:
```


### Dependency-produced contracts

- TASK-5429: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py, packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- No reentrant tree_lock or atomic catalog+tree transaction exists; do not invent one.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._all_taken_slugs",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._invalidate_graph",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.find_by_sha",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.find_by_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.rename_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#WriteTransaction.publish",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard"
  ]
}
```

## Implementation Notes

TASK-5429: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py, packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Implement the complete source/allocation/book lock protocol in spec §2 using the previous task primitives. **Why**: Concurrent identical sources, changed bytes at the same path, and new slug collisions serialize or time out clearly without unrelated overwrite.
2. Acquire sorted canonical-path/hash locks before catalog identity lookup; bound all acquisition by one monotonic deadline. Re-read identity after book lock acquisition. **Why**: Equal known source hash and TOC preserve graph and community; either mismatch or unknown hash invalidates only after successful rename/upsert.
3. For new IDs acquire configured-location allocation locks in canonical path order; include active staging bases in occupied slugs and create staging before releasing allocation. **Why**: Ingest failure or cancellation preserves old tree/card/graph and cleans staging; post-rename catalog failure leaves live content available for doctor.
4. Hold source/book locks through staging publication, catalog upsert and invalidation, then release before optional relate_books. **Why**: Real rename completes without reentering the destination lock; timeout acquisition is bounded and add-folder can report/continue failures.
5. Preserve graph/community only with equal nonempty source_sha256 AND toc_digest; retain manual card rules. Cleanup staged work on BaseException without deleting a successfully published live tree after catalog failure. **Why**: Concurrent identical sources, changed bytes at the same path, and new slug collisions serialize or time out clearly without unrelated overwrite.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class Bookstore:' packages/ai-parrot/src/parrot/knowledge/bookstore/library.py)
# Container/attachment anchor: class Bookstore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179; merge scoped edits, never replace the whole container.
async def add_book(self, file_path: str | Path, scope: str = "project",
                   title: Optional[str] = None, authors: Optional[list[str]] = None,
                   topics: Optional[list[str]] = None, force: bool = False, *,
                   relate: bool = False) -> tuple[BookCard, str]:
    """Serialize source identity and publication; preserve graph only with equal hash and TOC."""
    # FILL IN: retain format-specific ingest/manual carding and implement ordered locks,
    # identity revalidation, preservation predicate and failure boundaries; AC-1..AC-4.
    raise NotImplementedError

# FILL IN: update _all_taken_slugs to include active staging base IDs for allocation.
# Why: a new import reserves its slug before the final catalog card exists (AC-1).
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` (MODIFY)

```python
# Dependency-created file from TASK-5429; absent at base, so no fabricated grep count.
# Planned attachment anchor: async def test_concurrent_scope_open(tmp_path: Path) -> None:
# Expected occurrences after the prerequisite lands: 1; run grep -cF then, not claimed measured now.
# Append the scoped tests below; preserve every predecessor test.
# Append to the dependency-created test module; preserve its initialization/recovery tests.
@pytest.mark.asyncio
async def test_same_heading_changed_bytes_invalidates_graph(tmp_path: Path) -> None:
    """A stable TOC cannot justify retaining relations after content changes."""
    # FILL IN: real temporary book + graph, change body only, reimport and assert invalidation; AC-2.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_two_process_import_lock(tmp_path: Path) -> None:
    """Competing imports cannot silently overwrite or deadlock publication."""
    # FILL IN: bounded subprocess coordination using real locks; assert publication/timeout; AC-1, AC-4.
    raise NotImplementedError

# FILL IN: equal-hash preservation, new slug collision, cancellation and injected publication failures;
# all bounded by AC-1..AC-4, no host corpus or live model.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Concurrent identical sources, changed bytes at the same path, and new slug collisions serialize or time out clearly without unrelated overwrite.
- [ ] AC-2: Equal known source hash and TOC preserve graph and community; either mismatch or unknown hash invalidates only after successful rename/upsert.
- [ ] AC-3: Ingest failure or cancellation preserves old tree/card/graph and cleans staging; post-rename catalog failure leaves live content available for doctor.
- [ ] AC-4: Real rename completes without reentering the destination lock; timeout acquisition is bounded and add-folder can report/continue failures.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5430` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Populated by the task finalizer after implementation, validation and the exact implementation commit.
