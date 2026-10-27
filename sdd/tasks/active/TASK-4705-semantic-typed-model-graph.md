# TASK-4705: Frozen semantic graph and structural validation (M4a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M4; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Create frozen Dimension, Metric, Relationship and SemanticModel using the rev 0.4 field contract: physical columns/types, primary_key, aggregate column, derived sql, filters, paired join keys and join_type.
- Enforce aggregate input rules, dimension-only measure filters, derived closed arithmetic grammar and deterministic dependency traversal. Reject unknown fields, unresolved references, derived cycles and incompatible join keys.
- Provide graph validation helpers over dict[str, SemanticModel] for cross-model keys and derived references; loader calls these after loading all definitions. Freeze/defensively copy nested values, with stable canonical digest.
- One-to-many from_columns must equal the one-side primary key; reject empty/unequal key tuples, unknown models, self-joins and ambiguous paths. No warehouse introspection.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/model.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_model_graph.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticPolicyError
from .models import FilterGroup, Grain
from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from typing import Literal
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: FilterGroup/Grain from models.py and SemanticPolicyError from errors.py

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/model.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_model_graph.py",
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

### `packages/ai-parrot-semantic/src/parrot/semantic/model.py` (CREATE)

```python
"""Frozen, clean-room semantic graph built from public format definitions."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict
from .models import FilterGroup, Grain
from .errors import SemanticPolicyError

class Dimension(BaseModel, frozen=True):
    """Named physical dimension with optional time grain."""
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: Literal["categorical", "numeric", "time"]
    column: str
    grain: Grain | None = None

class Metric(BaseModel, frozen=True):
    """An aggregate input or a closed derived-metric expression."""
    model_config = ConfigDict(extra="forbid")
    name: str
    agg: Literal["sum", "count", "count_distinct", "avg", "min", "max"] | None = None
    column: str | None = None
    sql: str | None = None
    filter: FilterGroup | None = None

class Relationship(BaseModel, frozen=True):
    """Declared paired keys from one-side primary key to many-side foreign key."""
    model_config = ConfigDict(extra="forbid")
    from_model: str
    to_model: str
    cardinality: Literal["one_to_many"]
    from_columns: tuple[str, ...]
    to_columns: tuple[str, ...]
    join_type: Literal["inner", "left"] = "left"

class SemanticModel(BaseModel, frozen=True):
    """Physical schema and semantic members, with a canonical digest."""
    model_config = ConfigDict(extra="forbid")
    name: str
    table: str
    columns: dict[str, str]
    primary_key: tuple[str, ...]
    dimensions: tuple[Dimension, ...]
    metrics: tuple[Metric, ...]
    relationships: tuple[Relationship, ...]
    def digest(self) -> str:
        """Return canonical JSON SHA-256 without mutating nested definitions."""
        # FILL IN: deterministic digest; AC24.
        ...

def validate_model_graph(models: dict[str, SemanticModel]) -> None:
    """Reject unresolved references, cycles, incompatible keys and ambiguous joins."""
    # FILL IN: validators and closed derived grammar per rev 0.4 M4.
    # Structural validation never opens a database or imports a third-party engine.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_model_graph.py` (CREATE)

```python
"""Regression contract: Frozen semantic graph and structural validation (M4a)."""
from pathlib import Path
import pytest


def test_aggregate_inputs_and_derived_cycles(tmp_path: Path) -> None:
    """Verify aggregate inputs and derived cycles."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_composite_join_keys_and_physical_types(tmp_path: Path) -> None:
    """Verify composite join keys and physical types."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_nested_snapshot_and_deterministic_digest(tmp_path: Path) -> None:
    """Verify nested snapshot and deterministic digest."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/model.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_model_graph.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Create frozen Dimension, Metric, Relationship and SemanticModel using the rev 0.4 field contract: physical columns/types, primary_key, aggregate column, derived sql, filters, paired join keys and join_type.
- [ ] Enforce aggregate input rules, dimension-only measure filters, derived closed arithmetic grammar and deterministic dependency traversal. Reject unknown fields, unresolved references, derived cycles and incompatible join keys.
- [ ] Provide graph validation helpers over dict[str, SemanticModel] for cross-model keys and derived references; loader calls these after loading all definitions. Freeze/defensively copy nested values, with stable canonical digest.
- [ ] One-to-many from_columns must equal the one-side primary key; reject empty/unequal key tuples, unknown models, self-joins and ambiguous paths. No warehouse introspection.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_model_graph.py -q`

## Test Specification

- `test_aggregate_inputs_and_derived_cycles`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_composite_join_keys_and_physical_types`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_nested_snapshot_and_deterministic_digest`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4705` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
