# TASK-4469: Fail-closed PBAC and full column lineage (M6a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4467
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M6; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement PbacGate and resources_from_ast; require context and probe exact navigator_auth.abac.policies.environment/evaluator modules, not only the root package.
- Authorize the declared manifest before compilation and require every physical table after qualification to be in that manifest. Resolve CTE aliases to base resources, not fictitious physical tables.
- Implement ColumnUse, resolve_column_uses and enforce_usage_rights through aliases/CTEs/subqueries/window/derived expressions. Deny unresolved lineage and any ungranted usage of hidden/masked columns.
- Define governance package marker. Nodes trusted by pipeline identity must have strong references for the full pass; caller labels are never trusted.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/lineage.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_pbac.py` | CREATE | Focused regression evidence |
| `packages/ai-parrot-semantic/tests/test_lineage.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from ..errors import SemanticAccessError
from ..loader import LoadedModel
from ..loader import PhysicalSchema
from ..policy import ModelPolicy
from __future__ import annotations
from parrot.auth import DataPlanePolicyGuard, PermissionContext
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources
from pathlib import Path
from pydantic import BaseModel
from sqlglot import exp
from typing import Literal
import importlib.util
import logging
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/dataplane_guard.py:45
class DataPlanePolicyGuard():
    # line 71
    def __init__(self, evaluator: 'PolicyEvaluator', rls_registry: 'RlsRegistry', sensitive_drivers: frozenset[str]=frozenset(), logger: Optional[logging.Logger]=None) -> None:
    # line 193
    async def authorize_source(self, ctx: Optional[PermissionContext], resources: 'PhysicalResources') -> None:
```

```python
# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext():
```

```python
# packages/ai-parrot/src/parrot/auth/exceptions.py:12
class AuthorizationRequired(Exception):
    # line 34
    def __init__(self, tool_name: str, message: str, auth_url: Optional[str]=None, provider: str='unknown', scopes: Optional[List[str]]=None) -> None:
```

```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py:47
class PhysicalResources(BaseModel):
```

### Dependency Contracts and Parallelism Evidence

- TASK-4467: consumes packages/ai-parrot-semantic/src/parrot/semantic/loader.py (Clean-room model loader, graph scoping and fixtures (M4b))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/lineage.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_pbac.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_lineage.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/exceptions.py#AuthorizationRequired",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py#PhysicalResources"
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

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py` (CREATE)

```python
"""Governance pipeline: PBAC, lineage, RLS push-down, masking, positive guard (spec §3 Module 6)."""
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py` (CREATE)

```python
"""Two-phase PBAC gate over DataPlanePolicyGuard — never reaches its fail-open branch."""
from __future__ import annotations

import importlib.util
import logging

from sqlglot import exp

from parrot.auth import DataPlanePolicyGuard, PermissionContext
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from ..errors import SemanticAccessError
from ..loader import LoadedModel


class PbacGate:
    def __init__(self, guard: DataPlanePolicyGuard | None) -> None:
        """Probe evaluator availability at construction (navigator-auth importable, guard not None)."""
        self.guard = guard
        self.available = False
        # FILL IN: import exact environment AND evaluator modules safely; catch
        # ImportError/ModuleNotFoundError, require configured guard/evaluator.
        self.logger = logging.getLogger(__name__)

    async def authorize_manifest(self, ctx: PermissionContext | None, model: LoadedModel) -> PhysicalResources:
        """Phase (a): authorize the model's driver + all schema-map tables BEFORE compile."""
        manifest = PhysicalResources(driver=model.schema.driver,
                                     tables={f"{model.schema.driver}:{t}" for t in model.schema.tables})
        await self.authorize(ctx, manifest, governed=model.policy.governed)
        return manifest

    async def authorize(self, ctx: PermissionContext | None, resources: PhysicalResources, *,
                        governed: bool, manifest: PhysicalResources | None = None) -> None:
        """Phase (b): deny on missing ctx/evaluator, tables outside the manifest, or a guard denial."""
        if not governed:
            return
        # FILL IN: ctx None -> SemanticAccessError("no_subject"); not self.available -> ("pbac_unavailable");
        #   manifest given and resources.tables - manifest.tables -> ("outside_manifest");
        #   await self.guard.authorize_source(ctx, resources) mapping AuthorizationRequired -> ("pbac_denied")
        raise NotImplementedError


def resources_from_ast(tree: exp.Expression, driver: str) -> PhysicalResources:
    """`tables={f"{driver}:{schema}.{table}"}` from every exp.Table after qualify."""
    tables = {f"{driver}:{t.db}.{t.name}" for t in tree.find_all(exp.Table) if t.name}
    # FILL IN: CTE names are not physical tables — exclude exp.Table nodes that reference a CTE alias
    return PhysicalResources(driver=driver, tables=tables)
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/lineage.py` (CREATE)

