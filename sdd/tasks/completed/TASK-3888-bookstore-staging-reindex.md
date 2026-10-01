# TASK-3888: Bookstore staging swap and reserved-tree recovery

**Feature**: FEAT-615 — Bookstore re-index via staging tree + atomic PageIndex rename
**Spec**: `sdd/specs/bookstore-reindex-atomic-swap.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3887
**Assigned-to**: unassigned

## Context

Implement spec M3 across all ingest formats: stage creation, ingest, tree read and card drafting; publish only after a card is ready; invalidate graph and content LRU after swap. Recover reserved trees on the next ingest with a fixed 3600-second stale-staging threshold.

## Scope

Implement spec M3 across all ingest formats: stage creation, ingest, tree read and card drafting; publish only after a card is ready; invalidate graph and content LRU after swap. Recover reserved trees on the next ingest with a fixed 3600-second stale-staging threshold.

**NOT in scope**: Other feature modules, cross-process locking, global delete_tree cleanup changes, dependencies or shared test configuration changes.

**Parallelism**: Calls PageIndexToolkit.rename_tree and imports _REPLACED_MARKER created by TASK-3887. Owns library.py and test_library.py, including their local store/book_md fixtures.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Bookstore staging swap and reserved-tree recovery |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | Focused regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against current dev source; recheck after dependencies land.

### Verified Imports

```python
import secrets  # standard library; add to library.py
import time  # standard library; mtime age comparison
from pathlib import Path
from typing import Any, Optional
import pytest
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, _REPLACED_MARKER  # marker supplied by TASK-3887
from parrot.knowledge.pageindex.content_store import NodeContentStore
```

Standard-library additions need no dependency. pytest is already declared in the workspace; existing module imports were reread.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:168`: `class Bookstore:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:223`: `def _toolkit(self, scope: str) -> PageIndexToolkit:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:234`: `def _content_store(self, scope: str) -> NodeContentStore:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:242`: `def _all_taken_slugs(self) -> set[str]:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:923`: `async def add_book(self, file_path: str | Path, scope: str='project', title: Optional[str]=None, authors: Optional[list[str]]=None, topics: Optional[list[str]]=None, force: bool=False, *, relate: bool=False) -> tuple[BookCard, str]:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1105`: `async def _draft_card(self, path: Path, tree_name: str, scope: str, doc_description: str, toc_digest: str, toc_entries: list) -> CardDraft:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1275`: `def _invalidate_graph(self, book_id: str) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:50`: `class PageIndexToolkit(AbstractToolkit):`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197`: `def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:`
- `packages/ai-parrot/tests/knowledge/bookstore/test_library.py:34`: `def store(locations, fake_adapter) -> Bookstore:`
- `packages/ai-parrot/tests/knowledge/bookstore/test_library.py:27`: `def book_md(tmp_path) -> Path:`
- `packages/ai-parrot/tests/knowledge/bookstore/test_library.py:19`: `def locations(tmp_path) -> list[LibraryLocation]:`

### Does NOT Exist

Bookstore.reindex_book does not exist: modify add_book. _staging_tree_name, _sweep_reserved_trees and _is_reserved_tree_name are new. store/book_md are local to test_library.py, not conftest.py. No concurrency lock is provided.

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
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._toolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._content_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._all_taken_slugs",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._draft_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._invalidate_graph",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore.loader_for",
    "sym:packages/ai-parrot/tests/knowledge/bookstore/test_library.py#store",
    "sym:packages/ai-parrot/tests/knowledge/bookstore/test_library.py#book_md",
    "sym:packages/ai-parrot/tests/knowledge/bookstore/test_library.py#locations"
  ]
}
```

## Implementation Notes

The seven tree_name=slug occurrences must be disambiguated by their enclosing calls: import_pdf, two insert_markdown calls (md/docx), insert_content, insert_ebook and _draft_card become staging; BookCard remains slug. Read the full surrounding call blocks before editing. Reuse local store/book_md/locations and conftest fake_adapter. Adapt the existing test_reindex_invalidates_relations_and_communities setup to snapshot graph rows before forcing insert_markdown failure. Add card-draft and swap failure cases, backup-present/live-present sweep, first-add success and unchanged-byte recovery. Do not broaden delete_tree to fix the separately excluded embeddings-directory cleanup issue.

