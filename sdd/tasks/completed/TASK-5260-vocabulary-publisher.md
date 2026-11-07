# TASK-5260: `PostgresOntologyPublisher` — serialised, append-only publication

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-5256, TASK-5259
**Assigned-to**: unassigned

---

## Context

Spec Module 6 and spec §2 "Publication pipeline" / "Temporal semantics". The publisher is the
**only writer** of the `ontology_store` schema. It validates a candidate, diffs it against the
current version N and commits version N+1 in one short transaction: rows are never overwritten
(changing anything closes the current row and inserts a new one), closure is stored per version,
and a `publication_outbox` row records the diff. CPU-bound parse/validate/closure run in a process
pool. Also creates `_rows.py`, the shared "read everything visible at version v" helper the store
(TASK-5261) reuses.

---

## Scope

- `vocabulary/_rows.py` — `async def read_content(conn, schema, ontology_id, version) -> tuple[OntologyContent, list[ClosureRow], dict[str, list[float]]]`
  reading rows visible at `v` (`since_version <= v AND (until_version IS NULL OR v < until_version)`)
  and that version's closure and embeddings; and `async def visible_iris(conn, schema, ontology_id, version) -> frozenset[str]`.
- `vocabulary/publisher.py` — `PostgresOntologyPublisher` (spec lines 813–835).
- Pipeline (spec §2):
  1. `publish` → `parse_turtle` in the executor → `publish_content(carry_forward_missing=False)`.
  2. `publish_content`: read `base_iri`, `current_version` N (no lock) and the base content at N;
     with `carry_forward_missing=True`, add every base concept absent from `content` back as
     `deprecated=True` (keeping its labels); validate (executor) with `previous_iris` = IRIs visible
     at N → `OntologyValidationError` on any issue; diff → empty ⇒ return
     `PublishResult(version=N, changed=False, …)` and write nothing; materialise inverses and build
     the closure (executor); compute embeddings for added/changed concepts via `embed` (outside the TX).
  3. TX: `SELECT … FROM {s}.ontology WHERE ontology_id=$1 FOR UPDATE`; if `current_version != N`
     roll back and recompute from step 2 (at most `MAX_PUBLISH_RETRIES`, then `PublishConflict`);
     insert `version` (N+1, checksum, `turtle_canonical`, notes); upsert `concept_identity`; for each
     changed row close the current row (`until_version = N+1`) and insert the new one with
     `since_version = N+1`; insert added rows; close rows absent from the candidate (labels,
     relations incl. inferred, statements; concepts are never closed without a replacement row);
     insert `closure` rows for N+1; `UPDATE ontology SET current_version = N+1`; insert
     `publication_outbox(ontology_id, version, diff)`.
- `ensure_ontology` (idempotent; `ValueError` on a different `base_iri`), `close` (shuts down only an
  executor this instance created).
- `test_publisher.py` (integration, skip-gated).

