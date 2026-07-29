---
type: Wiki Overview
title: 'TASK-1335: Move vector-store backends (6 files) to satellite'
id: doc:sdd-tasks-completed-task-1335-move-store-backends-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of the spec — relocate six concrete
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
- concept: mod:parrot.stores.kb
  rel: mentions
- concept: mod:parrot.stores.milvus
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# TASK-1335: Move vector-store backends (6 files) to satellite

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1333
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec — relocate six concrete
vector-store backends from `packages/ai-parrot/src/parrot/stores/` to
the satellite. The store dispatch table
(`packages/ai-parrot/src/parrot/stores/__init__.py:3-10`) stays in
core; the moved backend modules continue to be reachable at the same
import paths through PEP 420 namespace merging.

This is the largest task in the feature by code volume (`postgres.py`
alone is 3143 lines, and stores has the most cross-imports
internally). Read the spec's Codebase Contract carefully before
touching anything.

Reference: spec §3 Module 3, §6 Codebase Contract.

---

## Scope

- `git mv` (preserve history) these six files:
  - `packages/ai-parrot/src/parrot/stores/postgres.py` →
    `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py`
  - `packages/ai-parrot/src/parrot/stores/pgvector.py` →
    `packages/ai-parrot-embeddings/src/parrot/stores/pgvector.py`
    (3-line shim; moves with postgres)
  - `packages/ai-parrot/src/parrot/stores/faiss_store.py` →
    `packages/ai-parrot-embeddings/src/parrot/stores/faiss_store.py`
  - `packages/ai-parrot/src/parrot/stores/milvus.py` →
    `packages/ai-parrot-embeddings/src/parrot/stores/milvus.py`
  - `packages/ai-parrot/src/parrot/stores/arango.py` →
    `packages/ai-parrot-embeddings/src/parrot/stores/arango.py`
  - `packages/ai-parrot/src/parrot/stores/bigquery.py` →
    `packages/ai-parrot-embeddings/src/parrot/stores/bigquery.py`
- Add per-backend extras to
  `packages/ai-parrot-embeddings/pyproject.toml`:
  - `pgvector = ["pgvector==0.4.1"]` (+ whatever postgres.py needs from
    asyncdb/psycopg).
  - `milvus = ["pymilvus==2.4.8", "milvus-lite>=2.4.0"]`.
  - `arango = ["python-arango-async==1.2.0"]`.
  - `bigquery = ["google-cloud-bigquery>=3.30.0"]`.
  - `faiss = []` — faiss-cpu stays in core deps (do not duplicate); the
    extra exists so users can opt in via name even though it pulls no
    extra deps.
  - `chroma = ["chromadb==0.6.3"]` — even though there is no
    `chroma.py` backend file today, the host's `chroma` extra (lines
    413-415) moves here. If implementation discovers no `ChromaStore`
    file at move time, leave the extra but document that it is reserved.
- Confirm internal imports in the moved files still resolve to the
  host:
  - `from parrot.stores.abstract import AbstractStore`
  - `from parrot.stores.models import Document, SearchResult,
    StoreConfig, DistanceStrategy`
  - `from parrot.embeddings import EmbeddingRegistry` (lazy, see F012)
- After move,
  `packages/ai-parrot/src/parrot/stores/` contains only:
  `__init__.py`, `abstract.py`, `models.py`, `empty.py`, `cache.py`,
  plus the sub-packages `kb/`, `parents/`, `utils/`.

**NOT in scope**:
- Touching `parrot.stores.__init__` (its `supported_stores` dispatch
  STAYS unchanged).
- Touching `parrot.stores.abstract`, `models`, `empty`, `cache` — they
  STAY in core.
- Touching the sub-packages `parrot.stores.kb`, `parents`, `utils` —
  they STAY in core per resolved question U2.
- "Fixing" the dispatch-table mismatch
  (`supported_stores['faiss_store'] == 'FaissStore'` vs actual class
  `FAISSStore`; `supported_stores['arango'] == 'ArangoStore'` vs actual
  `ArangoDBStore`) — out of scope per spec §7.
- Removing `pgvector==0.4.1` from the host's `images` extra — that's
  TASK-1337.
- Removing the host's `embeddings`/`milvus`/`chroma`/`arango`
  extras — that's TASK-1337.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/postgres.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/stores/pgvector.py` | DELETE (via git mv) | 3-line shim moves with postgres |
| `packages/ai-parrot/src/parrot/stores/faiss_store.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/stores/milvus.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/stores/arango.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/stores/bigquery.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot-embeddings/src/parrot/stores/*.py` | CREATE (via git mv) | Satellite locations |
| `packages/ai-parrot-embeddings/pyproject.toml` | MODIFY | Add `pgvector`, `milvus`, `arango`, `bigquery`, `faiss`, `chroma` extras |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports the moved files rely on (all STAY in core)

