# TASK-5224: E2E plan & synthetic contract fixtures (M3)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M3 (W2). Freezes the three scenario node IDs (spec §4 says they are frozen at decomposition — they are listed below and the scenario tasks MUST use these exact test names).

**Fixture decision**: spec §7 risk 2 assumed Postgres. A complete deterministic in-memory `ContractCatalogStore` double already exists (`InMemoryContractCatalog`, test_catalog_contract.py:66), as do `FakeGraphStore` (test_graph_loader.py:41) and temporal-context helpers (test_temporal.py:61). Use them so the **required** E2E gate does not depend on a live DSN — a required gate that skips without Postgres would block `/sdd-done` forever. Synthetic cards only (AC10).

## Scope

- `tests/e2e/__init__.py`, `tests/e2e/contracts/__init__.py` (empty).
- `conftest.py`: fixtures `synthetic_card` (via `make_card`, synthetic ids like `synthetic-msa-001`), `memory_catalog` (`InMemoryContractCatalog(now=FROZEN_NOW)`), `fake_graph_store`; plus a smoke test file proving the fixtures build.
- `sdd/state/FEAT-815/e2e-plan.md`: frontmatter-only plan (schema below), `targets: {}` — scenarios are in-process, no spawned target.
- Validate the plan with `load_plan`.

**NOT in scope**: The three scenario test files (TASK-5225..5227); Postgres-backed suites.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/e2e/__init__.py` | CREATE | package marker |
| `packages/ai-parrot/tests/e2e/contracts/__init__.py` | CREATE | package marker |
| `packages/ai-parrot/tests/e2e/contracts/conftest.py` | CREATE | synthetic fixtures |
| `packages/ai-parrot/tests/e2e/contracts/test_fixtures_smoke.py` | CREATE | fixture smoke test |
| `sdd/state/FEAT-815/e2e-plan.md` | CREATE | E2E plan, 3 required scenarios |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
from tests.knowledge.contracts.test_catalog_contract import InMemoryContractCatalog, make_card, FROZEN_NOW
# verified: packages/ai-parrot/tests/knowledge/contracts/test_catalog_contract.py:66 (class), :617 (make_card), :57 (FROZEN_NOW)
# `tests/__init__.py` and `tests/knowledge/__init__.py` exist (0 B) — VERIFY the absolute `tests.` import resolves
# under the repo's rootdir before relying on it; if it does not, copy the minimal double into conftest instead of hacking sys.path.
from parrot.e2e.plan import load_plan  # packages/ai-parrot-server/src/parrot/e2e/plan.py:45
```

### Existing Signatures to Use

| Callable | Signature | Source |
|---|---|---|
| `load_plan` | `(path: Path, *, worktree: Path) -> E2EPlan` | `parrot/e2e/plan.py:45` |
| `E2EPlan` | `schema_version: Literal[1]; feature_id; spec_path (relative, no ..); policy; targets: dict = {}; scenarios: list; budget; run_timeout_s` | `parrot/e2e/models.py:240` |
| `ScenarioSpec.target_ids` | `list[str] = []` — empty allowed | `parrot/e2e/models.py:181` |
| `make_card` | `(contract_id: str = "acme-msa", **overrides) -> ContractCard` | `test_catalog_contract.py:617` |
| `FakeGraphStore` | test double | `tests/knowledge/contracts/test_graph_loader.py:41` |
| Reference plan | `sdd/state/FEAT-581/e2e-plan.md` | format exemplar |

### Does NOT Exist

- ~~`parrot.knowledge.contracts.temporal.TemporalDrain`~~ — does not exist; the spec §6 name is wrong. The drain lives on `ContractTemporalPublisher.drain(ctx, *, limit=10) -> TemporalDrainReport` (`temporal.py:156,184`).
- ~~`parrot.knowledge.contracts.datasource.ContractDatasource`~~ — wrong name; the class is `ContractCardDataSource` (`datasource.py:130`).
- ~~`ContractCatalogStore.lookup()` / `.query()`~~ — no such methods; use `search(query, top_k=8) -> list[SearchHit]` (`catalog.py:398`) and `get(contract_id)` (`catalog.py:367`).
- ~~A default Postgres DSN~~ — `PostgresContractCatalog` refuses to build without explicit `dsn` or `pool` (`catalog_postgres.py:294`).
- ~~`packages/ai-parrot/tests/e2e/`~~ — does not exist yet; this task creates it.
- ~~A `kind: library`/`in-process` target~~ — `TargetConfig.kind` is only `mcp-toolkit|mcp-stdio|mcp-agent|botmanager|ui|browser` (models.py:48); use `targets: {}`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/e2e/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/e2e/contracts/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/e2e/contracts/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/e2e/contracts/test_fixtures_smoke.py",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-815/e2e-plan.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: root task of W2; creates tests/e2e/contracts/conftest.py + e2e-plan.md consumed by TASK-5225, TASK-5226, TASK-5227.

