# TASK-5261: `PostgresOntologyStore` — read contract over versioned rows

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5260
**Assigned-to**: unassigned

---

## Context

Spec Module 7 and spec §2 "Read contract" / "Temporal semantics". Implements every
`OntologyStore` method over the `ontology_store` schema. Each call captures **one** published
version and reads rows, labels and closure only at it. Also `load_version` (everything visible at a
version, for snapshot building) and the registry factory `_create_postgres` already named by
TASK-5254's built-in registration.

---

## Scope

- `vocabulary/postgres_store.py` with `PostgresOntologyStore` (`backend_name = "postgres"`,
  `TRGM_THRESHOLD = 0.45`, `RRF_K = 60`) and `_create_postgres` (spec lines 846–861).
- Semantics:
  - `version` → `current_version`; `OntologyNotFound` when unregistered.
  - `status` → `StoreStatus(version, stale=False, backend="postgres")`.
  - `as_of`: `None` → current; otherwise must be in `1..current_version`, else `OntologyVersionNotFound`.
    A version-0 ontology with `as_of=None` reads nothing (empty results, `get` → `None`).
  - `get` → `ConceptRef` visible at the version (pref label in `default_lang`), else `None`.
  - `resolve(term, lang, k, kinds, embedding)` at the current version, excluding deprecated
    concepts: (1) exact case-insensitive match on any label (`lang` filter when given); (2) trigram
    `similarity(label.text, term) > 0.45`; (3) vector cosine on `concept.embedding` when `embedding`
    is given; fuse with RRF `score = Σ 1/(60 + rank)`; `matched_by` = the best-ranked source for that
    concept (`exact` > `trgm` > `vector` on ties); at most `k`.
  - `expand(iris, family, direction, max_depth, include_deprecated, as_of)` from `closure` of that
    version: `down` = descendants of the inputs, `up` = ancestors, `both` = union; always includes
    the inputs; `max_depth` filters `depth`; deprecated concepts excluded unless asked (inputs stay).
  - `neighbors(iri, predicate, as_of)` → outbound `(predicate, object_iri)` pairs, asserted and inferred.
  - `canonical(iris)` → follow `replaced_by` at the current version, cycle-safe, ≤ 16 hops.
  - `export(fmt, as_of)` → `serialize(content_at_version, fmt)` (asserted graph only).
  - `load_version(ontology_id, version=None)` → `VersionContent` using `_rows.read_content`.
  - `close()` closes the pool **only** if this store created it.
- Pool handling: `__init__(pool, *, schema=None)` per spec, plus a keyword-only `dsn: str | None = None`;
  when `pool is None` the store creates one lazily on first call with `create_ontology_pg_pool(dsn, schema=…)`
  and owns it. `_create_postgres(*, dsn=None, schema=None, pool=None, **_)` returns the store
  synchronously (no awaiting in the factory).
- `test_postgres_reads.py` (integration, skip-gated).

**NOT in scope**: the shared conformance suite and the temporal gate (TASK-5264).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/postgres_store.py` | CREATE | the store + factory |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_reads.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.vocabulary._rows import read_content         # TASK-5260
from parrot.knowledge.ontology.vocabulary.contracts import (                 # TASK-5253
    ClosureFamily, ConceptRef, OntologyStore, Resolution, StoreStatus, VersionContent)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool, validate_schema_name  # TASK-5256
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, serialize                    # TASK-5258
# tests:
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher                    # TASK-5260
```

### Existing Signatures to Use
```python
# TASK-5260 — _rows.py
async def read_content(conn, schema, ontology_id, version) -> tuple[OntologyContent, list[ClosureRow], dict[str, list[float]]]
# TASK-5254 — backends.py registers "postgres" → "parrot.knowledge.ontology.vocabulary.postgres_store:_create_postgres"
# spec Module 3 — OntologyStore method signatures (spec lines 663-692): copy them exactly
```

### Does NOT Exist
- ~~`pg_trgm` `similarity` without the extension~~ — `ensure_schema` creates it; tests call it first.
- ~~a module-level dependency on `rdflib`~~ — `serialize` imports rdflib lazily; keep it that way.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/postgres_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_reads.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Skeleton with `_version_for(conn, ontology_id, as_of) -> int` (captures one version; raises the
   two typed errors) — *why*: every method starts from it (single-version reads).