```python
# Resolved through merged namespace after the move.
from parrot.stores.abstract import AbstractStore       # verified: packages/ai-parrot/src/parrot/stores/abstract.py:60
from parrot.stores.models import (                     # verified: packages/ai-parrot/src/parrot/stores/models.py
    SearchResult,      # line 7
    Document,          # line 40
    DistanceStrategy,  # line 49
    StoreConfig,       # line 61
)
from parrot.embeddings import EmbeddingRegistry        # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:1
                                                       # (idiomatic local-import inside methods to avoid circular)
```

### Verified Class Locations (the files being moved)

```python
# packages/ai-parrot/src/parrot/stores/postgres.py:49
class PgVectorStore(AbstractStore):
    # 3143-line implementation — does NOT change shape; just relocates.

# packages/ai-parrot/src/parrot/stores/pgvector.py:1
from .postgres import PgVectorStore   # 3-line re-export shim; moves with postgres

# packages/ai-parrot/src/parrot/stores/milvus.py:67
class MilvusStore(AbstractStore):

# packages/ai-parrot/src/parrot/stores/arango.py:28
class ArangoDBStore(AbstractStore):   # ← actual class name (despite dispatch dict saying "ArangoStore")

# packages/ai-parrot/src/parrot/stores/bigquery.py:23
class BigQueryStore(AbstractStore):

# packages/ai-parrot/src/parrot/stores/faiss_store.py:32
class FAISSStore(AbstractStore):      # ← actual class name (despite dispatch dict saying "FaissStore")
```

### Verified Dispatch Table (STAYS in core; do NOT modify)

```python
# packages/ai-parrot/src/parrot/stores/__init__.py:1-10
from .abstract import AbstractStore
supported_stores = {
    'postgres': 'PgVectorStore',
    'milvus': 'MilvusStore',
    'kb': 'KnowledgeBaseStore',
    'faiss_store': 'FaissStore',   # ← PRE-EXISTING mismatch; do NOT fix
    'arango': 'ArangoStore',       # ← PRE-EXISTING mismatch; do NOT fix
    'bigquery': 'BigQueryStore',
}
```

### Verified Abstract Signature (STAYS in core; do NOT modify)

```python
# packages/ai-parrot/src/parrot/stores/abstract.py
class AbstractStore(ABC):                                          # line 60
    def __init__(self, ...) -> None:                               # line 75
    async def similarity_search(...) -> List[SearchResult]:        # line 216
    async def from_documents(...) -> "AbstractStore":              # line 247
    async def add_documents(...) -> None:                          # line 279
    def create_embedding(self, ..., matryoshka=None) -> EmbeddingModel:  # line 297 — FEAT-150 kwarg
    async def delete_documents(...) -> None:                       # line 465
    async def delete_documents_by_filter(...) -> None:             # line 491
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.stores.FaissStore` (no caps)~~ — the actual class is
  `FAISSStore` at `faiss_store.py:32`. The dispatch dict's value
  `"FaissStore"` is a pre-existing typo that FEAT-201 must NOT fix.
- ~~`parrot.stores.ArangoStore`~~ — actual class is `ArangoDBStore`
  at `arango.py:28`. Same pre-existing dispatch-dict mismatch.
- ~~`__init__.py` in the satellite's `src/parrot/stores/`~~ — does NOT
  exist; must NOT be created (U3).
- ~~A new `chroma.py` backend file~~ — there is no `parrot.stores.chroma`
  file today. Verify with `ls packages/ai-parrot/src/parrot/stores/`
  before assuming. If absent, the `chroma` extra exists for future use
  but no file moves.
- ~~Moving `kb/`, `parents/`, `utils/`, `empty.py`, `cache.py`,
  `__init__.py`, `abstract.py`, `models.py`~~ — these STAY in core
  per resolved question U2.

---

## Implementation Notes

### Suggested per-backend extras

```toml
[project.optional-dependencies]
pgvector = [
    "pgvector==0.4.1",
    # postgres.py may also need: "asyncpg", "psycopg-binary" — verify before adding
]
milvus = [
    "pymilvus==2.4.8",
    "milvus-lite>=2.4.0",
]
arango = [
    "python-arango-async==1.2.0",
]
bigquery = [
    "google-cloud-bigquery>=3.30.0",
]
faiss = []   # faiss-cpu stays in core ai-parrot deps; this extra is a name-only opt-in
chroma = [
    "chromadb==0.6.3",
]
```

Refine by reading each moved file's actual imports.

### `pgvector.py` is a 3-line shim

```python
# Current content (verified):
from .postgres import PgVectorStore
```

This relative import (`from .postgres`) keeps working after the move
because both files end up in the same satellite directory.
**Do not rewrite it as `from parrot.stores.postgres`** — the relative
form is more robust and matches the existing style.

### Pre-existing dispatch-table mismatches

`supported_stores['faiss_store'] = 'FaissStore'` but the class is
`FAISSStore`; `supported_stores['arango'] = 'ArangoStore'` but the
class is `ArangoDBStore`. These mismatches exist TODAY in `dev` and
some downstream resolver likely handles them via case-insensitive
lookup or similar. **Do not touch them.** Fixing the dispatch table
is a separate concern outside FEAT-201's scope.

