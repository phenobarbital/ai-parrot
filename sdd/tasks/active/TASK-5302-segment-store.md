# TASK-5302: Immutable revision store and package exports

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5300
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3**. A document revision is one immutable JSON file,
`<storage_dir>/<tree>/segments/<doc_id>.<revision>.json`. The transaction (TASK-5303) writes
it; the read tools (TASK-5309) load it; the sweep removes superseded ones after the FEAT-831
grace period. Also exports the public FEAT-840 names from `knowledge/pageindex/__init__.py`.

---

## Scope

- Create `knowledge/pageindex/segment_store.py` with `SegmentStore` (spec §2 *New Public Interfaces*).
- Add `Segment`, `DocumentRevision`, `SegmentAddress`, `ReadResult`, `SegmentStore` to
  `knowledge/pageindex/__init__.py` (imports + `__all__`).
- Write `tests/knowledge/pageindex/test_segment_store.py`.

**NOT in scope**: staging in the transaction (TASK-5303), `NodeContentStore.delete_tree` (TASK-5310).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py` | CREATE | Revision files |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | Public exports |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.content_store import _atomic_write   # verified: content_store.py:62
from parrot.knowledge.pageindex.utils import structure_to_list        # verified: utils.py:294
from parrot.knowledge.pageindex.segments import DocumentRevision      # created by TASK-5300
```

### Existing Signatures to Use
```python
# knowledge/pageindex/content_store.py
_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")                 # line 41
def _atomic_write(path: Path, text: str) -> None                       # line 62 — mkdir parents, temp + fsync + os.replace
class NodeContentStore:
    def mark_superseded(self, tree_name, body_keys, node_ids) -> int    # line 305 — PATTERN: os.utime(path, None)
    def sweep_unreferenced(self, tree_name, tree, *, max_age_s) -> int  # line 322 — PATTERN: mtime cutoff, FileNotFoundError tolerated

# knowledge/pageindex/__init__.py
from .locks import TreeLockTimeout                                      # line 24 (last import)
__all__ = [ ... "TreeLockTimeout", ]                                    # lines 26-48 ("TreeLockTimeout", at :47)
```

### Does NOT Exist
- ~~`segment_store.py`, `SegmentStore`, a `segments/` directory~~ — created here
- ~~a revision or document registry~~ anywhere under `knowledge/pageindex/`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#_atomic_write",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Revision files are **immutable**: `save_revision` is a no-op when the file exists; the LRU cache
  (8 parsed revisions, `OrderedDict`) is never invalidated except by `delete_tree` — *because* the
  name contains the content hash.
- Validate `doc_id` (`^[A-Za-z0-9_-]{1,64}$`), `revision` (`^[0-9a-f]{16}$`) and the tree name before
  building any path — *because* names come from tree JSON and tool arguments.
- `live_revisions(tree)` reads `(node["doc_id"], node["revision"])` from every node that has both.
- `sweep_unreferenced` deletes files in `segments/` whose pair is not live and whose mtime is older
  than `max_age_s`; it never touches other files.
- Serialize with `rev.model_dump_json()`; load with `DocumentRevision.model_validate_json`.
- Synchronous API (like `NodeContentStore`): callers use `asyncio.to_thread` where needed.

---

## Implementation Blueprint

