# TASK-3887: PageIndex rename tool with rollback and cache consistency

**Feature**: FEAT-615 — Bookstore re-index via staging tree + atomic PageIndex rename
**Spec**: `sdd/specs/bookstore-reindex-atomic-swap.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3886
**Assigned-to**: unassigned

## Context

Implement spec M2 as an exposed LLM tool with overwrite=False default, rollback, cache invalidation, embedding invalidation and OKF reprojection. Export the private module constant _REPLACED_MARKER for the bookstore.

## Scope

Implement spec M2 as an exposed LLM tool with overwrite=False default, rollback, cache invalidation, embedding invalidation and OKF reprojection. Export the private module constant _REPLACED_MARKER for the bookstore.

**NOT in scope**: Other feature modules, cross-process locking, global delete_tree cleanup changes, dependencies or shared test configuration changes.

**Parallelism**: Consumes JSONTreeStore.rename and NodeContentStore.rename_tree from TASK-3886. Owns toolkit.py and test_toolkit.py; no overlapping writers.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | PageIndex rename tool with rollback and cache consistency |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | Focused regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against current dev source; recheck after dependencies land.

### Verified Imports

```python
import secrets  # standard library; add to toolkit.py
from typing import Any
import pytest
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
```

Standard-library additions need no dependency. pytest is already declared in the workspace; existing module imports were reread.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:50`: `class PageIndexToolkit(AbstractToolkit):`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:177`: `def _load_tree(self, tree_name: str) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:221`: `def _project_okf_sidecars(self, tree_name: str, tree: dict[str, Any]) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:362`: `async def _batch(self, tree_name: str):`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:398`: `async def delete_tree(self, tree_name: str) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:410`: `async def get_tree(self, tree_name: str) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py:23`: `class JSONTreeStore:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:110`: `def _cache_evict_tree(self, tree_name: str) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py:330`: `def invalidate_tree(self, tree_name: str) -> None:`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:547`: `def _generate_tools(self) -> None:`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:635`: `def list_tool_names(self) -> list[str]:`

### Does NOT Exist

rename_tree and _REPLACED_MARKER are created here. Store rename methods arrive from TASK-3886. NodeEmbeddingStore.rename_tree does not exist: invalidate and rebuild. No lock layer exists.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._load_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._project_okf_sidecars",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._batch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.delete_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.get_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore._cache_evict_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore.invalidate_tree",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._generate_tools",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.list_tool_names"
  ]
}
```

## Implementation Notes

Use existing toolkit fixture and mocks. Extend generated tool discovery coverage with the prefixed name. Parametrize failure injection across JSON/content backup and publish moves, and test no-sidecar trees. Add invalid-name, same-name, missing-source, long valid name, embedding invalidation and stale destination OKF cache coverage. Existing best-effort projection and delete_tree embeddings limitation remain as described in spec §7.

No Delegation Contract: test bodies and failure branches still require implementation judgment. Blueprint gaps are planning instructions; completed code must contain no placeholders.

## Implementation Blueprint

### Steps (in order)

1. Define _REPLACED_MARKER once and add the documented public async rename_tree — normal AbstractToolkit discovery exposes pageindex_rename_tree.
2. Validate names, source, src != dst, both batch depths and overwrite before moving anything — avoid destructive refusals.
3. Track successful individual moves and compensate failures, including a failure midway through moving destination to backup — rollback must restore the original destination JSON and content together.
4. Invalidate source embedding matrix before its directory moves; move content before publishing source JSON at destination — readers must not load new JSON against old content.
5. Evict caches for every affected name and reproject destination OKF sidecars after commit — avoid old search engines, loaders or frontmatter URIs.
6. Test each move boundary and tool discovery with temporary trees — expose partial-move defects without external services.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)

- `_MAX_TREES_HARD_CAP = 10` — packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:47, occurrences: 1 (verified with `grep -F -c`).
- `    tool_prefix = "pageindex"` — packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:86, occurrences: 1 (verified with `grep -F -c`).
- `    async def get_tree(self, tree_name: str) -> dict[str, Any]:` — packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:410, occurrences: 1 (verified with `grep -F -c`).

```python
# Add import secrets with standard-library imports.
# Add near _MAX_TREES_HARD_CAP (module scope).
_REPLACED_MARKER = "--replaced-"

