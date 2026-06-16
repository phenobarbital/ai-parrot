# TASK-1576: Builder & Loader Wiring + Dependencies

**Feature**: FEAT-240 — GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader
**Spec**: `sdd/specs/odoo-graphindex-code.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1572, TASK-1573, TASK-1574
**Assigned-to**: unassigned

---

## Context

This task wires all new components into the existing build pipeline. The builder
gets a configurable extractor class, mtime passing, and incremental staleness
checks. The loader gets SQLite backend selection. Dependencies are declared
explicitly.

Implements Spec §3 Module 6.

---

## Scope

- **Builder** (`builder.py`):
  - Add `code_extractor_class` constructor param (default: `CodeExtractor`)
  - In `_extract_code()`: instantiate `self._code_extractor_class()` instead of `CodeExtractor()`
  - Pass `mtime=os.stat(path).st_mtime` to `extract()`
  - If persistence has `is_stale()`, call it before extracting each file; skip if not stale
- **Loader** (`loader.py`):
  - Support SQLite backend selection alongside ArangoDB/Null
  - When `sqlite_dir` is provided, use `SQLitePersistence(db_dir=sqlite_dir)`
- **Exports** (`__init__.py`):
  - Export `SQLitePersistence` and `SQLiteGraphReader` from graphindex package
  - Export `OdooCodeExtractor` from extractors package
- **Dependencies** (`pyproject.toml`):
  - Add `aiosqlite>=0.17` to `graphindex` extra
  - Add `orjson>=3.9` to `graphindex` extra
- Write integration tests

**NOT in scope**: Implementing the components themselves (done in prior tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | Add code_extractor_class, mtime, is_stale |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | Add SQLite backend selection |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | MODIFY | Export new components |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/__init__.py` | MODIFY | Export OdooCodeExtractor |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add aiosqlite, orjson to graphindex extra |
| `packages/ai-parrot/tests/knowledge/graphindex/test_builder_odoo.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.builder import GraphIndexBuilder  # verified: builder.py:54
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence  # created by TASK-1573
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader  # created by TASK-1575
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor  # created by TASK-1574
from parrot.knowledge.graphindex.extractors.code import CodeExtractor  # verified: code.py:61
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
class GraphIndexBuilder:  # line 54
    def __init__(
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Optional[Path] = None,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,
        signal_config: Optional[SignalRelevanceConfig] = None,
        detect_communities_enabled: bool = False,
        community_resolution: float = 1.0,
    ) -> None:  # line 94
    # ADD: code_extractor_class: type = CodeExtractor

    async def _extract_code(
        self, sources: SourceConfig,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:  # line 404
    # Currently: extractor = CodeExtractor()
    # CHANGE TO: extractor = self._code_extractor_class()
    # AND: pass mtime=os.stat(path).st_mtime to extract()

# packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
class _NullPersistence:  # line 44
    async def persist_graph(...): ...    # line 57
    async def replace_document_slice(...): ...  # line 66

class GraphIndexLoader:  # line 96
    def __init__(self, ...) -> None:  # line 130
    # ADD: sqlite_dir param

# packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py
__all__ = [...]  # lines 48-72
# ADD: "SQLitePersistence", "SQLiteGraphReader", "OdooCodeExtractor"

# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/__init__.py
__all__ = [
    "CodeExtractor",    # line 16
    "LoaderExtractor",  # line 17
    "SkillExtractor",   # line 18
]
# ADD: "OdooCodeExtractor"

# packages/ai-parrot/pyproject.toml (graphindex extra, lines 158-163)
# graphindex = [
#     "rustworkx>=0.15",
#     "tree-sitter>=0.23",
#     "tree-sitter-languages>=1.10",
#     "pathspec>=0.12",
# ]
# ADD: "aiosqlite>=0.17", "orjson>=3.9"
```

### Does NOT Exist
- ~~`GraphIndexBuilder.__init__(..., code_extractor_class=...)`~~ — does not exist yet
- ~~`GraphIndexLoader.__init__(..., sqlite_dir=...)`~~ — does not exist yet
- ~~`persistence.is_stale()`~~ — only exists on `SQLitePersistence`, not on `GraphIndexPersistence`

