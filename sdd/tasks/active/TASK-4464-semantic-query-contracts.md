# TASK-4464: Query/result contracts and trusted identity model (M2)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4463
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M2; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement all §2 query/result contracts and SemanticError hierarchy; no engine selector. Saved query excludes explicit members/filters/order, otherwise at least one metric/dimension/time dimension is required. Preserve valid dimensions-only lookups.
- Validate positive limits, offset ordering, grains, filter arity and mixed WHERE/HAVING groups; validate_against resolves kinds. Canonical JSON uses sorted keys and deterministic values.
- Add SemanticRequestIdentity in context.py: trusted PermissionContext snapshot, channel http/agent/mcp-local, nonempty agent_id/session_id. Do not add fields to core PermissionContext. Runtime binding helpers belong to the context-binding task.
- GovernedQuery carries exact members and qualified physical_columns, in addition to tables. CompiledQuery never carries governed subject data.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/models.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/context.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_models.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from __future__ import annotations
from parrot.auth import PermissionContext
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any
from typing import Literal
from typing import Literal, Any
import json
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

`import json` is a standard-library dependency used by canonical_json.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext():
```

```python
# packages/ai-parrot/src/parrot/auth/permission.py:21
class UserSession():
```

### Dependency Contracts and Parallelism Evidence

- TASK-4463: consumes packages/ai-parrot-semantic/pyproject.toml, packages/ai-parrot-semantic/src/parrot/semantic/__init__.py (MIT satellite packaging, workspace and CI (M1))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/errors.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/context.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#UserSession"
  ]
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

### `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` (CREATE)

```python
"""Semantic-layer exception hierarchy (spec §3 Module 2)."""
from __future__ import annotations

from typing import Any


class SemanticError(Exception):
    """Base for all semantic-layer errors.

    Args:
        code: Stable machine-readable error code (e.g. ``"no_credentials"``).
        message: Human-readable message; NEVER contains SQL or subject values.
        details: Extra structured context (suggestions, audit_id, ...).
    """

    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.details: dict[str, Any] = details or {}


class SemanticValidationError(SemanticError):
    """Malformed or unsatisfiable SemanticQuery (unknown member, mixed filter group, missing grain, fan-out)."""


class SemanticPolicyError(SemanticError):
    """Invalid model/policy definition (unknown member, sidemantic `security:` block, bad RLS binding)."""


class SemanticAccessError(SemanticError):
    """Denied: no PermissionContext, evaluator unavailable, PBAC denial, member not granted, usage right, lineage."""


class SemanticExecutionError(SemanticError):
    """Database execution failed; ``details['audit_id']`` set; SQL never in the message."""


class SemanticResultError(SemanticError):
    """Result handle unknown, foreign, expired or stale (context/policy changed)."""
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/models.py` (CREATE)

```python
"""Semantic query and result contracts."""
from __future__ import annotations

from typing import Literal, Any
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator

Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]
FilterOp = Literal["equals", "not_equals", "in", "not_in", "contains", "gt", "gte", "lt", "lte",
                   "between", "is_set", "not_set", "in_date_range", "before_date", "after_date"]

class TimeDimension(BaseModel):
    name: str
    grain: Grain | None = None          # required when the dimension is a time dimension
    date_range: tuple[str, str] | None = None   # ISO-8601 inclusive bounds

class FilterLeaf(BaseModel):
    member: str                         # metric or dimension name; kind resolved against the model
    op: FilterOp
    values: list[str | int | float | bool] = Field(default_factory=list)

class FilterGroup(BaseModel):
    op: Literal["and", "or"]
    items: list["FilterLeaf | FilterGroup"]
    # validator: a group never mixes metric (HAVING) and dimension (WHERE) leaves

class OrderBy(BaseModel):
    member: str
    grain: Grain | None = None
    desc: bool = False

class SemanticQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")   # credential-like or unknown fields are rejected (never carried by a query)
    model: str
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_dimensions: list[TimeDimension] = Field(default_factory=list)
    filters: FilterGroup | None = None
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = None            # None → policy default; clamped to policy max
    offset: int = 0                     # requires order_by
    timezone: str | None = None
    saved_query: str | None = None      # exclusive with explicit members; expanded before compile
    def canonical_json(self) -> str:
        """Return sorted-key, whitespace-free JSON for versioned cache keys."""
        # FILL IN: use json.dumps(model_dump(mode="json"), sort_keys=True).
        ...
    def validate_against(self, member_kinds: dict[str, str], time_dimensions: set[str]) -> None:
        """Reject unknown members, mixed filter kinds and missing time grains."""
        # FILL IN: semantic validation after structural Pydantic validation.
        ...

