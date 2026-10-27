# TASK-4467: Clean-room model loader, graph scoping and fixtures (M4b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4465, TASK-4466, TASK-4705
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M4; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited. The historical filename is retained for ID/path continuity; no sidemantic loader/adapter/spike remains in scope.

## Scope

- Replace the old loader/spike task entirely: load own YAML and Ossie into SemanticModel; no sidemantic adapter, engine dispatch or compatibility shim.
- Implement PhysicalSchema, LoadedModel.model/related_models/policy/members/schema/model_digest/policy_digest/compiler_version and SemanticModelLoader load/reload_if_changed.
- Resolve the complete directory graph before policy binding; derive reachable physical schema, semantic-to-physical provenance and manifest. Include related-model definitions in root digest so dependent caches cannot remain current after changes.
- Create deterministic orders/customers own-format fixtures and shared tests/_models.py helpers. Derive Ossie lowering from its validated public schema and reject unsupported constructs rather than guessing.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/_models.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_loader.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticPolicyError
from .model import SemanticModel, validate_model_graph
from .models import ModelMember
from .ossie import is_ossie_document, validate_ossie_document
from .policy import ModelPolicy, load_policy
from __future__ import annotations
from parrot.semantic.loader import SemanticModelLoader
from pathlib import Path
from pydantic import BaseModel, ConfigDict
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

### Dependency Contracts and Parallelism Evidence

- TASK-4465: consumes packages/ai-parrot-semantic/src/parrot/semantic/policy.py (Model policy validation and role grants (M3))
- TASK-4466: consumes packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json, packages/ai-parrot-semantic/src/parrot/semantic/ossie.py (Vendored Ossie 0.1.1 validation (M4 import boundary))
- TASK-4705: consumes packages/ai-parrot-semantic/src/parrot/semantic/model.py (Frozen semantic graph and structural validation (M4a))

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/loader.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/_models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/fixtures/models/orders.yml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_loader.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

### `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` (CREATE)

```python
"""Own-format and Ossie loader into the typed semantic graph."""
from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from .model import SemanticModel, validate_model_graph
from .models import ModelMember
from .policy import ModelPolicy, load_policy
from .ossie import is_ossie_document, validate_ossie_document
from .errors import SemanticPolicyError

class PhysicalSchema(BaseModel):
    """Qualified physical columns and types for AST qualification."""
    driver: str
    tables: dict[str, dict[str, str]]
    def sqlglot_schema(self) -> dict:
        """Return the dialect-aware nested schema accepted by sqlglot."""
        # FILL IN: preserve catalog/schema/table qualification; no DB I/O.
        ...

class LoadedModel(BaseModel):
    """Model with resolved graph, policy and deterministic version digests."""
    name: str
    model: SemanticModel
    related_models: dict[str, SemanticModel]
    policy: ModelPolicy
    members: list[ModelMember]
    schema: PhysicalSchema
    model_digest: str
    policy_digest: str
    compiler_version: str

class SemanticModelLoader:
    """Publish an immutable, completely validated model-directory snapshot."""
    def __init__(self, models_dir: Path, *, driver: str) -> None:
        self.models_dir = models_dir
        self.driver = driver
    def load(self) -> dict[str, LoadedModel]:
        """Load model/policy pairs, rejecting unsupported format or bindings."""
        # FILL IN: YAML/Ossie lowering, graph validation, policies, schema and digests.
        ...
    def reload_if_changed(self) -> bool:
        """Atomically replace the snapshot only after full validation."""
        # FILL IN: track directory fingerprint, return whether versions moved.
        ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/_models.py` (CREATE)

```python
"""Deterministic warehouse and model helpers for semantic tests."""
from pathlib import Path
import pytest
from parrot.semantic.loader import SemanticModelLoader

@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """Copy own-format fixture definitions into an isolated directory."""
    # FILL IN: copy declared fixtures and companion customers graph; no credentials.
    ...

@pytest.fixture
def loaded_models(models_dir: Path) -> dict:
    """Load the same typed model snapshot used by compiler/governance tests."""
    return SemanticModelLoader(models_dir, driver="duckdb").load()

@pytest.fixture
def duckdb_warehouse(tmp_path: Path) -> Path:
    """Seed sales.orders and dim.customers in a real file, with two tenant subsets."""
    # FILL IN: use duckdb synchronously in fixture setup and close connection;
    # key columns id/customer_id plus tenant_id/region/order_date/amount and email/salary.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml` (CREATE)

```yaml
models:
  - name: orders
    table: sales.orders
    columns: {id: INTEGER, customer_id: INTEGER, region: VARCHAR, tenant_id: VARCHAR, order_date: TIMESTAMP, amount: DECIMAL}
    primary_key: [id]
    dimensions:
      - {name: region, kind: categorical, column: region}
      - {name: order_date, kind: time, column: order_date, grain: month}
    metrics:
      - {name: revenue, agg: sum, column: amount}
      - {name: order_count, agg: count}
    relationships: []
# FILL IN: add customers model here (same directory graph) and customers→orders
# paired keys; validate envelope lowering to exact SemanticModel definitions (AC24).
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml` (CREATE)

```yaml
governed: true
connection: semantic_test
limits: {default: 1000, max: 10000}
roles:
  analyst: {metrics: [revenue, order_count], dimensions: [region, order_date], usage: [region]}
  admin: {metrics: "*", dimensions: "*", usage: "*"}
rls:
  - {driver: duckdb, table: sales.orders, predicate_template: "region IN (:subject.programs)", subject_attribute: programs}
# FILL IN: exact physical masks/bindings for joined customer fixture and matching
# model policy pairs; no engine selector and no static secrets (AC3–AC6).
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_loader.py` (CREATE)

```python
"""Regression contract: Clean-room model loader, graph scoping and fixtures (M4b)."""
from pathlib import Path
import pytest


def test_own_and_ossie_lowering(tmp_path: Path) -> None:
    """Verify own and ossie lowering."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_related_model_digest_and_manifest(tmp_path: Path) -> None:
    """Verify related model digest and manifest."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_reload_atomicity_and_bad_policy(tmp_path: Path) -> None:
    """Verify reload atomicity and bad policy."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/_models.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_loader.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Replace the old loader/spike task entirely: load own YAML and Ossie into SemanticModel; no sidemantic adapter, engine dispatch or compatibility shim.
- [ ] Implement PhysicalSchema, LoadedModel.model/related_models/policy/members/schema/model_digest/policy_digest/compiler_version and SemanticModelLoader load/reload_if_changed.
- [ ] Resolve the complete directory graph before policy binding; derive reachable physical schema, semantic-to-physical provenance and manifest. Include related-model definitions in root digest so dependent caches cannot remain current after changes.
- [ ] Create deterministic orders/customers own-format fixtures and shared tests/_models.py helpers. Derive Ossie lowering from its validated public schema and reject unsupported constructs rather than guessing.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_loader.py -q`

## Test Specification

- `test_own_and_ossie_lowering`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_related_model_digest_and_manifest`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_reload_atomicity_and_bad_policy`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4467` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: gpt-5.6-terra (codex), 1 attempt, 283s.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