---

## Implementation Notes

### Builder changes

```python
# In __init__, add parameter:
code_extractor_class: type = CodeExtractor

# Store it:
self._code_extractor_class = code_extractor_class

# In _extract_code(), replace:
#   extractor = CodeExtractor()
# with:
#   extractor = self._code_extractor_class()

# When iterating files, add mtime:
import os
mtime = os.stat(path).st_mtime
# If persistence supports is_stale, check before extracting:
if hasattr(self.persistence, 'is_stale'):
    sha1 = hashlib.sha1(source.encode()).hexdigest()
    if not await self.persistence.is_stale(ctx, str(f), mtime, sha1):
        continue  # skip unchanged file
nodes, edges = await extractor.extract(str(f), source, mtime=mtime)
```

### Loader changes

Add `sqlite_dir: Optional[Path] = None` to `__init__`. When provided and
`persist_enabled` is False (no ArangoDB), use `SQLitePersistence(db_dir=sqlite_dir)`.

### Key Constraints
- `code_extractor_class` defaults to `CodeExtractor` for backward compatibility
- `is_stale` check uses `hasattr` since ArangoDB backend lacks it
- Don't break any existing builder/loader tests
- mtime must use `os.stat` not `os.path.getmtime` (stat is more precise)

---

## Acceptance Criteria

- [ ] `GraphIndexBuilder(persistence, embedder, code_extractor_class=OdooCodeExtractor)` works
- [ ] `_extract_code()` uses the configured extractor class
- [ ] `_extract_code()` passes `mtime` to `extract()`
- [ ] Incremental builds skip unchanged files when persistence supports `is_stale`
- [ ] `GraphIndexLoader(..., sqlite_dir=Path(...))` uses SQLitePersistence
- [ ] `aiosqlite>=0.17` and `orjson>=3.9` in `graphindex` extra
- [ ] `OdooCodeExtractor` exported from `graphindex.extractors`
- [ ] `SQLitePersistence` and `SQLiteGraphReader` exported from `graphindex`
- [ ] All existing builder/loader tests pass
- [ ] Integration test: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_builder_odoo.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch
from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor

class TestBuilderOdooWiring:
    def test_accepts_extractor_class(self):
        # Verify constructor accepts code_extractor_class param
        ...

    async def test_extract_code_uses_configured_extractor(self):
        # Mock to verify OdooCodeExtractor is instantiated
        ...

    async def test_mtime_passed_to_extract(self):
        # Mock extract to capture args, verify mtime is present
        ...

    async def test_stale_check_skips_unchanged(self):
        # Mock is_stale to return False, verify extract is NOT called
        ...
```

---

## Completion Note

Implemented 2026-06-16 by sdd-worker (claude-sonnet-4-6).

- `GraphIndexBuilder`: added `code_extractor_class` param (default `CodeExtractor`), stored as `self._code_extractor_class`. `_extract_code()` now instantiates the configured class, reads `mtime` via `os.stat()`, and calls `await self.persistence.is_stale()` (guarded by `hasattr`) to skip unchanged files.
- `GraphIndexLoader`: added `sqlite_dir` param; `_make_persistence()` returns `SQLitePersistence(db_dir=self._sqlite_dir)` when set (takes priority over ArangoDB null fallback).
- `graphindex/__init__.py`: exports `SQLitePersistence`, `SQLiteGraphReader`, `OdooCodeExtractor`.
- `pyproject.toml`: added `aiosqlite>=0.17`, `orjson>=3.9` to `[graphindex]` extra.
- Fixed 5 pre-existing test failures from TASK-1571 (EdgeKind.EXTENDS changed enum size from 5→6): updated test_schema.py, test_meta_ontology.py, test_persist.py.
- 15 integration tests in `test_builder_odoo.py` — all pass. 502/502 graphindex tests pass.

Key issue fixed: `MagicMock.is_stale` is truthy due to auto-attribute creation. Used `_mock_null_persistence()` (which `del p.is_stale`) in tests that should not trigger the staleness path.
