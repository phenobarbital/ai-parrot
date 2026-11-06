# TASK-5226: Graph publication: temporal drain + loader publish synthetic contract nodes (M5)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5224
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M5. The spec's `TemporalDrain` does not exist — the drain is `ContractTemporalPublisher.drain`. Scenario `contracts-graph-publication`, covers AC6.

## Scope

- Upsert the synthetic card (writes the outbox), publish with `ContractGraphLoader.publish(card)` against `FakeGraphStore`, and drain the temporal outbox with `ContractTemporalPublisher.drain(ctx)` using the `make_ctx`/persistence double pattern from `test_temporal.py`.
- Assert the graph store holds the contract node(s) and `GraphPublicationReport.complete` / `TemporalDrainReport` counts.
- The test function name is frozen: `test_temporal_drain_publishes_synthetic_contract_nodes` — do not rename (TASK-5224 plan).

**NOT in scope**: conftest/plan edits (TASK-5224 owns them), other scenarios, Postgres.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py` | CREATE | scenario contracts-graph-publication |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
from parrot.knowledge.contracts.graph_loader import ContractGraphLoader  # graph_loader.py:182
from parrot.knowledge.contracts.temporal import ContractTemporalPublisher  # temporal.py:156
```

### Existing Signatures to Use

| Callable | Signature | Source |
|---|---|---|
| `ContractGraphLoader.__init__` | `(*, catalog, graph_store, tenant_manager=None, datasource=None, ontology_dir=None, domain=CONTRACTS_DOMAIN)` | `graph_loader.py:197` |
| `ContractGraphLoader.publish` | `async (card) -> GraphPublicationReport` | `graph_loader.py:594` |
| `GraphPublicationReport.complete` | property -> bool | `graph_loader.py:177` |
| `ContractTemporalPublisher.__init__` | `(*, catalog, persistence, agent_id=TEMPORAL_AGENT_ID, now=None)` | `temporal.py:168` |
| `ContractTemporalPublisher.drain` | `async (ctx, *, limit=10) -> TemporalDrainReport` | `temporal.py:184` |
| test helpers | `make_ctx` (`test_temporal.py:61`), `FakeGraphStore` (`test_graph_loader.py:41`) | — |

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
      "path": "packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py#ContractGraphLoader",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py#ContractTemporalPublisher"
  ]
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: contracts-graph-publication: uses fixtures from TASK-5224 (tests/e2e/contracts/conftest.py) and must match node id test_temporal_drain_publishes_synthetic_contract_nodes frozen in its e2e-plan.md.

## Implementation Blueprint

### Steps (in order)

1. Read `test_graph_loader.py` (setup near :198) and `test_temporal.py` (:41–:125) for the exact double wiring — reuse, do not reinvent.
2. If `ContractGraphLoader` requires ontology files, use the same `ontology_dir` the existing test uses.
3. Write, run.

#### `packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py` (CREATE)

```python
"""E2E scenario `contracts-graph-publication` (FEAT-815) — synthetic fixtures only."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_temporal_drain_publishes_synthetic_contract_nodes(synthetic_card, memory_catalog) -> None:
    """Graph publication: temporal drain + loader publish synthetic contract nodes (M5)."""
    # FILL IN: upsert -> ContractGraphLoader(catalog=memory_catalog, graph_store=fake_graph_store).publish(card) -> assert report.complete and node present; drain via ContractTemporalPublisher -> assert report counts — AC6 (add fake_graph_store to the signature)
```

**Why**: one test per scenario keeps the plan's node-ID → scenario mapping 1:1, which `parrot e2e verify` requires.


### FILL IN checklist

- [ ] Test body (AC6)

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py::test_temporal_drain_publishes_synthetic_contract_nodes` passes offline (no DSN, no network) (AC6).
- [ ] Only synthetic ids/text (AC10).

## Validation Commands

- `pytest packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py::test_temporal_drain_publishes_synthetic_contract_nodes -q`

## Test Specification

| `test_temporal_drain_publishes_synthetic_contract_nodes` | AC6 |

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5226 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