## Implementation Blueprint

### Steps (in order)

1. Verify the `tests.knowledge.contracts...` import works from `tests/e2e/contracts/` (`python -c`, with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot`).
2. Create package markers, conftest, smoke test.
3. Write the plan; validate with `python -c "from pathlib import Path; from parrot.e2e.plan import load_plan; print(load_plan(Path('sdd/state/FEAT-815/e2e-plan.md'), worktree=Path('.')))"`.

#### `sdd/state/FEAT-815/e2e-plan.md` (CREATE)

```yaml
---
schema_version: 1
feature_id: FEAT-815
spec_path: sdd/specs/contracts-pilot-signoff-e2e.spec.md
policy: required
targets: {}
run_timeout_s: 600
scenarios:
- id: contracts-catalog-roundtrip
  tier: deterministic
  target_ids: []
  required: true
  node_ids:
  - packages/ai-parrot/tests/e2e/contracts/test_catalog_roundtrip.py::test_synthetic_contract_roundtrips_through_catalog
  timeout_s: 120
  prerequisites: []
  assertions:
  - FILL IN one line per scenario from spec §4
- id: contracts-graph-publication
  tier: deterministic
  target_ids: []
  required: true
  node_ids:
  - packages/ai-parrot/tests/e2e/contracts/test_graph_publication.py::test_temporal_drain_publishes_synthetic_contract_nodes
  timeout_s: 120
  prerequisites: []
  assertions:
  - FILL IN one line per scenario from spec §4
- id: contracts-card-lookup
  tier: deterministic
  target_ids: []
  required: true
  node_ids:
  - packages/ai-parrot/tests/e2e/contracts/test_card_lookup.py::test_lookup_cites_published_synthetic_contract
  timeout_s: 120
  prerequisites: []
  assertions:
  - FILL IN one line per scenario from spec §4
---

# FEAT-815 E2E plan — in-process contracts pipeline scenarios (synthetic fixtures only).
```

**Why**: node IDs are frozen here so `parrot e2e verify` can match evidence to scenarios; changing a test name later silently breaks the gate. Copy `budget:` from the FEAT-581 plan only if `load_plan` requires it (it has a default factory).

#### `packages/ai-parrot/tests/e2e/contracts/conftest.py` (CREATE)

```python
"""Synthetic fixtures for the FEAT-815 contracts E2E scenarios — no real contract text."""
from __future__ import annotations

import pytest

# FILL IN: imports per Verified Imports (InMemoryContractCatalog, make_card, FROZEN_NOW, FakeGraphStore)
#          — verify the `tests.` absolute import resolves first.

SYNTHETIC_ID = "synthetic-msa-001"


@pytest.fixture()
def synthetic_card():
    """A fully synthetic contract card."""
    return make_card(SYNTHETIC_ID)


@pytest.fixture()
def memory_catalog():
    """Deterministic in-memory catalog with a frozen clock."""
    return InMemoryContractCatalog(now=FROZEN_NOW)


# FILL IN: fake_graph_store fixture mirroring test_graph_loader.py usage (graph_store=FakeGraphStore()).
```

**Why**: conftest is shared by three downstream tasks; keep it minimal and stable — scenario-specific setup belongs in each test file.


### FILL IN checklist

- [ ] conftest imports + `fake_graph_store`
- [ ] smoke test body
- [ ] plan `assertions` lines

## Acceptance Criteria

- [ ] `load_plan` accepts `sdd/state/FEAT-815/e2e-plan.md` with policy `required` and 3 required deterministic scenarios.
- [ ] Node IDs exactly as listed in this task.
- [ ] Fixtures build without Postgres or network; only synthetic ids (AC10).

## Validation Commands

- `pytest packages/ai-parrot/tests/e2e/contracts/test_fixtures_smoke.py -q`

## Test Specification

| `test_fixtures_build_offline` | synthetic card + memory catalog + fake graph store construct |

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5224 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
