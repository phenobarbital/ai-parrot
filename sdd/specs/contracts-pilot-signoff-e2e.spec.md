---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [contracts, ontology, pilot, e2e, acceptance]
e2e:
  policy: required
  scenario_ids:
    - contracts-catalog-roundtrip
    - contracts-graph-publication
    - contracts-card-lookup
docs:
  policy: required
  pages:
    - wiki/knowledge/contracts-pilot-acceptance.md
---

# Feature Specification: Contracts Pilot Signoff & End-to-End Validation

**Feature ID**: FEAT-815
**Date**: 2026-11-05
**Author**: Jesus Lara / Claude
**Status**: draft
**Target version**: 2.1.x
**Parent**: FEAT-539 (contracts-card-ontology)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-539 delivered the contracts card & ontology data plane — catalog,
carding, evidence, temporal publication, ontology projection and graph
loading — all merged to `dev` (PRs #1347, #1349, 2026-09-09). Two
deliverables remain unfinished:

1. **Pilot acceptance (AC15)** — Bob's twelve-case pilot review was never
   started. The external acceptance task (TASK-3056) was force-closed
   because the operational inputs (verbatim questions, pilot corpus,
   reviewer availability) never materialized. Without signoff, the feature
   cannot be reported as pilot-accepted per spec §4–5.

2. **End-to-end test coverage** — The contracts pipeline has unit and
   integration tests but no deterministic E2E gate. The original spec
   shipped with `e2e.policy: optional` and no E2E plan, so regressions in
   the full pipeline (ingestion → carding → publication → lookup) are
   caught only by manual testing.

### Goals

- G1: Provide a structured pilot acceptance workflow with a twelve-case
  review matrix, disposition tracking, and explicit signoff recording.
- G2: Deliver deterministic E2E test scenarios covering the contracts
  pipeline end-to-end, wired into the `parrot e2e` gate framework.
- G3: Update the GitHub wiki page
  `wiki/knowledge/contracts-pilot-acceptance.md` with acceptance results
  once the pilot completes.

### Non-Goals (explicitly out of scope)

- Modifying the contracts data plane itself (catalog, carding, models,
  relations, temporal) — that is FEAT-539 code, already merged.
- Building a UI for the pilot review — this is CLI/script-driven.
- Automatic outreach or scheduling — Bob reviews on his own schedule.
- OCR or new ingestion backends.
- Real contract text committed to the repository — all evidence references
  use `contract_id`/`node_id`/`version_n`/`answer_id`, never raw text.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:d2e34a0e96a3c34c326cf2ddadfd46da74a79806cfba1fb180c2c8a3f31cb795 evaluation_digest=sha256:7dc57fe27e95bd01fcc10841eb93ca2c99cf641a7c9571e218e43b626d612fa4 rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, skills, tools

## 2. Architectural Design

### Overview

Two independent workstreams in one feature:

**W1 — Pilot Acceptance Framework** builds a CLI tool
(`parrot contracts pilot`) that loads a case matrix from a YAML file,
executes each case against the contracts catalog adapters (lookup +
citation), records reviewer feedback and disposition, and writes a
structured signoff artifact to `sdd/state/FEAT-815/pilot-signoff.json`.

**W2 — E2E Test Coverage** defines three deterministic E2E scenarios using
the `parrot e2e` fixture framework: catalog roundtrip, graph publication,
and card lookup. These use synthetic contract fixtures (no real contract
text), run via `parrot e2e run`, and produce gate evidence consumed by
`parrot e2e verify`.

W2 can proceed independently with synthetic fixtures. W1 depends on
external operational inputs and will block on Bob's availability.

### Component Diagram

```
W1: Pilot Acceptance
  case_matrix.yaml → pilot CLI → ContractCatalogStore → disposition.json → signoff artifact

W2: E2E Tests
  synthetic fixtures → pytest (parrot e2e plugin) → ScenarioResult → E2EVerdict
    ├── contracts-catalog-roundtrip: ingest → query → verify fields
    ├── contracts-graph-publication: ingest → temporal drain → verify graph nodes
    └── contracts-card-lookup: ingest → publish → lookup → verify citation
```

### Integration Points

| Component | Location | Integration |
|---|---|---|
| `ContractCatalogStore` | `parrot/knowledge/contracts/catalog.py:292` | W1 case execution, W2 roundtrip |
| `PostgresContractCatalog` | `parrot/knowledge/contracts/catalog_postgres.py` | W1+W2 concrete catalog |
| `ContractLibrary` | `parrot/knowledge/contracts/library.py` | W2 ingestion scenarios |
| `ContractGraphLoader` | `parrot/knowledge/contracts/graph_loader.py` | W2 publication scenario |
| `E2EPlan` / `load_plan` | `parrot/e2e/plan.py:45` | W2 plan loading |
| `run_plan` | `parrot/e2e/runner.py:66` | W2 scenario execution |
| `NodeContentStore` | `parrot/knowledge/pageindex/content_store.py` | W2 lookup verification |

---

## 3. Module Breakdown

### M1 — Pilot Case Matrix Schema (W1)

Define the YAML schema for the twelve-case review matrix and a Pydantic
model to load/validate it.

**Files:**
- CREATE `packages/ai-parrot/src/parrot/knowledge/contracts/pilot.py`
  — `CaseMatrix`, `PilotCase`, `CaseDisposition`, `PilotSignoff` models
- CREATE `sdd/state/FEAT-815/case_matrix_template.yaml`
  — template with placeholder cases

**Interface Skeleton:**
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/pilot.py
from pydantic import BaseModel

class PilotCase(BaseModel):
    """One of the twelve review cases."""
    case_id: str
    question: str
    expected_answer: str | None
    source: str  # "client_initial" | "common"

class CaseDisposition(BaseModel):
    """Reviewer's disposition for one case."""
    case_id: str
    actual_answer: str | None
    citations: list[str]
    feedback: str
    disposition: str  # "pass" | "fail" | "skip"
    reviewer: str
    reviewed_at: str  # ISO-8601

class CaseMatrix(BaseModel):
    """The full twelve-case review matrix."""
    cases: list[PilotCase]

class PilotSignoff(BaseModel):
    """Explicit signoff record."""
    feature_id: str
    reviewer: str
    signed_off_at: str | None
    dispositions: list[CaseDisposition]
    notes: str
```

### M2 — Pilot CLI Commands (W1)

CLI subcommands under `parrot contracts pilot` for running cases and
recording dispositions.

**Files:**
- CREATE `packages/ai-parrot/src/parrot/sdd/scripts/contracts_pilot.py`
  — `run_case`, `record_disposition`, `generate_signoff` commands

**Depends on:** M1

### M3 — E2E Plan & Synthetic Fixtures (W2)

The E2E plan and synthetic contract fixtures for deterministic testing.

**Files:**
- CREATE `sdd/state/FEAT-815/e2e-plan.md` — E2E plan with three scenarios
- CREATE `packages/ai-parrot/tests/e2e/contracts/conftest.py`
  — synthetic catalog fixtures (no real contract text)
- CREATE `packages/ai-parrot/tests/e2e/contracts/__init__.py`

### M4 — E2E Scenario: Catalog Roundtrip (W2)

Ingest a synthetic contract, query it back, verify all fields match.

**Files:**
- CREATE `packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py`

**Depends on:** M3

### M5 — E2E Scenario: Graph Publication (W2)

Ingest a synthetic contract, run the temporal drain, verify graph nodes
exist in the published tree.

**Files:**
- CREATE `packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py`

**Depends on:** M3

### M6 — E2E Scenario: Card Lookup (W2)

Ingest, publish, perform a lookup query, verify the citation references
the correct contract/obligation/node.

**Files:**
- CREATE `packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py`

**Depends on:** M3, M4, M5 (citation depends on published graph)

### M7 — Wiki Documentation Update (W1+W2)

Update the GitHub wiki page with acceptance results and E2E coverage notes.

**Files:**
- MODIFY `wiki/knowledge/contracts-pilot-acceptance.md`

**Depends on:** M1, M6

**Delegation-eligible modules:**

| Module | Delegation eligible | Reason |
|---|---|---|
| M1 | yes | Pure Pydantic models, mechanical |
| M2 | no | CLI design decisions needed |
| M3 | yes | Fixture setup, plan YAML |
| M4 | yes | Single test file, pattern established |
| M5 | yes | Single test file, pattern established |
| M6 | partially | Depends on M4+M5 outputs |
| M7 | yes | Wiki page update, mechanical |

---

## 4. Test Specification

### Integration Tests

| Test | File | Verifies |
|---|---|---|
| Case matrix loading | `packages/ai-parrot/tests/knowledge/contracts/test_pilot_matrix.py` | M1 schema validation |
| Disposition recording | `packages/ai-parrot/tests/knowledge/contracts/test_pilot_dispositions.py` | M1+M2 round-trip |

### E2E Scenarios

| Scenario ID | Tier | Required | Description |
|---|---|---|---|
| `contracts-catalog-roundtrip` | deterministic | yes | Ingest → query → field match |
| `contracts-graph-publication` | deterministic | yes | Ingest → drain → verify graph |
| `contracts-card-lookup` | deterministic | yes | Ingest → publish → lookup → citation |

### Validation Contract

`none — fallback`

---

## 5. Acceptance Criteria

- [ ] AC1: A `CaseMatrix` model loads and validates a twelve-case YAML file.
- [ ] AC2: `parrot contracts pilot run-case` executes a case against the
  catalog and records lookup citations.
- [ ] AC3: `parrot contracts pilot record` records a reviewer disposition
  with date/reviewer/evidence references.
- [ ] AC4: `parrot contracts pilot signoff` writes a signoff artifact to
  `sdd/state/FEAT-815/pilot-signoff.json` with all twelve dispositions.
- [ ] AC5: E2E scenario `contracts-catalog-roundtrip` passes: synthetic
  contract ingested and queried back with matching fields.
- [ ] AC6: E2E scenario `contracts-graph-publication` passes: temporal drain
  produces graph nodes from synthetic contract.
- [ ] AC7: E2E scenario `contracts-card-lookup` passes: lookup returns
  correct citation for a published synthetic contract.
- [ ] AC8: `parrot e2e verify --plan sdd/state/FEAT-815/e2e-plan.md` reports
  `gate_satisfied: true` with all three scenarios passing.
- [ ] AC9: `wiki/knowledge/contracts-pilot-acceptance.md` updated with
  signoff results (or placeholder noting pending).
- [ ] AC10: No real contract text committed — all evidence uses
  `contract_id`/`node_id`/`version_n`/`answer_id` references only.

---

## 6. Codebase Contract

Verified against `dev` at commit `b3225cbd1b` (2026-11-05).

### Verified Imports

```python
from parrot.knowledge.contracts.catalog import ContractCatalogStore  # packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py:292
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog  # packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py
from parrot.knowledge.contracts.models import ContractCard  # packages/ai-parrot/src/parrot/knowledge/contracts/models.py
from parrot.knowledge.contracts.library import ContractLibrary  # packages/ai-parrot/src/parrot/knowledge/contracts/library.py
from parrot.knowledge.contracts.graph_loader import ContractGraphLoader  # packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py
from parrot.knowledge.contracts.evidence import EvidenceArchive  # packages/ai-parrot/src/parrot/knowledge/contracts/evidence.py
from parrot.knowledge.contracts.temporal import TemporalDrain  # packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py
from parrot.knowledge.contracts.datasource import ContractDatasource  # packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py
from parrot.knowledge.pageindex.content_store import NodeContentStore  # packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
from parrot.e2e.plan import load_plan, E2EPlan  # packages/ai-parrot-server/src/parrot/e2e/plan.py:45
from parrot.e2e.runner import run_plan  # packages/ai-parrot-server/src/parrot/e2e/runner.py:66
```

### Existing Signatures to Use

| Callable | Signature | Source |
|---|---|---|
| `ContractCatalogStore` | `class ContractCatalogStore(ABC)` | `catalog.py:292` |
| `PostgresContractCatalog` | `__init__(self, dsn, tenant_id, schema)` | `catalog_postgres.py` |
| `load_plan` | `(path: Path, *, worktree: Path) -> E2EPlan` | `plan.py:45` |
| `run_plan` | `async (plan_path: Path, *, worktree: Path, owner_id: str) -> E2EVerdict` | `runner.py:66` |
| `NodeContentStore.loader_for` | `(self, tree_name: str) -> Callable[[str], Optional[str]]` | `content_store.py` |

### Does NOT Exist

- `parrot.knowledge.contracts.pilot` — DOES NOT EXIST (M1 creates it)
- `parrot.sdd.scripts.contracts_pilot` — DOES NOT EXIST (M2 creates it)
- `packages/ai-parrot/tests/e2e/contracts/` — DOES NOT EXIST (M3 creates it)

### Edit Sites

| File | Action | Anchor | Count |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/pilot.py` | CREATE | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/contracts_pilot.py` | CREATE | — | — |
| `sdd/state/FEAT-815/e2e-plan.md` | CREATE | — | — |
| `sdd/state/FEAT-815/case_matrix_template.yaml` | CREATE | — | — |
| `packages/ai-parrot/tests/e2e/contracts/conftest.py` | CREATE | — | — |
| `packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py` | CREATE | — | — |
| `packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py` | CREATE | — | — |
| `packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py` | CREATE | — | — |
| `packages/ai-parrot/tests/knowledge/contracts/test_pilot_matrix.py` | CREATE | — | — |
| `packages/ai-parrot/tests/knowledge/contracts/test_pilot_dispositions.py` | CREATE | — | — |
| `wiki/knowledge/contracts-pilot-acceptance.md` | MODIFY | `# Contracts pilot acceptance` | 1 |

Base commit: `b3225cbd1b`

---

## 7. Known Risks / Gotchas

1. **W1 blocks on external inputs** — Bob's twelve questions and pilot
   corpus availability are not under our control. W2 proceeds independently.
2. **E2E scenarios need a Postgres instance** — The contracts catalog is
   Postgres-only (`PostgresContractCatalog`). E2E fixtures must provision a
   test schema. The existing test infrastructure at
   `packages/ai-parrot/tests/knowledge/contracts/` shows the pattern.
3. **`docs/knowledge/contracts-pilot-acceptance.md` was moved** — FEAT-801
   (commit `321c9883a3`) migrated docs to the GitHub wiki. The file now
   lives at `wiki/knowledge/contracts-pilot-acceptance.md`.

### External Dependencies

| Library | Purpose | Already in tree |
|---|---|---|
| `asyncpg` | Postgres catalog tests | yes |
| `rapidfuzz` | Contract matching | yes |
| `pydantic` | Case matrix models | yes |
| `PyYAML` | Case matrix file loading | yes |

---

## Consequences

<!-- decision-audit: input_digest=sha256:d2e34a0e96a3c34c326cf2ddadfd46da74a79806cfba1fb180c2c8a3f31cb795 evaluation_digest=sha256:7dc57fe27e95bd01fcc10841eb93ca2c99cf641a7c9571e218e43b626d612fa4 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/contracts-pilot-signoff-e2e.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: acceptance, contracts, e2e, ontology, pilot
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "acceptance",
      "contracts",
      "e2e",
      "ontology",
      "pilot"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/contracts-pilot-signoff-e2e.spec.md"
    }
  ],
  "evaluation_digest": "sha256:7dc57fe27e95bd01fcc10841eb93ca2c99cf641a7c9571e218e43b626d612fa4",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:d2e34a0e96a3c34c326cf2ddadfd46da74a79806cfba1fb180c2c8a3f31cb795",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [ ] When will Bob's twelve cases and the pilot corpus be available? — *Owner: Jesus*
- [ ] Should the E2E tests use real contract fixtures or synthetic ones? — *Recommendation: synthetic, to avoid committing sensitive text*
- [ ] What is the target timeline for pilot completion? — *Owner: Jesus*

---

## 9. Design Research Cross-Check

Status: skipped (proposal not marked accepted)

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## 10. Documentation

| Page | Description |
|---|---|
| `wiki/knowledge/contracts-pilot-acceptance.md` | Update with acceptance results and E2E coverage notes |

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`.
- **Module dependency graph**: M2 → M1 (CLI uses models); M4,M5,M6 → M3
  (scenarios use fixtures); M6 → M4,M5 (lookup depends on published graph);
  M7 → M1,M6 (wiki update after acceptance + E2E).
- **Shared files**: none — all files are new CREATEs.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none — FEAT-539 is already merged.
