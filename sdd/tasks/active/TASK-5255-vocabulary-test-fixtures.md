# TASK-5255: Vocabulary test fixtures — golden Turtle v1/v2/v3 and PostgreSQL fixtures

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5253
**Assigned-to**: unassigned

---

## Context

Spec §4 "Test Data / Fixtures" and "Integration Tests". Every Phase 2 test that parses, publishes
or reads uses the same golden Turtle and the same live-PostgreSQL fixtures. They are created once
here, before the modules that use them, so no two tasks edit `conftest.py`. The
`published_store` fixture of spec §4 needs the publisher and lives in the conformance task
(TASK-5264), not here.

---

## Scope

- `fixtures/legal_es.v1.ttl` — base IRI `https://ontology.parrot.dev/legal_es/` (any stable HTTP
  base is fine; keep it in one `@prefix ex:`). Must contain, with **no blank nodes**:
  - ≥ 6 `owl:Class` with `skos:prefLabel` in `es` (some also `en`), some `skos:altLabel`, one
    `skos:definition`;
  - a DAG with **multiple inheritance** (one class with two `rdfs:subClassOf` parents) at depth ≥ 3;
  - one `skos:ConceptScheme` and ≥ 4 `skos:Concept` linked by `skos:broader`, each with `skos:prefLabel`;
  - two `owl:ObjectProperty` declared `owl:inverseOf` each other, one `owl:DatatypeProperty`;
  - one `owl:NamedIndividual` typed by a class;
  - one literal statement with a datatype (e.g. `dcterms:created "2026-01-01"^^xsd:date`) and one
    language-tagged literal that is not a label (e.g. `rdfs:comment "..."@es`).
- `fixtures/legal_es.v2.ttl` — v1 with: one prefLabel text changed; one definition changed; one
  `rdfs:subClassOf` removed (record which in a comment); one relation added; one class deprecated
  with `owl:deprecated true` and `dcterms:isReplacedBy` a **new** class added in v2.
- `fixtures/legal_es.v3.ttl` — v2 with the `rdfs:subClassOf` removed in v2 reintroduced.
- `conftest.py` with the fixtures in the blueprint.
- `test_fixtures.py` — sanity tests (no rdflib needed).

**NOT in scope**: invalid-Turtle fixtures for each validation rule (inline strings in TASK-5259);
`published_store` (TASK-5264); creating the catalog tables (TASK-5265).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/conftest.py` | CREATE | golden + PostgreSQL fixtures |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v1.ttl` | CREATE | golden v1 |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v2.ttl` | CREATE | golden v2 |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v3.ttl` | CREATE | golden v3 |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_fixtures.py` | CREATE | sanity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncpg                          # installed (0.32.0); extra graphindex-postgres: packages/ai-parrot/pyproject.toml:296
import pytest, pytest_asyncio           # pytest-asyncio 1.4.0; asyncio_mode = "auto": packages/ai-parrot/pyproject.toml:1089
from parrot.conf import default_dsn     # verified: parrot/conf.py:72 (None when DB env is unset, :76)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/knowledge/graphindex/test_persist_postgres.py:24-25  (live-DB gating pattern)
PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")
```

### Does NOT Exist
- ~~`testcontainers`~~ — not in any pyproject; tests use a configured live server or skip.
- ~~an existing vocabulary `conftest.py`~~ — created here.
- ~~`rdflib` in the shared venv~~ — not installed until the host step after TASK-5252; this task's
  tests must not import it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v1.ttl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v2.ttl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v3.ttl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_fixtures.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The PostgreSQL fixtures read `ONTOLOGY_PG_DSN`, fall back to `parrot.conf.default_dsn`, and
  **skip** (never fail) when neither is set (spec §4 Integration Tests).
- Each test gets a uniquely named schema (`ontology_store_t_<uuid8>`) dropped with `CASCADE` at
  teardown, so integration tests can run concurrently (spec Worktree Strategy).
