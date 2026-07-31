---
type: Wiki Overview
title: 'TASK-1207: Regression + integration tests for cache contract & tool workflow'
id: doc:sdd-tasks-completed-task-1207-regression-and-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: End-to-end coverage that the production bugs (`pokemon.stores`
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
---

# TASK-1207: Regression + integration tests for cache contract & tool workflow

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1204, TASK-1205, TASK-1206
**Assigned-to**: unassigned

---

## Context

End-to-end coverage that the production bugs (`pokemon.stores`
disappearing for `search_term="store"`, `networkninja.forms +
organizations` JOIN failing because columns came back empty) are
fixed and stay fixed.

Implements **Module 7** of the spec.

---

## Scope

Add the following tests under
`packages/ai-parrot/tests/bots/database/`. Reuse / extend
`conftest.py` for fixtures (`stub_metadata`, `full_metadata`,
`seeded_pg`) per spec §4.

Integration tests (PG-fixture-backed):
- `test_pokemon_stores_alaska_regression`
  Seed `pokemon.stores(store_id, store_name, state_code)` as a
  `NAME_ONLY` stub. Run the full agent flow
  `search_schema("store") → describe_table("pokemon", "stores")
  → generate_query(...)` and assert the resulting skeleton
  references the real `state_code` column.
- `test_networkninja_join_regression`
  Seed `networkninja.forms` + `networkninja.organizations` as
  `NAME_ONLY` stubs. Ask the agent for a JOIN; assert
  `describe_table` is called for both, and the output contains
  both column lists.
- `test_no_columns_yaml_does_not_silently_succeed`
  `to_yaml_context()` on a `NAME_ONLY` stub always emits
  `_warning` (already covered as a unit test in TASK-1201; here
  re-assert via the full toolkit-rendered output).
- `test_frontend_pre_warm_completeness_tagging`
  Parse a mixed `[NAME_ONLY]` / `[WITH_COLUMNS]` block using the
  navigator-plugins parser logic *as imported* (skip if not
  available — this test belongs primarily downstream but mirrors
  the contract here for fast-fail).
- `test_pg_catalog_full_introspection_matches_information_schema`
  For a seeded table, the new `pg_catalog`-based introspection
  returns at least the union of fields the old `information_schema`
  query returned.

Additionally:
- A `pytest` marker `@pytest.mark.integration` on the PG tests so
  they can be selected / skipped per environment.
- A short CI note in the task completion (do not touch CI config
  here unless trivially needed).

Fixtures to add / extend in
`packages/ai-parrot/tests/bots/database/conftest.py`:
- `stub_metadata`, `full_metadata` (spec §4 Test Data).
- `seeded_pg` — creates `pokemon.stores`, `networkninja.forms`,
  `networkninja.organizations` on the test PG; drops on teardown.

**NOT in scope**: navigator-plugins parser changes (Module 8 —
downstream), frontend emitter (Module 9 — downstream).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/database/conftest.py` | MODIFY | Add `stub_metadata`, `full_metadata`, `seeded_pg` fixtures |
| `packages/ai-parrot/tests/bots/database/test_integration_regression.py` | CREATE | Integration regression tests |
| `packages/ai-parrot/tests/bots/database/test_pg_catalog_introspection.py` | CREATE or MODIFY | Cross-check vs `information_schema` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.cache import CachePartition, CachePartitionConfig
from parrot.bots.database.toolkits.sql import SQLToolkit
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.agent import DatabaseAgent
```

### Existing Fixtures
```python
# packages/ai-parrot/tests/conftest.py — confirm what's already provided
# (pg_pool / db connection fixture, etc.) — read before authoring new ones
```

### Does NOT Exist
- `seeded_pg`, `stub_metadata`, `full_metadata` fixtures —
  introduced here.
- The `pokemon` and `networkninja` schemas — created and dropped
  by the fixture, not assumed to exist.

---

## Implementation Notes

### Fixture skeleton (spec §4)
```python
@pytest.fixture
def stub_metadata():
    return TableMetadata(
        schema="pokemon", tablename="stores",
        table_type="BASE TABLE", full_name='"pokemon"."stores"',
        completeness=Completeness.NAME_ONLY, source="frontend",
    )

@pytest.fixture
def full_metadata():
    return TableMetadata(
        schema="pokemon", tablename="stores",
        table_type="BASE TABLE", full_name='"pokemon"."stores"',
        completeness=Completeness.FULL, source="pg_catalog",
        columns=[
            {"name": "store_id", "type": "integer", "nullable": False},
            {"name": "store_name", "type": "varchar", "nullable": True},
            {"name": "state_code", "type": "char(2)", "nullable": True},
        ],
        primary_keys=["store_id"],
    )

@pytest.fixture
async def seeded_pg(pg_pool):
    async with pg_pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS pokemon")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS networkninja")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pokemon.stores (
                store_id    SERIAL PRIMARY KEY,
                store_name  VARCHAR(255),
                state_code  CHAR(2)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS networkninja.organizations (
                org_id          SERIAL PRIMARY KEY,
                organization    VARCHAR(255)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS networkninja.forms (
                form_id     SERIAL PRIMARY KEY,
                form_name   VARCHAR(255),
                org_id      INT REFERENCES networkninja.organizations(org_id)
            )
        """)
    yield
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA IF EXISTS pokemon CASCADE")
        await conn.execute("DROP SCHEMA IF EXISTS networkninja CASCADE")
```

### Regression test pattern
```python
@pytest.mark.integration
async def test_pokemon_stores_alaska_regression(
    seeded_pg, pg_toolkit, cache_partition,
):
    # Pre-warm cache with a NAME_ONLY stub only
    await cache_partition.store_table_metadata(TableMetadata(
        schema="pokemon", tablename="stores",
        table_type="BASE TABLE", full_name='"pokemon"."stores"',
        completeness=Completeness.NAME_ONLY, source="frontend",
    ))

    hits = await pg_toolkit.search_schema("store")
    assert any(h.schema == "pokemon" and h.tablename == "stores" for h in hits)

    described = await pg_toolkit.describe_table("pokemon", "stores")
    assert described.completeness == Completeness.FULL
    assert {c["name"] for c in described.columns} >= {
        "store_id", "store_name", "state_code",
    }

    out = await pg_toolkit.generate_query(
        "stores in alaska", target_tables=["pokemon.stores"],
    )
    assert "state_code" in out
    assert "SELECT" in out
```

### `information_schema` cross-check
For `test_pg_catalog_full_introspection_matches_information_schema`,
fetch the canonical four-tuple (`column_name`, `data_type`,
`is_nullable`, `column_default`) from
`information_schema.columns` for `pokemon.stores` and compare to
the columns produced by `pg_toolkit._build_table_metadata`.
Assert subset / set-equality on column names; types may differ
in formatting (`character(2)` vs `char(2)`) — normalise before
asserting.

### CI marker
Mark all PG-fixture tests with `@pytest.mark.integration` so CI
can opt-in. If `pytest.ini` / `pyproject.toml` doesn't declare
the marker yet, add a one-line registration to
`pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: requires a live database connection",
]
```

---

## Acceptance Criteria

- [ ] `stub_metadata`, `full_metadata`, `seeded_pg` fixtures exist
      and clean up after themselves
- [ ] `test_pokemon_stores_alaska_regression` passes
- [ ] `test_networkninja_join_regression` passes
- [ ] `test_no_columns_yaml_does_not_silently_succeed` passes
- [ ] `test_pg_catalog_full_introspection_matches_information_schema`
      passes
- [ ] `@pytest.mark.integration` marker is registered
- [ ] All unit tests from TASK-1201..1206 still pass
- [ ] `pytest packages/ai-parrot/tests/bots/database/ -v -m integration`
      green
- [ ] `pytest packages/ai-parrot/tests/bots/database/ -v -m "not integration"`
      green

---

## Test Specification

See "Implementation Notes" above for the per-test skeletons.

---

## Agent Instructions

1. Confirm TASK-1204, TASK-1205, TASK-1206 are in
   `sdd/tasks/completed/`.
2. Read `packages/ai-parrot/tests/conftest.py` to discover the
   existing PG fixture (likely `pg_pool` or similar) — reuse it.
3. Implement fixtures + tests.
4. Run the full DB test suite locally (requires a running test PG).
5. Move task file to `completed/` and update the per-spec index.
6. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- Added `stub_metadata`, `full_metadata`, `test_cache_partition`, `pg_pool`, `pg_toolkit`, `seeded_pg`, `seeded_pg_with_fks` fixtures to `tests/bots/database/conftest.py`. PG fixtures skip automatically when `PARROT_TEST_PG_DSN` is unset or `asyncpg` is not installed.
- Created `test_integration_regression.py` with 34 total tests across 8 test classes and top-level functions:
  - `TestCompletenessGating` — completeness ordering and `satisfies()` contract
  - `TestYamlContextRegression` — NAME_ONLY/WITH_COLUMNS stubs emit `_warning`; FULL does not
  - `TestSearchSchemaRegressionUnit` — Bug 1 regression: NAME_ONLY stubs from cache are never discarded; DB and cache results are always merged; higher completeness wins on collision
  - `TestDescribeTableRegressionUnit` — describe_table promotes stubs to FULL, stores result in cache, short-circuits on cached FULL, returns None for missing tables
  - `TestGenerateQueryRegressionUnit` — Bug 2 regression: real columns used (not `*`), both JOIN tables described, falls back to search_schema when no target tables
  - `TestMetadataSourceRegression` — PostgresToolkit uses `"pg_catalog"`, SQLToolkit uses `"information_schema"`
  - `TestCachePartitionUnit` — in-memory store/retrieve, completeness gate enforcement, TTL defaults
  - `test_frontend_pre_warm_completeness_tagging` — skip when `navigator_plugins` not available; enum values asserted when present
  - 4 `@pytest.mark.integration` tests: pokemon/stores alaska end-to-end, networkninja JOIN, yaml warning via toolkit flow, pg_catalog vs information_schema cross-check
- 152 unit tests pass (`-m "not integration"`), 8 integration tests deselected, 1 skipped; ruff clean.