# Keep tool_prefix = "pageindex"; do not exclude rename_tree.
# Insert BEFORE get_tree, at class indentation.
async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Rename a tree and its sidecars, optionally replacing the destination.

    Args:
        src: Existing filesystem-safe tree name.
        dst: New filesystem-safe tree name, distinct from src.
        overwrite: Replace an existing destination when True; defaults to False.

    Returns:
        Source, destination and whether a destination was replaced.

    Raises:
        KeyError: Source tree does not exist.
        ValueError: Invalid names, identical names, an open batch, or a
            destination collision without overwrite.
    """
    # FILL IN: guards and backup name respecting 128-character store limit — AC1.
    # FILL IN: journal individual moves, compensate partial failures — AC2.
    # FILL IN: invalidate embeddings, commit move, cleanup, caches, projection — AC3/AC4.
    # FILL IN: return {"src": src, "dst": dst, "replaced": replaced} — AC1.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` (MODIFY)

- `def _adapter() -> MagicMock:` — packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py:14, occurrences: 1 (verified with `grep -F -c`).

```python
# Append module-level tests after existing definitions; retain existing fixtures/imports.
@pytest.mark.asyncio
async def test_rename_tree_basic(toolkit: PageIndexToolkit) -> None:
    """Move tree and sidecars and search under the new name."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_refuses_existing_dst_without_overwrite(toolkit: PageIndexToolkit) -> None:
    """Reject collisions without mutation."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_overwrite_replaces_and_removes_backup(toolkit: PageIndexToolkit) -> None:
    """Replace old content and remove backup JSON."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_overwrite_rolls_back_on_failure(toolkit: PageIndexToolkit) -> None:
    """Fault-inject each move boundary and restore destination."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_invalidates_search_engine_cache(toolkit: PageIndexToolkit) -> None:
    """Never return old destination search results."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_reprojects_okf_sidecars(toolkit: PageIndexToolkit) -> None:
    """Reproject enriched frontmatter to destination URI."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_exposed_as_tool(toolkit: PageIndexToolkit) -> None:
    """Discover pageindex_rename_tree with safe overwrite default."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

@pytest.mark.asyncio
async def test_rename_tree_refuses_inside_batch(toolkit: PageIndexToolkit) -> None:
    """Reject a batch open for either endpoint."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.

## Acceptance Criteria

- [ ] AC1: rename_tree(src, dst, *, overwrite=False) returns {"src": src, "dst": dst, "replaced": bool}; invalid names, same name, batch participation or occupied destination without overwrite raise ValueError; absent source raises KeyError.
- [ ] AC2: Overwrite backs up destination JSON first, content second; publishes source content first, JSON second; restores destination after a failed move without stale caches or lost original bytes.
- [ ] AC3: Success drops source/destination/backup tree, search and content caches; stale OKF toolkit objects are not reused; destination OKF sidecar URIs use dst.
- [ ] AC4: Invalidate source per-tree embedding matrix/order before moving content, preserve global embedding tier, and best-effort delete backup with logging.
- [ ] AC5: pageindex_rename_tree is present in list_tool_names and its generated schema accepts src, dst and optional overwrite=False. Do not add it to exclude_tools.
- [ ] Run black (120 columns) and ruff check on touched Python files; retain existing unrelated formatting. Store validation logs in artifacts/logs/.

## Validation Commands

Activate the project venv and export `PYTHONPATH=packages/ai-parrot/src` before running these commands.

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py -q`

## Test Specification

Use existing toolkit fixture and mocks. Extend generated tool discovery coverage with the prefixed name. Parametrize failure injection across JSON/content backup and publish moves, and test no-sidecar trees. Add invalid-name, same-name, missing-source, long valid name, embedding invalidation and stale destination OKF cache coverage. Existing best-effort projection and delete_tree embeddings limitation remain as described in spec §7.

## Agent Instructions

1. Use `$sdd-start TASK-3887` to provision the feature worktree. Never implement on dev.
2. Read the spec and check dependencies are done in `sdd/tasks/index/bookstore-reindex-atomic-swap.json`.
3. Reverify contracts, set in-progress state and implement only declared files.
4. Complete all blueprint gaps, run file-scoped validations and commit scoped code.
5. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the implementation HEAD; it owns the completion note and active-to-completed move. Commit SDD state separately. Do not manually close the ledger issue; FEAT-615 closeout owns that evidence.

## Completion Note

Pending; populated by finalize_task after verified implementation.