**NOT in scope**: reading APIs (`resolve`, `expand`… — TASK-5261); snapshot; outbox draining
(Phase 3 consumes it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/_rows.py` | CREATE | read rows visible at a version |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/publisher.py` | CREATE | the publisher |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_publisher.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncpg
from parrot.knowledge.ontology.vocabulary.contracts import (               # TASK-5253
    ClosureRow, EmbedFn, OntologyContent, ParsedConcept, PublishDiff, PublishResult)
from parrot.knowledge.ontology.vocabulary.exceptions import (               # TASK-5253
    OntologyNotFound, OntologyValidationError, PublishConflict)
from parrot.knowledge.ontology.vocabulary.pg_schema import validate_schema_name, create_ontology_pg_pool  # TASK-5256
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings                       # TASK-5254
from parrot.knowledge.ontology.vocabulary.turtle import (                   # TASK-5258/5259
    canonical_ntriples, content_checksum, diff_content, parse_turtle, statement_object_hash, validate_content)
from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses              # TASK-5257
```

### Existing Signatures to Use
```python
# TASK-5256: async def ensure_schema(pool, schema=None, *, embedding_dim=None, ann_index_kind=None) -> None
#            async def create_ontology_pg_pool(dsn=None, *, schema=None, min_size=1, max_size=10, **kw) -> Pool  (pgvector codec registered)
# spec §2 DDL: tables ontology, version, concept_identity, concept, label, relation, statement, closure, publication_outbox
#   partial unique indexes *_current ... WHERE until_version IS NULL  (two current rows ⇒ unique violation)
# pattern: parrot/knowledge/ontology/concept_catalog/worker.py:57-131 — conn.transaction() + FOR UPDATE
# TASK-5255 conftest: pg_pool, pg_schema_name, golden_v1/v2/v3, golden_base_iri
```

### Does NOT Exist
- ~~an UPDATE that changes `pref_label`/`definition`/… of a current row in place~~ — forbidden;
  the only UPDATE on versioned tables sets `until_version`.
- ~~`DELETE` on any vocabulary table~~ — forbidden (append-only, D2).
- ~~`PgVectorStore` reuse~~ — asyncpg only (FEAT-520 convention).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/_rows.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/publisher.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_publisher.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The transaction must be short: everything CPU- or network-bound (parse, validate, closure,
  embeddings) happens before it (spec §7 "Lecturas de larga duración").
- Executor work exchanges only Pydantic models; submit top-level functions (`parse_turtle`,
  `validate_content`, a module-level `_prepare(content, base) -> (diff, inverses, closure, checksum, ntriples)`).
- `concept.embedding` text = `pref_label + "\n" + definition + "\n" + ", ".join(alt labels)`; `embed=None`
  leaves it NULL. Unchanged rows keep their stored embedding (they are not rewritten).
- Concurrency proof (AC): two concurrent `publish_content` on the same ontology produce consecutive
  versions; the `FOR UPDATE` + version check is what serialises them.
- Measure and record the publication time for the largest golden fixture in the Completion Note
  (spec AC, no threshold).

---

## Implementation Blueprint

### Steps (in order)
1. `_rows.py` — *why*: the publisher needs the base content and the store needs `load_version`; one SQL path.
2. `publisher.py` skeleton below; then `publish_content` per Scope step 2–3.
3. Integration tests.

### `.../vocabulary/publisher.py` (CREATE)
```python
"""Serialised, append-only publication of ontology versions to PostgreSQL (FEAT-824)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import ClassVar

import asyncpg

from parrot.knowledge.ontology.vocabulary._rows import read_content, visible_iris
from parrot.knowledge.ontology.vocabulary.contracts import EmbedFn, OntologyContent, PublishResult
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyValidationError, PublishConflict
from parrot.knowledge.ontology.vocabulary.pg_schema import validate_schema_name
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.turtle import parse_turtle, validate_content


class PostgresOntologyPublisher:
    """Serialised, append-only publication of ontology versions."""

    MAX_PUBLISH_RETRIES: ClassVar[int] = 3

    def __init__(self, pool: asyncpg.Pool, *, schema: str | None = None, embed: EmbedFn | None = None,
                 executor: concurrent.futures.Executor | None = None) -> None:
        settings = resolve_ontology_settings(schema=schema)
        validate_schema_name(settings.schema_name)
        self._pool, self._schema, self._embed = pool, settings.schema_name, embed
        self._default_lang = settings.default_lang
        self._executor, self._owns_executor = executor, executor is None
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.publisher")

    def _pool_executor(self) -> concurrent.futures.Executor:
        """Lazily create a single-worker ProcessPoolExecutor when none was injected."""
        if self._executor is None:
            self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        return self._executor

    async def ensure_ontology(self, ontology_id: str, *, base_iri: str, title: str | None = None) -> None:
        """Register at version 0. Idempotent; ValueError when it exists with a different base_iri."""
        # FILL IN: INSERT ... ON CONFLICT DO NOTHING; then compare stored base_iri.
        raise NotImplementedError

    async def publish(self, ontology_id: str, turtle: bytes, *, notes: str = "",
                      shapes: bytes | None = None) -> PublishResult:
        """Parse, then publish_content(carry_forward_missing=False).

        Raises: OntologyNotFound, OntologyValidationError, PublishConflict.
        """
        # FILL IN: fetch base_iri (OntologyNotFound when missing); run parse_turtle in the executor
        #          via loop.run_in_executor; forward `shapes` to validation (store it on a private arg
        #          of an internal _publish(...) shared with publish_content).
        raise NotImplementedError

    async def publish_content(self, ontology_id: str, content: OntologyContent, *, notes: str = "",
                              carry_forward_missing: bool = False) -> PublishResult:
        """Validate, diff against the current version, commit version N+1 in one transaction."""
        # FILL IN: Scope steps 2-3 with the bounded retry loop; self.logger.info on each new version.
        raise NotImplementedError

    async def close(self) -> None:
        """Shut down the executor this instance created; the pool belongs to the caller."""
        if self._owns_executor and self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
```

### `.../vocabulary/test_publisher.py` (CREATE) — required cases (all use `pg_pool`, `pg_schema_name`)
```python
async def test_publish_first_version(...): ...          # v1 → version 1, changed=True, checksum == content_checksum(parse(v1))
async def test_publish_twice_same_version(...): ...     # same Turtle again → version 1, changed=False, no new version row
async def test_publish_removed_iri_rejected(...): ...   # v1 then a doc dropping an IRI → OntologyValidationError(IRI_REMOVED); current_version still 1
async def test_rejection_writes_nothing(...): ...       # row counts unchanged after a rejected publication
async def test_concurrent_publish_serialised(...): ...  # asyncio.gather(two different candidates) → versions {2, 3}; no two current rows per identity
async def test_attribute_change_closes_row(...): ...    # v2 label change → old row until_version=2, new row since_version=2
async def test_ensure_ontology_conflicting_base(...): ...  # ValueError
async def test_carry_forward_missing_deprecates(...): ...  # publish_content(content minus one concept, carry_forward_missing=True) → concept deprecated, not IRI_REMOVED
```
Use `executor=concurrent.futures.ThreadPoolExecutor(1)` in tests only if the process pool is slow to
spawn under pytest — the production default stays a process pool.

### FILL IN checklist
- [ ] `_rows.read_content`, `_rows.visible_iris`.
- [ ] `ensure_ontology`, `publish`, `publish_content` (+ module-level `_prepare`).
- [ ] eight integration tests; publication time recorded.

---

## Acceptance Criteria

- [ ] Publishing the same Turtle twice does not change `version`.
- [ ] A rejected candidate (any issue code) writes nothing.
- [ ] Concurrent publications never produce overlapping validity intervals or two current rows.
- [ ] No `DELETE` and no in-place attribute `UPDATE` in the module.
- [ ] `ruff check` passes; no SQLAlchemy, no `print`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_publisher.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5256 and TASK-5259 are `done`.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   and `ONTOLOGY_PG_DSN` pointing at a scratch database (state in the note whether they ran or skipped).
3. Commit only the listed files; close with `parrot sdd task close TASK-5260 ontology-backend verified`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 426s. Merge-tier validation exit 0, BUT the PostgreSQL-backed tests (test_publisher.py: 8 tests) were all SKIPPED (needs live Postgres, connection refused) — the publisher's behaviour is NOT exercised by this run; run them against a live DB (ONTOLOGY_PG_DSN) before relying on it.

**Completed by**: sdd-worker (coder: gpt-5.6-terra)
**Date**: 2026-11-07
**Publication time (largest golden fixture)**:
**Notes**:

**Deviations from spec**: adds the private helper module `_rows.py` (shared with TASK-5261).
