# TASK-5225: Catalog roundtrip: synthetic card upserted and read back with matching fields (M4)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5224
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M4. Scenario `contracts-catalog-roundtrip`, covers AC5.

## Scope

- Upsert the synthetic card, read back via `get` and `search`, assert field equality.
- The test function name is frozen: `test_synthetic_contract_roundtrips_through_catalog` — do not rename (TASK-5224 plan).

**NOT in scope**: conftest/plan edits (TASK-5224 owns them), other scenarios, Postgres.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py` | CREATE | scenario contracts-catalog-roundtrip |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
from parrot.knowledge.contracts.catalog import UpsertResult, SearchHit  # catalog.py:195, :188
```

### Existing Signatures to Use

| Callable | Signature | Source |
|---|---|---|
| `upsert` | `async (card, *, expected_revision=None, version=None, targets=("ontology","temporal")) -> UpsertResult` | `catalog.py:339` |
| `get` | `async (contract_id) -> Optional[ContractCard]` | `catalog.py:367` |
| `search` | `async (query, top_k=8) -> list[SearchHit]` | `catalog.py:398` |

### Does NOT Exist

- ~~`parrot.knowledge.contracts.temporal.TemporalDrain`~~ — does not exist; the spec §6 name is wrong. The drain lives on `ContractTemporalPublisher.drain(ctx, *, limit=10) -> TemporalDrainReport` (`temporal.py:156,184`).
- ~~`parrot.knowledge.contracts.datasource.ContractDatasource`~~ — wrong name; the class is `ContractCardDataSource` (`datasource.py:130`).
- ~~`ContractCatalogStore.lookup()` / `.query()`~~ — no such methods; use `search(query, top_k=8) -> list[SearchHit]` (`catalog.py:398`) and `get(contract_id)` (`catalog.py:367`).
- ~~A default Postgres DSN~~ — `PostgresContractCatalog` refuses to build without explicit `dsn` or `pool` (`catalog_postgres.py:294`).

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py#ContractCatalogStore"
  ]
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: contracts-catalog-roundtrip: uses fixtures from TASK-5224 (tests/e2e/contracts/conftest.py) and must match node id test_synthetic_contract_roundtrips_through_catalog frozen in its e2e-plan.md.

## Implementation Blueprint

### Steps (in order)

1. Read `InMemoryContractCatalog.search` to learn what text it matches on.
2. Write the test; run it.

#### `packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py` (CREATE)

```python
"""E2E scenario `contracts-catalog-roundtrip` (FEAT-815) — synthetic fixtures only."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_synthetic_contract_roundtrips_through_catalog(synthetic_card, memory_catalog) -> None:
    """Catalog roundtrip: synthetic card upserted and read back with matching fields (M4)."""
    # FILL IN: upsert -> get -> assert model_dump equality on identity/party/date fields; search(<synthetic title term>) hit contains SYNTHETIC_ID — AC5
```

**Why**: one test per scenario keeps the plan's node-ID → scenario mapping 1:1, which `parrot e2e verify` requires.


### FILL IN checklist

- [ ] Test body (AC5)

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py::test_synthetic_contract_roundtrips_through_catalog` passes offline (no DSN, no network) (AC5).
- [ ] Only synthetic ids/text (AC10).

## Validation Commands

- `pytest packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py::test_synthetic_contract_roundtrips_through_catalog -q`

## Test Specification

| `test_synthetic_contract_roundtrips_through_catalog` | AC5 |

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5225 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