### Use `git mv` (NOT `git rm` + create)

```bash
git mv packages/ai-parrot/src/parrot/stores/postgres.py \
       packages/ai-parrot-embeddings/src/parrot/stores/postgres.py
# ...etc
```

### References in Codebase

- `packages/ai-parrot/src/parrot/stores/__init__.py:1-10` — dispatch
  STAYS in core.
- `packages/ai-parrot/src/parrot/stores/abstract.py:60` — Abstract
  STAYS in core.
- `packages/ai-parrot/src/parrot/stores/models.py:7,40,49,61` — shared
  types STAY in core.

---

## Acceptance Criteria

- [ ] All six files moved via `git mv` (history preserved).
- [ ] `packages/ai-parrot/src/parrot/stores/` no longer contains
      `postgres.py`, `pgvector.py`, `faiss_store.py`, `milvus.py`,
      `arango.py`, `bigquery.py`.
- [ ] `packages/ai-parrot/src/parrot/stores/` STILL contains
      `__init__.py`, `abstract.py`, `models.py`, `empty.py`,
      `cache.py`, and the sub-packages `kb/`, `parents/`, `utils/`.
- [ ] `packages/ai-parrot-embeddings/src/parrot/stores/` contains the
      six moved files and NO `__init__.py`.
- [ ] Satellite `pyproject.toml` declares extras `pgvector`, `milvus`,
      `arango`, `bigquery`, `faiss` (possibly empty), `chroma`.
- [ ] `uv sync --all-packages` succeeds.
- [ ] With satellite installed:
      `python -c "from parrot.stores.pgvector import PgVectorStore; print(PgVectorStore.__module__)"`
      prints `parrot.stores.postgres` (because pgvector.py re-exports
      from postgres).
- [ ] `python -c "import parrot.stores.milvus as m; print(m.__file__)"`
      shows a path inside `packages/ai-parrot-embeddings/...`.
- [ ] `python -c "from parrot.stores import supported_stores;
      print(supported_stores)"` prints the unchanged dict (6 keys, same
      values as before, mismatches preserved).
- [ ] `python -c "from parrot.stores import AbstractStore"` succeeds
      from the host.
- [ ] Existing test:
      `pytest packages/ai-parrot/tests/ -k stores -x` still passes.

---

## Test Specification

```python
# packages/ai-parrot-embeddings/tests/test_store_backends_present.py
import importlib
from pathlib import Path

import pytest

STORE_BACKENDS = ["postgres", "milvus", "arango", "bigquery", "faiss_store"]


@pytest.mark.parametrize("backend", STORE_BACKENDS)
def test_backend_resolves_to_satellite(backend):
    """Moved backend modules resolve inside the satellite distribution."""
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.stores.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__


def test_pgvector_shim_reexports_pgvectorstore():
    """The 3-line pgvector.py shim still aliases postgres.PgVectorStore."""
    from parrot.stores import pgvector, postgres
    assert pgvector.PgVectorStore is postgres.PgVectorStore


def test_supported_stores_unchanged():
    """Dispatch table in core remains exactly as before (mismatches preserved)."""
    from parrot.stores import supported_stores
    assert supported_stores == {
        'postgres': 'PgVectorStore',
        'milvus': 'MilvusStore',
        'kb': 'KnowledgeBaseStore',
        'faiss_store': 'FaissStore',
        'arango': 'ArangoStore',
        'bigquery': 'BigQueryStore',
    }


def test_kb_parents_utils_stay_in_core():
    """U2: higher-level sub-packages remain in the host."""
    for subpkg in ("kb", "parents", "utils"):
        mod = importlib.import_module(f"parrot.stores.{subpkg}")
        assert "ai-parrot/src/parrot/stores" in mod.__file__, \
            f"{subpkg} should stay in core, got {mod.__file__}"


def test_satellite_did_not_create_stores_init():
    """Satellite did not accidentally create __init__.py at the stores level."""
    init = (
        Path(__file__).parent.parent
        / "src" / "parrot" / "stores" / "__init__.py"
    )
    assert not init.exists(), f"forbidden file: {init}"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 3 and §6 Codebase Contract.
2. **Check dependencies** — TASK-1333 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — `grep` each of the six files for
   their `import` lines and confirm the cross-distribution imports
   point at host-only modules (`abstract`, `models`, `embeddings`).
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** — `git mv` the six files, edit satellite pyproject,
   run `uv sync`, run the smoke test + core test suite.
6. **Verify** all acceptance criteria, especially the
   `supported_stores` byte-identity check (the dict in core must NOT
   change).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: All 6 files moved via `git mv`. Satellite pyproject updated with
pgvector, milvus, arango, bigquery, faiss (empty), chroma extras. 8/9 tests
pass. The milvus test fails due to a pre-existing `marshmallow==4.3.0` / environs
incompatibility in the dev environment, not from our changes. The milvus.py file
is confirmed to be in the satellite at the correct path.

**Deviations from spec**: The milvus test cannot pass due to the
marshmallow/environs version conflict pre-existing in the dev venv. This is
outside FEAT-201 scope.
