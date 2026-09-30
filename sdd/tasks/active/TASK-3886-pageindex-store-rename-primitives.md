# TASK-3886: PageIndex store rename primitives

**Feature**: FEAT-615 — Bookstore re-index via staging tree + atomic PageIndex rename
**Spec**: `sdd/specs/bookstore-reindex-atomic-swap.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec M1: validated, non-overwriting JSON and whole-directory rename primitives, including sidecar-cache eviction. Preserve existing CRUD behavior.

## Scope

Implement spec M1: validated, non-overwriting JSON and whole-directory rename primitives, including sidecar-cache eviction. Preserve existing CRUD behavior.

**NOT in scope**: Other feature modules, cross-process locking, global delete_tree cleanup changes, dependencies or shared test configuration changes.

**Parallelism**: Independent store primitives; owns store.py, content_store.py and their two test files. No shared mutable test configuration.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` | MODIFY | PageIndex store rename primitives |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | MODIFY | PageIndex store rename primitives |
| `packages/ai-parrot/tests/knowledge/pageindex/test_store.py` | MODIFY | Focused regression coverage |
| `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` | MODIFY | Focused regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against current dev source; recheck after dependencies land.

### Verified Imports

```python
import os  # standard library; existing in store.py, add in content_store.py
from pathlib import Path
import pytest
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.content_store import NodeContentStore
```

Standard-library additions need no dependency. pytest is already declared in the workspace; existing module imports were reread.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py:23`: `class JSONTreeStore:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py:42`: `def _path_for(self, tree_name: str) -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py:91`: `def delete(self, tree_name: str) -> bool:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:37`: `class NodeContentStore:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:82`: `def _tree_dir(self, tree_name: str) -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:110`: `def _cache_evict_tree(self, tree_name: str) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:158`: `def delete_tree(self, tree_name: str) -> int:`

### Does NOT Exist

JSONTreeStore.rename and NodeContentStore.rename_tree do not exist; this task creates them. There is no public NodeContentStore.evict_tree.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore._path_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore.delete",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore._tree_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore._cache_evict_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore.delete_tree"
  ]
}
```

## Implementation Notes

Use temporary filesystem fixtures already in each test file. Prime caches under both names before a move. Include missing-source, destination collision, invalid-name and os.replace failure cases; assert content bytes survive.

No Delegation Contract: test bodies and failure branches still require implementation judgment. Blueprint gaps are planning instructions; completed code must contain no placeholders.

## Implementation Blueprint

### Steps (in order)

1. Add both rename methods using validated paths and os.replace — callers need atomic per-path moves without silent overwrites.
2. Check destination before mutation and move the entire content directory, including embeddings — sidecar-only moves strand data.
3. Add focused failure and cache tests — prove refusals leave bytes unchanged.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` (MODIFY)

- `    def delete(self, tree_name: str) -> bool:` — packages/ai-parrot/src/parrot/knowledge/pageindex/store.py:91, occurrences: 1 (verified with `grep -F -c`).

```python
# Add after the existing delete method.
def rename(self, src: str, dst: str) -> None:
    """Move a tree JSON without overwriting another tree.

    Raises:
        ValueError: A name is invalid.
        FileNotFoundError: Source JSON does not exist.
        FileExistsError: Destination already exists.
    """
    # FILL IN: validated paths, source/destination checks, os.replace — AC1.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` (MODIFY)

- `    def delete_tree(self, tree_name: str) -> int:` — packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:158, occurrences: 1 (verified with `grep -F -c`).

```python
# Add import os beside the standard-library imports.
# Add after the existing delete_tree method.
def rename_tree(self, src: str, dst: str) -> bool:
    """Move all content and evict source/destination cache entries.

    Returns:
        False when the source directory is absent; True after moving it.

    Raises:
        ValueError: A name is invalid.
        FileExistsError: Destination directory already exists.
    """
    # FILL IN: _tree_dir validation, existence checks, os.replace and eviction — AC2/AC3.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/tests/knowledge/pageindex/test_store.py` (MODIFY)

- `def store(tmp_path: Path) -> JSONTreeStore:` — packages/ai-parrot/tests/knowledge/pageindex/test_store.py:14, occurrences: 1 (verified with `grep -F -c`).

```python
# Append module-level tests after existing definitions; retain existing fixtures/imports.
def test_json_store_rename_moves_file(store: JSONTreeStore) -> None:
    """Preserve bytes and remove the old JSON name."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

def test_json_store_rename_refuses_existing_dst(store: JSONTreeStore) -> None:
    """Keep both JSON files intact on collision."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

def test_json_store_rename_invalid_or_missing_source(store: JSONTreeStore) -> None:
    """Reject unsafe names and absent source."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` (MODIFY)

- `def store(tmp_path: Path) -> NodeContentStore:` — packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py:12, occurrences: 1 (verified with `grep -F -c`).

```python
# Append module-level tests after existing definitions; retain existing fixtures/imports.
def test_content_store_rename_tree_moves_dir_and_evicts_cache(store: NodeContentStore) -> None:
    """Move nested content and invalidate both cache names."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

def test_content_store_rename_tree_missing_src_dir_returns_false(store: NodeContentStore) -> None:
    """Treat absent content as a no-op."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.

def test_content_store_rename_tree_refuses_existing_dst(store: NodeContentStore) -> None:
    """Preserve both directories on collision."""
    # FILL IN: setup, operation and assertions — bounded by Test Specification below.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/knowledge/pageindex/test_store.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.

## Acceptance Criteria

- [ ] AC1: JSONTreeStore.rename(src, dst) preserves JSON bytes; missing source raises FileNotFoundError, occupied destination raises FileExistsError, invalid names raise ValueError.
- [ ] AC2: NodeContentStore.rename_tree(src, dst) returns False for no source directory and True after a move; rejects occupied destination; invalidates both names in the LRU.
- [ ] AC3: Whole-directory moves retain nested embeddings and non-markdown files. Failure never removes either pre-existing tree.
- [ ] Run black (120 columns) and ruff check on touched Python files; retain existing unrelated formatting. Store validation logs in artifacts/logs/.

## Validation Commands

Activate the project venv and export `PYTHONPATH=packages/ai-parrot/src` before running these commands.

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py -q`

## Test Specification

Use temporary filesystem fixtures already in each test file. Prime caches under both names before a move. Include missing-source, destination collision, invalid-name and os.replace failure cases; assert content bytes survive.

## Agent Instructions

1. Use `$sdd-start TASK-3886` to provision the feature worktree. Never implement on dev.
2. Read the spec and check dependencies are done in `sdd/tasks/index/bookstore-reindex-atomic-swap.json`.
3. Reverify contracts, set in-progress state and implement only declared files.
4. Complete all blueprint gaps, run file-scoped validations and commit scoped code.
5. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the implementation HEAD; it owns the completion note and active-to-completed move. Commit SDD state separately. Do not manually close the ledger issue; FEAT-615 closeout owns that evidence.

## Completion Note

Pending; populated by finalize_task after verified implementation.