No Delegation Contract: test bodies and failure branches still require implementation judgment. Blueprint gaps are planning instructions; completed code must contain no placeholders.

## Implementation Blueprint

### Steps (in order)

1. Add reserved-name helpers and import the shared replacement marker — prevent naming drift between toolkit and bookstore.
2. Sweep the target scope before the skipped-ingest early return and before choosing slugs — crash recovery must also work when bytes are unchanged.
3. Replace destructive updated-path deletion with staging allocation; keep existing identity and manual card preservation — failures must leave the old book usable.
4. Include create, ingest, tree read, draft and swap in the staging cleanup boundary — carding errors otherwise leak reserved trees.
5. Publish via rename_tree, then invalidate the updated graph, drop the scope content-store cache and upsert the card — preserve old graph until the replacement is usable.
6. Add recovery and failed-ingest tests using local fixtures — assert byte/row identity and warmed-cache reads, not only return status.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

- `                taken |= {p.stem for p in loc.trees_dir.glob("*.json")}` — packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:256, occurrences: 1 (verified with `grep -F -c`).
- `        if status == "updated":` — packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:982, occurrences: 1 (verified with `grep -F -c`).
- `        tree = await toolkit.get_tree(slug)` — packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1043, occurrences: 1 (verified with `grep -F -c`).
- `        catalog.upsert(card)` — packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1100, occurrences: 1 (verified with `grep -F -c`).
- `            tree_name=slug,` — packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1000, occurrences: 7 (verified with `grep -F -c`).

```python
# Add standard-library secrets and time imports.
# Extend existing toolkit import; _REPLACED_MARKER comes from TASK-3887.
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, _REPLACED_MARKER

_STAGING_MARKER = "--staging-"
_STAGING_MAX_AGE_S = 3600

def _is_reserved_tree_name(name: str) -> bool:
    """Identify reserved staging/replacement names that cannot be book slugs."""
    # FILL IN: recognize reserved names consistently — AC3/AC4.

# Add private methods in Bookstore before add_book.
def _staging_tree_name(self, slug: str) -> str:
    """Return a temporary tree name using an eight-hex-character suffix."""
    return f"{slug}{_STAGING_MARKER}{secrets.token_hex(4)}"

async def _sweep_reserved_trees(self, scope: str) -> None:
    """Restore interrupted swaps and sweep staging trees older than one hour."""
    # FILL IN: target-scope snapshot, replacement recovery, mtime threshold — AC3.

# MODIFY _all_taken_slugs: retain catalog slugs; filter reserved disk names.
# MODIFY add_book: preserve its full existing signature and card-building logic.
# FILL IN: sweep before early return; select live slug without deleting it — AC1/AC5.
# FILL IN: create staging inside cleanup try; use staging for all ingest calls — AC1.
# Disambiguated original call contexts (six ingest/draft sites change; card stays live):
# result = await toolkit.import_pdf(
#     tree_name=slug,
#     pdf_path=str(path),
# await toolkit.insert_markdown(
#     tree_name=slug,
#     markdown=await asyncio.to_thread(path.read_text, encoding="utf-8"),
# await toolkit.insert_content(
#     tree_name=slug,
#     content=await asyncio.to_thread(path.read_text, encoding="utf-8"),
# await toolkit.insert_markdown(
#     tree_name=slug,
#     markdown=markdown,
# await toolkit.insert_ebook(
#     tree_name=slug,
#     sections=sections,
# draft = await self._draft_card(
#     path=path,
#     tree_name=slug,
# Card context stays unchanged: toc=toc_entries, tree_name=slug, scope=scope.
# FILL IN: get_tree(staging), _draft_card(tree_name=staging), BookCard(tree_name=slug).
# FILL IN: await toolkit.rename_tree(staging, slug, overwrite=status == "updated").
# FILL IN: except cleans staging only, preserves original exception — AC1.
# FILL IN: after swap invalidate graph for updated, pop content store, catalog.upsert.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` (MODIFY)

