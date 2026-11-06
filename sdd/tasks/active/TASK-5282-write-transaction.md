# TASK-5282: WriteTransaction: copy-on-write candidate and the publish sequence

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5276, TASK-5277, TASK-5278, TASK-5279
**Assigned-to**: unassigned

---

## Context

Implements the transaction half of spec §3 **Module 2** and the publish sequence of spec §2
Overview (steps 1-6 and 8; step 7 — the in-process swap — belongs to the toolkit, TASK-5283).
A `WriteTransaction` holds a deep copy of a tree, stages body blobs, and publishes them with
one atomic JSON replace under the per-tree lock.

---

## Scope

- Add `WriteTransaction` to `generation.py` with the constructor fixed by the spec skeleton.
- Capture the **base generation** from `base_tree` at construction and never read it back from
  `self.tree` — *because* `rename_tree` (TASK-5286) replaces `txn.tree` with another tree's content
  while the base generation must stay the destination's.
- `set_body`, `drop_body`, `live_body_keys`, `publish`; attribute `published_signature` set by publish.
- Stale rule (step 2): with the lock held, `cur = store.signature(name)`; if `cur != base_signature`
  then stale unless both generations are known and equal (`store.read_generation(name) ==
  base_generation.id`). `base_signature is None` means "the tree must not exist": any existing file is stale.
- A transaction publishes at most once (second call → `RuntimeError`).
- Export `GenerationInfo`, `StaleGenerationError` and `TreeLockTimeout` from `knowledge/pageindex/__init__.py`.
- Extend `test_generation.py`.

**NOT in scope**: the toolkit `_write`/`_mutate` and cache swap (TASK-5283), legacy-body migration (TASK-5283).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py` | MODIFY | WriteTransaction |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | Export three names |
| `packages/ai-parrot/tests/knowledge/pageindex/test_generation.py` | MODIFY | Transaction tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.locks import TreeLockTimeout, tree_lock      # created by TASK-5276
from parrot.knowledge.pageindex.store import JSONTreeStore                   # verified: store.py:23
from parrot.knowledge.pageindex.content_store import NodeContentStore       # verified: content_store.py:38
from parrot.knowledge.pageindex.utils import structure_to_list              # verified: okf/projection.py:30
```

### Existing Signatures to Use
```python
# knowledge/pageindex/store.py (after TASK-5277)
    def save(self, tree_name, tree) -> tuple[int, int]      # fsync + os.replace; returns the new signature
    def signature(self, tree_name) -> tuple[int, int] | None
    def read_generation(self, tree_name) -> Optional[int]

# knowledge/pageindex/content_store.py (after TASK-5279)
    def bodies_dir(self, tree_name) -> Path
    def body_path(self, tree_name, key) -> Path
    def save_body(self, tree_name, key, markdown) -> Path   # atomic, idempotent
    def sweep_unreferenced(self, tree_name, tree, *, max_age_s) -> int

# knowledge/pageindex/generation.py (after TASK-5278)
GenerationInfo, BodyRef, PublishReport, StaleGenerationError,
flatten_concept_id(concept_id), body_sha16(markdown), generation_of(tree), next_generation(base), ensure_concept_ids(tree)

# knowledge/pageindex/locks.py (after TASK-5276)
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]
class TreeLockTimeout(TimeoutError)

# knowledge/pageindex/__init__.py
__all__ = [                                                  # line 24 (18 names, lines 24-43)
```

### Does NOT Exist
- ~~`WriteTransaction`~~ — added here
- ~~an `on_published` callback~~ — the toolkit reads `txn.published_signature` after `publish()` instead
- ~~`TreeLockTimeout` defined in `generation.py`~~ — it lives in `locks.py`; re-export it from the package `__init__`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_generation.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Order inside `publish()` is the spec's: lock → stale check → validate → write staged blobs
  (`asyncio.to_thread`) and `fsync` the `bodies/` directory → `projector(tree, name)` → set
  `tree["generation"] = next_generation(base).model_dump()` and `store.save` → sweep → release.
- Any exception before `store.save` leaves the tree JSON untouched (blobs already written are
  orphans the sweep removes later).
- `projector: Callable[[dict[str, Any], str], bool]` returns whether OKF sidecars were projected;
  its exceptions propagate (strict projection).
- Validation (step 3): `ensure_concept_ids(self.tree)`; every `body_ref` parses with
  `BodyRef.parse` and is either staged or present at `content_store.body_path(...)`; otherwise
  `ValueError` naming the node.
- `set_body` calls `ensure_concept_ids(self.tree)` when the node has no `concept_id`, then stages
  `key = f"{flatten_concept_id(cid)}.{body_sha16(markdown)}"` and sets `node["body_ref"] = key`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the class below to `generation.py` (after `ensure_concept_ids`) — *why*: fixed by spec M2.
2. Fill `publish()` in the order of Key Constraints — *why*: the order is the crash-safety argument.
3. Export the three names from the package — *why*: spec §5 last criterion.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py` (MODIFY — append)
```python
import asyncio
import copy
import os
from pathlib import Path
from typing import Callable

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.locks import TreeLockTimeout, tree_lock  # noqa: F401 — re-exported
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import structure_to_list