class CompiledQuery(BaseModel, frozen=True):
    """Pre-governance compiler output. MUST contain no subject-derived predicates or values."""
    sql: str
    dialect: str
    # (rev 0.3) no `engine` field — the native compiler is the sole engine; `compiler_version` below
    # replaces the old "engine+version" cache-key component (invalidates on compiler codegen changes).
    members: tuple[str, ...]            # metrics + dimensions referenced
    tables: tuple[str, ...]             # "schema.table" physical tables referenced
    cache_key: str                      # (model digest, policy digest, canonical query, dialect, compiler_version, connection id)

class GovernedQuery(BaseModel, frozen=True):
    sql: str
    dialect: str
    driver: str
    tables: tuple[str, ...]
    rls_applied: tuple[str, ...]        # rule descriptions applied (never values)
    masked_columns: tuple[str, ...]
    limit: int
    subject_digest: str
    members: tuple[str, ...]            # exact semantic provenance including dependencies
    physical_columns: tuple[str, ...]   # resolved qualified lineage; never inferred from output aliases

```

```python
class SemanticQueryResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    compiled_sql: str                   # governed SQL as executed
    audit_id: str
    result_id: str | None = None        # present only when the ResultHandleStore is enabled

class Limits(BaseModel):
    """Default/max row caps with positive ordered values."""
    default: int = 1000
    max: int = 10000
    # FILL IN: require 1 <= default <= max.

class ModelMember(BaseModel):
    """Catalog member metadata; policy determines access, not sensitive alone."""
    name: str
    kind: Literal["metric", "dimension", "time_dimension", "entity"]
    description: str = ""
    grain: Grain | None = None
    sensitive: bool = False
# FILL IN: saved-query exclusivity, dimensions-only queries and validation errors.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/context.py` (CREATE)

```python
"""Trusted semantic identity; runtime binding is added separately."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from parrot.auth import PermissionContext

class SemanticRequestIdentity(BaseModel, frozen=True):
    """Host-authenticated identity for retained results."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    ctx: PermissionContext
    channel: Literal["http", "agent", "mcp-local"]
    agent_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    # FILL IN: defensively copy trusted context/metadata, reject blank identifiers;
    # never infer identity from tool arguments or PermissionContext.request_id.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_models.py` (CREATE)

```python
"""Regression contract: Query/result contracts and trusted identity model (M2)."""
from pathlib import Path
import pytest


def test_dimensions_only_and_saved_query_exclusivity(tmp_path: Path) -> None:
    """Verify dimensions only and saved query exclusivity."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_invalid_grains_limits_and_mixed_filters(tmp_path: Path) -> None:
    """Verify invalid grains limits and mixed filters."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_identity_snapshot_and_provenance_fields(tmp_path: Path) -> None:
    """Verify identity snapshot and provenance fields."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/models.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/context.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_models.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement all §2 query/result contracts and SemanticError hierarchy; no engine selector. Saved query excludes explicit members/filters/order, otherwise at least one metric/dimension/time dimension is required. Preserve valid dimensions-only lookups.
- [ ] Validate positive limits, offset ordering, grains, filter arity and mixed WHERE/HAVING groups; validate_against resolves kinds. Canonical JSON uses sorted keys and deterministic values.
- [ ] Add SemanticRequestIdentity in context.py: trusted PermissionContext snapshot, channel http/agent/mcp-local, nonempty agent_id/session_id. Do not add fields to core PermissionContext. Runtime binding helpers belong to the context-binding task.
- [ ] GovernedQuery carries exact members and qualified physical_columns, in addition to tables. CompiledQuery never carries governed subject data.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_models.py -q`

## Test Specification

- `test_dimensions_only_and_saved_query_exclusivity`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_invalid_grains_limits_and_mixed_filters`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_identity_snapshot_and_provenance_fields`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4464` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