- `def locations(tmp_path) -> list[LibraryLocation]:` — packages/ai-parrot/tests/knowledge/bookstore/test_library.py:19, occurrences: 1 (verified with `grep -F -c`).

```python
# Append module-level tests after existing definitions; retain existing fixtures/imports.
@pytest.mark.asyncio
async def test_reindex_failed_ingest_keeps_old_book(store: Bookstore, book_md: Path) -> None:
    """Preserve old JSON, sidecars, card and graph on failed ingest."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_reindex_success_swaps_tree_same_book_id(store: Bookstore, book_md: Path) -> None:
    """Keep identity and evict warmed content caches."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_add_failed_ingest_leaves_no_tree(store: Bookstore, book_md: Path) -> None:
    """Leave no staging or card after a first-add failure."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_sweep_restores_orphaned_replaced_tree(store: Bookstore, book_md: Path) -> None:
    """Restore backup when its live tree is absent."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_sweep_deletes_stale_staging_keeps_fresh(store: Bookstore, book_md: Path) -> None:
    """Honor the fixed one-hour threshold."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_all_taken_slugs_ignores_reserved_names(store: Bookstore, book_md: Path) -> None:
    """Ignore staging and replacement names."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_reindex_roundtrip_markdown(store: Bookstore, book_md: Path) -> None:
    """Read and search changed markdown under the same ID."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.

## Acceptance Criteria

- [ ] AC1: Any failure before swap completion cleans the current staging tree and preserves prior tree JSON/sidecars, card, relations, judgements and communities; a failed first add leaves no card or live tree.
- [ ] AC2: Success keeps book_id == tree_name == slug, uses staging for all ingest and _draft_card reads, invalidates updated graph only after rename and drops self._content_stores[scope] before future reads.
- [ ] AC3: Sweep restores replaced trees only if live JSON is absent; otherwise deletes replaced trees; removes staging JSON older than 3600 seconds and retains fresh staging.
- [ ] AC4: Reserved names never enter _all_taken_slugs; no reserved JSON tree remains from the current completed/failed add; unrelated fresh staging is retained.
- [ ] AC5: Markdown roundtrip reflects new ToC, section and search content under the same ID; skipped and manual-card preservation behaviors stay green.
- [ ] Run black (120 columns) and ruff check on touched Python files; retain existing unrelated formatting. Store validation logs in artifacts/logs/.

## Validation Commands

Activate the project venv and export `PYTHONPATH=packages/ai-parrot/src` before running these commands.

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

## Test Specification

The seven tree_name=slug occurrences must be disambiguated by their enclosing calls: import_pdf, two insert_markdown calls (md/docx), insert_content, insert_ebook and _draft_card become staging; BookCard remains slug. Read the full surrounding call blocks before editing. Reuse local store/book_md/locations and conftest fake_adapter. Adapt the existing test_reindex_invalidates_relations_and_communities setup to snapshot graph rows before forcing insert_markdown failure. Add card-draft and swap failure cases, backup-present/live-present sweep, first-add success and unchanged-byte recovery. Do not broaden delete_tree to fix the separately excluded embeddings-directory cleanup issue.

## Agent Instructions

1. Use `$sdd-start TASK-3888` to provision the feature worktree. Never implement on dev.
2. Read the spec and check dependencies are done in `sdd/tasks/index/bookstore-reindex-atomic-swap.json`.
3. Reverify contracts, set in-progress state and implement only declared files.
4. Complete all blueprint gaps, run file-scoped validations and commit scoped code.
5. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the implementation HEAD; it owns the completion note and active-to-completed move. Commit SDD state separately. Do not manually close the ledger issue; FEAT-615 closeout owns that evidence.

## Completion Note

Pending; populated by finalize_task after verified implementation.

## Completion Note

Merged by sdd-worker (gpt-5.6-terra, 1 attempt). Review fix 6ebbaba34e2543187b01c5a8366a103defb44ea4: test_reindex_roundtrip_markdown used a too-short section body, so the markdown parser thinned the node away; lengthened the body. bookstore+pageindex suite: only baseline failures remain (test_adapter, test_okf_ontology, test_integration_graph).
