# TASK-5264: Shared conformance suite and temporal-fidelity gate

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5261, TASK-5263
**Assigned-to**: unassigned

---

## Context

Spec Module 9 and the Phase 2 acceptance criteria "Temporal fidelity" and "pass the same
`ALL_CASES`". Backend-agnostic `case_*` coroutines run against **both** `PostgresOntologyStore`
and `SnapshotOntologyStore` over the same published fixture; a separate test proves that historical
reads and exports reproduce each version exactly.

---

## Scope

- `store_conformance.py` with `Case`, the nine `case_*` coroutines and `ALL_CASES` (spec lines 917–927).
  Each case derives expectations from golden v1 (assert ranked IRIs and `matched_by` for `resolve`;
  scores only within 0.02 — spec §7 "Trigram parity").
- `test_postgres_store.py` — `test_conformance_postgres`: publish golden v1 (and v2 where a case
  needs a deprecation), parametrise over `ALL_CASES`.
- `test_snapshot_store.py` — `test_conformance_snapshot`: publish the same fixture to PostgreSQL,
  `load_version` → `build_snapshot` → `SnapshotOntologyStore`, parametrise over `ALL_CASES`.
- `test_temporal_fidelity.py` — `test_temporal_fidelity_v1_v2_v3`: publish v1, v2, v3; for each
  `v`: `export(as_of=v)` re-parsed has `content_checksum == version.checksum` (read the row);
  `get(…, as_of=1)` returns v1 attributes after v2 changed them; `expand(as_of=1)` uses v1's closure
  while `expand(as_of=2)` lacks the removed edge and `expand(as_of=3)` has it again; `as_of=4`
  raises `OntologyVersionNotFound`; a snapshot of v1 holds only v1-visible rows.
- A shared async fixture `published` (in each test module, not `conftest.py`) that runs
  `ensure_schema` + `ensure_ontology` + publishes, yielding `(publisher, store, ontology_id)`.

**NOT in scope**: new store behaviour — a failing case is a bug to fix in the store module, and
that fix is allowed here only if it is confined to `postgres_store.py` or `snapshot.py`
(list it in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/store_conformance.py` | CREATE | cases |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_store.py` | CREATE | conformance — postgres |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_store.py` | CREATE | conformance — snapshot |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_temporal_fidelity.py` | CREATE | temporal gate |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore                     # TASK-5253
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyVersionNotFound          # TASK-5253
from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema, create_ontology_pg_pool  # TASK-5256
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher         # TASK-5260
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore        # TASK-5261
from parrot.knowledge.ontology.vocabulary.snapshot import SnapshotOntologyStore, build_snapshot  # TASK-5262/5263
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle       # TASK-5258
from .store_conformance import ALL_CASES                                                     # this task
```

### Existing Signatures to Use
```python
# pattern — packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py:1-45
#   module docstring; Case = Callable[[Any, Any], Awaitable[None]]; async def case_x(persistence, ctx) -> None
#   imported from a per-backend test with `from .persistence_conformance import ...` (test_graph_backends.py:23)
# TASK-5255 conftest: pg_pool, pg_schema_name, golden_v1/v2/v3, golden_base_iri
# TASK-5261: PostgresOntologyStore(pool, *, schema=None, dsn=None); async load_version(ontology_id, version=None) -> VersionContent
# TASK-5263: SnapshotOntologyStore(snapshot_dir=None, *, source=None)
```

### Does NOT Exist
- ~~a `published_store` fixture in `conftest.py`~~ — defined per module here (no conftest edit).
- ~~`ConceptRef.score`~~ — scores live on `Resolution`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/store_conformance.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_temporal_fidelity.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `store_conformance.py` — *why*: one definition of correct behaviour for both backends.
2. The two per-backend modules — *why*: same cases, same fixture (spec AC).
3. The temporal gate — *why*: spec AC "Temporal fidelity", the core correctness proof.

### `.../vocabulary/store_conformance.py` (CREATE)
```python
"""Reusable OntologyStore conformance cases (FEAT-824 M9).

Call each case with a store that has golden legal_es v1 (then v2) published as ``ontology_id``.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyVersionNotFound

Case = Callable[[OntologyStore, str], Awaitable[None]]


async def case_version_matches_published(store: OntologyStore, ontology_id: str) -> None:
    """version() equals the last published version; status().version agrees."""
    # FILL IN


# FILL IN: case_get_known_and_unknown, case_resolve_exact_trgm_order, case_resolve_excludes_deprecated,
#          case_expand_closed_and_reflexive, case_expand_multiple_inheritance,
#          case_canonical_follows_replaced_by, case_export_checksum_roundtrip,
#          case_unknown_version_rejected — one-line docstring each, expectations from the golden files.

ALL_CASES: tuple[Case, ...] = (
    case_version_matches_published,
    # FILL IN: the other eight, in the order above.
)
```

### `.../vocabulary/test_postgres_store.py` (CREATE)
```python
"""OntologyStore conformance — PostgreSQL backend (FEAT-824 TASK-5264)."""
from __future__ import annotations

import pytest

from .store_conformance import ALL_CASES


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.__name__)
async def test_conformance_postgres(case, published) -> None:
    _publisher, store, ontology_id = published
    await case(store, ontology_id)

# FILL IN: `published` pytest_asyncio fixture (ensure_schema, ensure_ontology, publish v1 then v2).
```
`test_snapshot_store.py` mirrors it with `test_conformance_snapshot`, building the snapshot from
`PostgresOntologyStore.load_version` into `tmp_path`.

### FILL IN checklist
- [ ] nine cases + `ALL_CASES`.
- [ ] `published` fixtures in both conformance modules.
- [ ] temporal test per Scope.

---

## Acceptance Criteria

- [ ] `PostgresOntologyStore` and `SnapshotOntologyStore` pass the same `ALL_CASES` over the same fixture.
- [ ] Temporal fidelity: export checksums equal `version.checksum` for v1, v2, v3; historical `get`
      and `expand` reproduce each version; unknown `as_of` raises.
- [ ] A snapshot of version v holds only rows visible at v.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_temporal_fidelity.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5261 and TASK-5263 are `done`.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   and `ONTOLOGY_PG_DSN` set (these are integration tests; say whether they ran or skipped).
3. Commit only the listed files (plus any confined store fix, listed in the note); close with
   `parrot sdd task close TASK-5264 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