class WriteTransaction:
    """Copy-on-write unit of work for one tree; created only by ``PageIndexToolkit``."""

    def __init__(self, *, tree_name: str, base_tree: dict[str, Any], base_signature: tuple[int, int] | None,
                 store: JSONTreeStore, content_store: NodeContentStore, storage_dir: Path,
                 lock_timeout_s: float, grace_s: int, projector: Callable[[dict[str, Any], str], bool]) -> None:
        self.tree_name = tree_name
        self.tree: dict[str, Any] = copy.deepcopy(base_tree)
        self.base_generation: Optional[GenerationInfo] = generation_of(base_tree)
        self.base_signature = base_signature
        self.published_signature: tuple[int, int] | None = None
        self._store, self._content, self._storage_dir = store, content_store, Path(storage_dir)
        self._lock_timeout_s, self._grace_s, self._projector = lock_timeout_s, grace_s, projector
        self._staged: dict[str, str] = {}
        self._published = False

    def set_body(self, node: dict[str, Any], markdown: str) -> BodyRef:
        """Stage ``markdown`` for ``node`` (assigning ``concept_id`` when missing) and set ``node['body_ref']``."""
        # FILL IN — bounded by Key Constraints (set_body)
        raise NotImplementedError

    def drop_body(self, node: dict[str, Any]) -> None:
        """Remove ``body_ref`` from ``node``; the blob is left for the sweep."""
        node.pop("body_ref", None)

    def live_body_keys(self) -> set[str]:
        """Every ``body_ref`` in ``self.tree``."""
        return {n["body_ref"] for n in structure_to_list(self.tree.get("structure", [])) if n.get("body_ref")}

    async def publish(self) -> PublishReport:
        """Steps 1-6 and 8 of spec §2. Raises TreeLockTimeout, StaleGenerationError, ValueError, or
        whatever the projector raises; in every case the tree JSON on disk is unchanged."""
        if self._published:
            raise RuntimeError("transaction already published")
        async with tree_lock(self._storage_dir, self.tree_name, timeout=self._lock_timeout_s):
            # FILL IN: stale check (Scope rule), validation, blob writes + dir fsync, projector,
            # generation stamp + store.save (→ self.published_signature), sweep — Key Constraints order
            raise NotImplementedError
```
**Why this shape**: the constructor is the spec skeleton; `base_generation` and
`published_signature` are the two pieces of state the toolkit and `rename_tree` need.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '__all__ = [' __init__.py)
# BEFORE `__all__ = [` (verified: __init__.py:24) add:
from .generation import GenerationInfo, StaleGenerationError
from .locks import TreeLockTimeout
# and append "GenerationInfo", "StaleGenerationError", "TreeLockTimeout" to __all__.
```

### FILL IN checklist
- [ ] `set_body`; Key Constraints
- [ ] `publish` stale check; AC-2
- [ ] `publish` validation and blob writes; AC-3
- [ ] `publish` projector + save + sweep; AC-1, AC-4

---

## Acceptance Criteria

- [ ] AC-1: first publish of a new tree writes `generation.id == 1`; the next publish from that state writes 2 with `parent == 1`.
- [ ] AC-2: an external rewrite of the JSON between construction and `publish()` raises `StaleGenerationError` and leaves the file byte-identical; `base_signature=None` with an existing file is stale.
- [ ] AC-3: a `body_ref` that is neither staged nor on disk raises `ValueError`; `set_body` assigns a missing `concept_id`.
- [ ] AC-4: a projector that raises, or an `os.replace` failure on the tree JSON, leaves the on-disk JSON unchanged; staged blobs may remain.
- [ ] AC-5: `from parrot.knowledge.pageindex import GenerationInfo, StaleGenerationError, TreeLockTimeout` works.
- [ ] AC-6: a second `publish()` raises `RuntimeError`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation.py -q`

---

## Test Specification

```python
# add to packages/ai-parrot/tests/knowledge/pageindex/test_generation.py
import pytest
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.generation import StaleGenerationError, WriteTransaction
from parrot.knowledge.pageindex.store import JSONTreeStore


def _txn(tmp_path, name, base, sig, projector=lambda t, n: False):
    return WriteTransaction(tree_name=name, base_tree=base, base_signature=sig,
                            store=JSONTreeStore(tmp_path), content_store=NodeContentStore(tmp_path),
                            storage_dir=tmp_path, lock_timeout_s=1.0, grace_s=3600, projector=projector)


@pytest.mark.asyncio
async def test_publish_increments_generation(tmp_path):
    txn = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    node = {"node_id": "0001", "title": "Intro"}
    txn.tree["structure"].append(node)
    txn.set_body(node, "hello")
    report = await txn.publish()
    assert report.generation == 1
    assert JSONTreeStore(tmp_path).read_generation("t") == 1


@pytest.mark.asyncio
async def test_publish_rejects_stale_base(tmp_path):
    # FILL IN: publish gen 1; open txn with that base; rewrite JSON externally; publish → StaleGenerationError
    ...


@pytest.mark.asyncio
async def test_publish_projection_failure_aborts(tmp_path):
    # FILL IN: projector raises RuntimeError → JSON unchanged
    ...


@pytest.mark.asyncio
async def test_publish_replace_failure_keeps_old_generation(tmp_path, monkeypatch):
    # FILL IN: monkeypatch parrot.knowledge.pageindex.store.os.replace to raise once
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-generation-publication --feature-id FEAT-831`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-generation-publication.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
7. **Verify** — run the Validation Commands and `ruff check` on the files you touched.
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `parrot sdd task close TASK-5282 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