2. Methods in order: version, status, get, expand, neighbors, canonical, export, load_version, resolve.
3. Factory; integration tests.

### `.../vocabulary/postgres_store.py` (CREATE)
```python
"""OntologyStore over PostgreSQL versioned rows (FEAT-824)."""
from __future__ import annotations

import logging
from typing import Any, ClassVar, Literal, Sequence

from parrot.knowledge.ontology.vocabulary.contracts import (
    ClosureFamily, ConceptRef, OntologyStore, Resolution, StoreStatus, VersionContent,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

_VISIBLE = "since_version <= $2 AND (until_version IS NULL OR $2 < until_version)"


class PostgresOntologyStore:
    """OntologyStore over PostgreSQL. Each call captures one version and reads only at it."""

    backend_name: ClassVar[str] = "postgres"
    TRGM_THRESHOLD: ClassVar[float] = 0.45
    RRF_K: ClassVar[int] = 60

    def __init__(self, pool: Any, *, schema: str | None = None, dsn: str | None = None) -> None:
        settings = resolve_ontology_settings(schema=schema, dsn=dsn)
        self._pool, self._owns_pool = pool, pool is None
        self._dsn, self._schema, self._lang = settings.dsn, settings.schema_name, settings.default_lang
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.postgres_store")

    async def _get_pool(self) -> Any:
        """Return the pool, creating (and owning) one from the DSN on first use."""
        # FILL IN: lazy create_ontology_pg_pool(self._dsn, schema=self._schema) when self._pool is None.
        raise NotImplementedError

    async def _version_for(self, conn: Any, ontology_id: str, as_of: int | None) -> int:
        """Current version (as_of=None) or as_of validated against 1..current_version."""
        # FILL IN: OntologyNotFound / OntologyVersionNotFound per Scope.
        raise NotImplementedError

    # FILL IN: version, status, get, resolve, expand, neighbors, canonical, export, close —
    #          exact OntologyStore signatures (spec lines 665-692); queries filter with _VISIBLE
    #          and closure.version = captured version.

    async def load_version(self, ontology_id: str, version: int | None = None) -> VersionContent:
        """Everything visible at one version — rows, closure, embeddings — for build_snapshot."""
        # FILL IN: _version_for + _rows.read_content + content_checksum check against version.checksum
        #          (log an error if they differ — that is a temporal-fidelity bug).
        raise NotImplementedError


def _create_postgres(*, dsn: str | None = None, schema: str | None = None, pool: Any = None,
                     **_: Any) -> OntologyStore:
    """Registry factory for the 'postgres' backend."""
    return PostgresOntologyStore(pool, schema=schema, dsn=dsn)
```

### `.../vocabulary/test_postgres_reads.py` (CREATE) — required cases
```python
# fixture: ensure_schema + PostgresOntologyPublisher.publish(golden_v1) into pg_schema_name, then the store
async def test_resolve_exact_then_trgm(...): ...      # exact label first, matched_by="exact"; misspelling → "trgm"
async def test_resolve_vector_when_embedding_given(...): ...   # publisher with a deterministic fake embed
async def test_resolve_excludes_deprecated(...): ...  # after v2
async def test_expand_down_up_reflexive(...): ...
async def test_canonical_follows_replaced_by(...): ...
async def test_as_of_unknown_raises(...): ...         # as_of=99 → OntologyVersionNotFound
async def test_factory_via_registry(...): ...         # create_ontology_store("postgres", pool=pg_pool, schema=...)
```

### FILL IN checklist
- [ ] `_get_pool`, `_version_for`, nine contract methods, `load_version`.
- [ ] integration tests.

---

## Acceptance Criteria

- [ ] Every method reads one captured version; unknown `as_of` raises `OntologyVersionNotFound`.
- [ ] `resolve` fuses exact/trgm/vector by RRF k=60 and excludes deprecated concepts.
- [ ] `expand` is closed and reflexive and correct on the golden DAG.
- [ ] `create_ontology_store("postgres", …)` builds the store through the registry.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_reads.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5260 is `done`.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   and `ONTOLOGY_PG_DSN` set (say in the note whether they ran or skipped).
3. Commit only the listed files; close with `parrot sdd task close TASK-5261 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `__init__` gains keyword-only `dsn=None` so the sync registry factory can
build a store without a pool (lazy pool, owned by the store).