### Steps (in order)
1. Create `segment_store.py` from the block below.
2. Fill the method bodies.
3. Add the exports to `__init__.py`.
4. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py` (CREATE)
```python
"""Immutable document-revision files for PageIndex trees (FEAT-840)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Optional

from parrot.knowledge.pageindex.content_store import _atomic_write
from parrot.knowledge.pageindex.segments import DocumentRevision
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger("parrot.knowledge.pageindex.segment_store")

_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{16}$")


class SegmentStore:
    """``<storage_dir>/<tree>/segments/<doc_id>.<revision>.json``, written once, read through an LRU."""

    def __init__(self, storage_dir: str | Path, cache_size: int = 8) -> None:
        self._dir = Path(storage_dir)
        self._cache_size = max(1, int(cache_size))
        self._cache: "OrderedDict[tuple[str, str, str], DocumentRevision]" = OrderedDict()

    def segments_dir(self, tree_name: str) -> Path:
        """Return ``<storage_dir>/<tree_name>/segments``; ValueError on a bad name."""
        if not isinstance(tree_name, str) or not _TREE_NAME_RE.match(tree_name):
            raise ValueError(f"Invalid tree_name {tree_name!r}")
        return self._dir / tree_name / "segments"

    def revision_path(self, tree_name: str, doc_id: str, revision: str) -> Path:
        """Path of one revision file; ValueError on a malformed doc_id or revision."""
        # FILL IN: validate with _DOC_ID_RE/_REVISION_RE — bounded by AC-4
        raise NotImplementedError

    def save_revision(self, tree_name: str, rev: DocumentRevision) -> Path:
        """Write ``rev`` atomically; no-op when the file already exists."""
        # FILL IN — bounded by AC-1
        raise NotImplementedError

    def load_revision(self, tree_name: str, doc_id: str, revision: str) -> Optional[DocumentRevision]:
        """Return the cached/parsed revision, or ``None`` when the file is absent."""
        # FILL IN — bounded by AC-2
        raise NotImplementedError

    def has_revision(self, tree_name: str, doc_id: str, revision: str) -> bool:
        return self.revision_path(tree_name, doc_id, revision).is_file()

    def list_revisions(self, tree_name: str) -> list[tuple[str, str]]:
        """``(doc_id, revision)`` of every file on disk, sorted."""
        # FILL IN
        raise NotImplementedError

    @staticmethod
    def live_revisions(tree: dict[str, Any]) -> set[tuple[str, str]]:
        """Every ``(doc_id, revision)`` named by a node of ``tree``."""
        return {(n["doc_id"], n["revision"]) for n in structure_to_list(tree.get("structure", []))
                if isinstance(n.get("doc_id"), str) and isinstance(n.get("revision"), str)}

    def mark_superseded(self, tree_name: str, pairs: Iterable[tuple[str, str]]) -> int:
        """Restart the grace clock (``os.utime``) of revisions a new generation stopped referencing."""
        # FILL IN — pattern NodeContentStore.mark_superseded (content_store.py:305)
        raise NotImplementedError

    def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int:
        """Delete non-live revision files older than ``max_age_s``; return the count."""
        # FILL IN — bounded by AC-3; evict the removed keys from the cache
        raise NotImplementedError

    def delete_tree(self, tree_name: str) -> int:
        """Remove ``segments/`` for ``tree_name`` and evict its cache entries; return files removed."""
        # FILL IN: count files, shutil.rmtree(ignore_errors=True), evict
        raise NotImplementedError
```
**Why this shape**: mirrors `NodeContentStore` (sync, validated names, same atomic write) so the
transaction can treat revisions exactly like body blobs.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` (MODIFY)
```python
# AFTER — insert below `from .locks import TreeLockTimeout` (verified: __init__.py:24)
# occurrences: 1 (verified: grep -c 'from .locks import TreeLockTimeout' __init__.py)
from .segments import DocumentRevision, ReadResult, Segment, SegmentAddress
from .segment_store import SegmentStore

# AFTER — insert below `    "TreeLockTimeout",` inside __all__ (verified: __init__.py:47)
# occurrences: 1 (verified: grep -c '    "TreeLockTimeout",' __init__.py)
    "Segment",
    "DocumentRevision",
    "SegmentAddress",
    "ReadResult",
    "SegmentStore",
```

### FILL IN checklist
- [ ] `revision_path` validation; bounded by AC-4
- [ ] `save_revision` / `load_revision` with LRU; bounded by AC-1, AC-2
- [ ] `list_revisions`, `mark_superseded`, `sweep_unreferenced`, `delete_tree`; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: `save_revision` writes atomically (temp file cleaned when `os.replace` fails) and a second call does not rewrite the file (mtime unchanged).
- [ ] AC-2: `load_revision` returns an equal model; a missing file returns `None`; a repeated load is served from the cache.
- [ ] AC-3: `sweep_unreferenced` never removes a live revision; removes a non-live one only when older than `max_age_s`.
- [ ] AC-4: `../x` as doc_id or a non-hex revision raises `ValueError` before touching disk.
- [ ] AC-5: `from parrot.knowledge.pageindex import Segment, DocumentRevision, SegmentAddress, ReadResult, SegmentStore` works.
- [ ] `ruff check` on both source files passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py
import os
import time

import pytest

from parrot.knowledge.pageindex import SegmentStore
from parrot.knowledge.pageindex.segments import DocumentRevision, SourceInfo, revision_id, segment_pages


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


def _rev(doc_id="d", text="Hello."):
    segs = segment_pages([(1, text)])
    return DocumentRevision(doc_id=doc_id, revision=revision_id(segs), source=SourceInfo(name="d.pdf", kind="pdf"),
                            created_at="2026-11-07T00:00:00Z", segments=segs)


def test_save_revision_atomic_and_idempotent(tmp_path):
    store = SegmentStore(tmp_path)
    rev = _rev()
    path = store.save_revision("t", rev)
    mtime = path.stat().st_mtime_ns
    store.save_revision("t", rev)
    assert path.stat().st_mtime_ns == mtime
    assert store.load_revision("t", "d", rev.revision) == rev


def test_sweep_revisions_respects_grace(tmp_path):
    # FILL IN: live pair kept; non-live pair kept at max_age_s=3600, removed after os.utime into the past
    ...


def test_revision_path_rejects_bad_names(tmp_path):
    # FILL IN — AC-4
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5302 — Immutable revision store and package exports`), then close with
   `parrot sdd task close TASK-5302 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
