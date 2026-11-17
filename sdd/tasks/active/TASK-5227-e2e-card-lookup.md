# TASK-5227: Card lookup: lookup returns the correct citation for a published synthetic contract (M6)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5224
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M6. Spec lists M4/M5 as dependencies, but this test imports nothing from them — only the TASK-5224 fixtures — so those edges are dropped. Scenario `contracts-card-lookup`, covers AC7.

## Scope

- Ingest/publish the synthetic contract, perform the lookup through the public answer path, assert the returned `Citation` has the synthetic `contract_id` and expected `node_id`, and that `EvidenceArchive.resolve` (or `ContractLibrary.load_section`) maps it back.
- Find the real lookup entrypoint first: `wikitoolkit symbols lookup Citation` / grep `-> .*Citation` in `parrot/knowledge/contracts/` — do NOT invent one.
- The test function name is frozen: `test_lookup_cites_published_synthetic_contract` — do not rename (TASK-5224 plan).

**NOT in scope**: conftest/plan edits (TASK-5224 owns them), other scenarios, Postgres.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py` | CREATE | scenario contracts-card-lookup |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
from parrot.knowledge.contracts.models import Citation  # models.py:564
from parrot.knowledge.contracts.evidence import EvidenceArchive, EvidenceRef  # evidence.py:286, :78
from parrot.knowledge.contracts.library import ContractLibrary  # library.py:459
```

### Existing Signatures to Use

| Callable | Signature | Source |
|---|---|---|
| `Citation` | `contract_id, title, node_id, quote, page, verification` | `models.py:564` |
| `EvidenceArchive.resolve` | `async (citation, ref) -> EvidenceLookup` | `evidence.py:462` |
| `ContractLibrary.load_section` | `async (contract_id, node_id, *, source_sha256) -> Optional[str]` | `library.py:1169` |
| `ContractLibrary.__init__` | `(*, catalog, storage_root, evidence_root, adapter=None, indexer_factory=None, content_store_factory=None, ...)` | `library.py:481` |
| ingestion doubles | `FakeIndexer` (`test_ingestion.py:46`), `FakeAdapter` (`test_carding.py:95`) | — |

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
      "path": "packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#Citation",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/evidence.py#EvidenceArchive",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/library.py#ContractLibrary"
  ]
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: contracts-card-lookup: uses fixtures from TASK-5224 (tests/e2e/contracts/conftest.py) and must match node id test_lookup_cites_published_synthetic_contract frozen in its e2e-plan.md.

## Implementation Blueprint

### Steps (in order)

1. Locate the lookup/answer entrypoint that yields `Citation`s (see Scope); if none is reachable without an LLM, assert via `EvidenceArchive.resolve` on a citation built from the published node and record that in the Completion Note.
2. Use `tmp_path` for `storage_root`/`evidence_root`.
3. Write, run.

#### `packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py` (CREATE)

```python
"""E2E scenario `contracts-card-lookup` (FEAT-815) — synthetic fixtures only."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_lookup_cites_published_synthetic_contract(synthetic_card, memory_catalog) -> None:
    """Card lookup: lookup returns the correct citation for a published synthetic contract (M6)."""
    # FILL IN: ingest synthetic DOCX/markdown via ContractLibrary + doubles -> lookup -> assert citation.contract_id == SYNTHETIC_ID and node_id resolves via EvidenceArchive — AC7 (no LLM calls)
```

**Why**: one test per scenario keeps the plan's node-ID → scenario mapping 1:1, which `parrot e2e verify` requires.


### FILL IN checklist

- [ ] Test body (AC7)

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py::test_lookup_cites_published_synthetic_contract` passes offline (no DSN, no network) (AC7).
- [ ] Only synthetic ids/text (AC10).

## Validation Commands

- `pytest packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py::test_lookup_cites_published_synthetic_contract -q`

## Test Specification

| `test_lookup_cites_published_synthetic_contract` | AC7 |

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5227 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
