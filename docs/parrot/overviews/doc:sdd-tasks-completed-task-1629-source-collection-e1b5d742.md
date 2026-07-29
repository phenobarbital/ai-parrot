---
type: Wiki Overview
title: 'TASK-1629: Source Collection Manager'
id: doc:sdd-tasks-completed-task-1629-source-collection-manager-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the "Raw Sources" layer of Karpathy's 3-layer architecture. Manages
relates_to:
- concept: mod:parrot.knowledge.wiki
  rel: mentions
- concept: mod:parrot.knowledge.wiki.models
  rel: mentions
- concept: mod:parrot.knowledge.wiki.sources
  rel: mentions
---

# TASK-1629: Source Collection Manager

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1627
**Assigned-to**: unassigned

---

## Context

Implements the "Raw Sources" layer of Karpathy's 3-layer architecture. Manages
the source collection: tracks what's been ingested, detects changes via file
hash + mtime (reusing GraphIndex's SQLite `is_stale()` pattern), maintains a
JSON manifest. Implements Spec §3 Module 3.

---

## Scope

- Implement `SourceCollectionManager` class with:
  - `add_source(path) -> SourceManifestEntry` — register a new source, compute hash + mtime
  - `list_sources() -> list[SourceManifestEntry]` — list all tracked sources
  - `get_source(source_id) -> SourceManifestEntry` — get a single source
  - `is_stale(source_id) -> bool` — check if source file changed since last ingest
  - `mark_ingested(source_id, pages_generated)` — update manifest after ingest
  - `remove_source(source_id)` — remove a source from tracking
  - `_compute_hash(path) -> str` — SHA-1 file hash
  - `_load_manifest() / _save_manifest()` — JSON persistence
- Manifest stored as `.manifest.json` in the wiki's sources directory
- Write unit tests

**NOT in scope**: Ingest pipeline (TASK-1632), toolkit API (TASK-1633)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | CREATE | SourceCollectionManager |
| `tests/knowledge/wiki/test_sources.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.models import SourceManifestEntry  # from TASK-1627
from pathlib import Path
import hashlib
import json
import os
import logging
```

### Existing Signatures to Use

```python
# Reuse the PATTERN from SQLitePersistence.is_stale, not the class itself:
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py
# async def is_stale(self, ctx, source_uri, mtime, sha1) -> bool:  # line 387
# The pattern: compare stored mtime + SHA-1 hash against current file state.
# SourceCollectionManager implements its own version using JSON manifest
# instead of SQLite — same logic, different storage.
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.sources`~~ — does not exist yet; this task creates it
- ~~`SourceCollectionManager`~~ — does not exist yet
- ~~`parrot.knowledge.wiki.manifest`~~ — no separate manifest module; manifest
  logic is part of SourceCollectionManager

---

## Implementation Notes

### Pattern to Follow

```python
class SourceCollectionManager:
    def __init__(self, sources_dir: Path) -> None:
        self.sources_dir = sources_dir
        self.manifest_path = sources_dir / ".manifest.json"
        self.logger = logging.getLogger(__name__)
        self._manifest: dict[str, SourceManifestEntry] = {}
        self._load_manifest()

    def _compute_hash(self, path: Path) -> str:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def is_stale(self, source_id: str) -> bool:
        entry = self._manifest.get(source_id)
        if not entry:
            return True
        path = Path(entry.source_uri)
        if not path.exists():
            return True
        current_hash = self._compute_hash(path)
        current_mtime = path.stat().st_mtime
        return current_hash != entry.file_hash or current_mtime != entry.mtime
```

### Key Constraints

- Synchronous file I/O is acceptable here (manifest is small JSON)
- Use SHA-1 for file hashing (matches GraphIndex pattern)
- Manifest must be human-readable JSON with indent=2
- Source IDs should be deterministic from the source URI

---

## Acceptance Criteria

- [ ] SourceCollectionManager tracks sources with hash + mtime
- [ ] `is_stale()` detects file changes correctly
- [ ] Manifest persisted as `.manifest.json`
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_sources.py -v`
- [ ] Import works: `from parrot.knowledge.wiki.sources import SourceCollectionManager`

---

## Test Specification

```python
import pytest
from parrot.knowledge.wiki.sources import SourceCollectionManager

@pytest.fixture
def sources_dir(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    return d

@pytest.fixture
def sample_source(sources_dir):
    f = sources_dir / "article.md"
    f.write_text("# Test Article\n\nContent here.")
    return f

class TestSourceCollectionManager:
    def test_add_source(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert entry.source_uri == str(sample_source)
        assert entry.file_hash is not None

    def test_is_stale_unchanged(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        mgr.add_source(sample_source)
        assert not mgr.is_stale(entry.source_id)

    def test_is_stale_changed(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        sample_source.write_text("# Updated Content")
        assert mgr.is_stale(entry.source_id)

    def test_manifest_persistence(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        mgr.add_source(sample_source)
        mgr2 = SourceCollectionManager(sources_dir)
        assert len(mgr2.list_sources()) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §3 Module 3
2. **Check dependencies** — TASK-1627 must be completed
3. **Reference** `graphindex/persist_sqlite.py:387` for the `is_stale()` pattern
4. **Implement** SourceCollectionManager with manifest persistence
5. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