- The fixtures must not create the `vector`/`pg_trgm` extensions — `ensure_schema` (TASK-5256) does.
- Golden Turtle is authored by hand; keep each file < 200 lines and comment every v2/v3 change.

---

## Implementation Blueprint

### Steps (in order)
1. Write v1, then derive v2 and v3 by copy-and-edit — *why*: the temporal gate compares them.
2. Write `conftest.py` — *why*: one owner for shared fixtures.
3. Write the sanity tests and run them.

### `.../vocabulary/conftest.py` (CREATE)
```python
"""Shared fixtures for the vocabulary-store tests (FEAT-824)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from parrot.conf import default_dsn  # verified: parrot/conf.py:72

FIXTURES = Path(__file__).parent / "fixtures"
PG_DSN = os.environ.get("ONTOLOGY_PG_DSN") or default_dsn


@pytest.fixture
def golden_v1() -> bytes:
    """legal_es v1: classes, SKOS concepts, a DAG with multiple inheritance."""
    return (FIXTURES / "legal_es.v1.ttl").read_bytes()


@pytest.fixture
def golden_v2() -> bytes:
    """Labels, attributes and relations changed; one deprecation with replacement."""
    return (FIXTURES / "legal_es.v2.ttl").read_bytes()


@pytest.fixture
def golden_v3() -> bytes:
    """A relation removed in v2 comes back."""
    return (FIXTURES / "legal_es.v3.ttl").read_bytes()


@pytest.fixture
def golden_base_iri() -> str:
    """Base IRI shared by the golden files."""
    return "https://ontology.parrot.dev/legal_es/"  # FILL IN: must equal the files' base


@pytest_asyncio.fixture
async def pg_pool() -> AsyncIterator["asyncpg.Pool"]:
    """asyncpg pool to the live test server; skips when no DSN is configured."""
    if not PG_DSN:
        pytest.skip("needs live Postgres (ONTOLOGY_PG_DSN or parrot.conf.default_dsn)")
    import asyncpg

    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def pg_schema_name(pg_pool) -> AsyncIterator[str]:
    """A unique schema name, dropped with CASCADE at teardown."""
    name = f"ontology_store_t_{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
```

### `.../vocabulary/test_fixtures.py` (CREATE)
```python
"""Golden Turtle sanity checks — no rdflib required (FEAT-824 TASK-5255)."""
from __future__ import annotations

import re


def test_golden_files_have_no_blank_nodes(golden_v1, golden_v2, golden_v3) -> None:
    for data in (golden_v1, golden_v2, golden_v3):
        text = data.decode("utf-8")
        assert "_:" not in text
        # FILL IN: assert no anonymous-node "[" outside IRIs/strings (simple regex on lines).


def test_v2_deprecates_with_replacement(golden_v2) -> None:
    text = golden_v2.decode("utf-8")
    assert "owl:deprecated" in text and "dcterms:isReplacedBy" in text


def test_versions_differ(golden_v1, golden_v2, golden_v3) -> None:
    assert len({golden_v1, golden_v2, golden_v3}) == 3


async def test_pg_schema_fixture(pg_pool, pg_schema_name) -> None:
    """The live fixture yields a usable unique schema (skipped without a DSN)."""
    async with pg_pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA "{pg_schema_name}"')
        assert await conn.fetchval("SELECT 1") == 1
```

### FILL IN checklist
- [ ] the three Turtle files per Scope.
- [ ] `golden_base_iri` value matches the files.
- [ ] blank-node bracket check.

---

## Acceptance Criteria

- [ ] v1 satisfies every bullet of Scope; v2 and v3 differ from it exactly as described.
- [ ] No golden file contains a blank node.
- [ ] PostgreSQL fixtures skip cleanly without a DSN and drop their schema when one is set.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_fixtures.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5253 is `done` (it creates the test package `__init__.py`).
2. Mark `in-progress`; implement; run the Validation Commands; commit only the listed files.
3. Close with `parrot sdd task close TASK-5255 ontology-backend verified`; fill in the Completion Note,
   listing every v2/v3 change (later tasks assert on them).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