```python
"""Column-usage lineage: projection rights ≠ usage rights; unresolved lineage fails closed."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlglot import exp

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema
from ..policy import ModelPolicy


class ColumnUse(BaseModel):
    column: str
    table: str
    context: Literal["projection", "where", "having", "join", "group_by", "order_by", "window", "derived"]


def resolve_column_uses(tree: exp.Expression, schema: PhysicalSchema) -> list[ColumnUse]:
    """Walk aliases, CTEs, subqueries, derived expressions back to physical columns."""
    # FILL IN: tree is already qualified; use sqlglot.optimizer.scope.build_scope to follow each exp.Column
    #   through its scope sources to a physical table; context from the nearest ancestor clause
    #   (exp.Where/Having/Join/Group/Order/Window; a projection that is not a bare column -> "derived");
    #   any column not resolvable -> SemanticAccessError("unresolved_lineage")
    raise NotImplementedError


def enforce_usage_rights(uses: list[ColumnUse], policy: ModelPolicy, roles: frozenset[str], *,
                         trusted_nodes: set[int]) -> None:
    """Deny any non-projection use of a masked/hidden column without usage rights."""
    # FILL IN: for u in uses with u.context != "projection": if not policy.usage_allowed(roles, f"{u.table}.{u.column}")
    #   -> SemanticAccessError("usage_denied", details={"column": ...}); trusted_nodes are skipped by the caller
    #   (resolve_column_uses must accept them) — nodes injected by RLS/masking are trusted by identity only
    raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_pbac.py` (CREATE)

```python
"""Regression contract: Fail-closed PBAC and full column lineage (M6a)."""
from pathlib import Path
import pytest


def test_manifest_and_exact_evaluator_failure(tmp_path: Path) -> None:
    """Verify manifest and exact evaluator failure."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_cte_alias_physical_resources(tmp_path: Path) -> None:
    """Verify cte alias physical resources."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_sensitive_usage_lineage_matrix(tmp_path: Path) -> None:
    """Verify sensitive usage lineage matrix."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_lineage.py` (CREATE)

```python
"""Regression contract: Fail-closed PBAC and full column lineage (M6a)."""
from pathlib import Path
import pytest


def test_manifest_and_exact_evaluator_failure(tmp_path: Path) -> None:
    """Verify manifest and exact evaluator failure."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_cte_alias_physical_resources(tmp_path: Path) -> None:
    """Verify cte alias physical resources."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_sensitive_usage_lineage_matrix(tmp_path: Path) -> None:
    """Verify sensitive usage lineage matrix."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/lineage.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_pbac.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_lineage.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement PbacGate and resources_from_ast; require context and probe exact navigator_auth.abac.policies.environment/evaluator modules, not only the root package.
- [ ] Authorize the declared manifest before compilation and require every physical table after qualification to be in that manifest. Resolve CTE aliases to base resources, not fictitious physical tables.
- [ ] Implement ColumnUse, resolve_column_uses and enforce_usage_rights through aliases/CTEs/subqueries/window/derived expressions. Deny unresolved lineage and any ungranted usage of hidden/masked columns.
- [ ] Define governance package marker. Nodes trusted by pipeline identity must have strong references for the full pass; caller labels are never trusted.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_pbac.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_lineage.py -q`

## Test Specification

- `test_manifest_and_exact_evaluator_failure`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_cte_alias_physical_resources`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_sensitive_usage_lineage_matrix`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4469` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
