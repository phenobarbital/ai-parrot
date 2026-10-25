# TASK-4470: Request-local RLS below aggregation (M6b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4469
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M6; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement RlsPushdown using registry lookup/render and typed sqlglot literals derived from the qualified schema; each physical base scan is wrapped below aggregation with aliases preserved.
- Keep schema binding request-local; pipeline supplies its qualified schema to the per-call pass without mutating shared registry/AST state. Preserve the public apply(tree, ctx, driver) contract.
- Reject unplaceable sources, table functions, lateral/unnest and recursive CTEs; missing subject values render deny predicates. Never wrap the aggregate as a fallback.
- Return applied descriptions and trusted node ids while holding referenced nodes alive. Test aggregates for two subjects, nested queries, joins and adversarial literals.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_rls_pushdown.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from ..errors import SemanticAccessError
from ..loader import PhysicalSchema
from __future__ import annotations
from parrot.auth import PermissionContext, RlsRegistry, RlsPredicate
from pathlib import Path
from sqlglot import exp
import logging
import pytest
import sqlglot
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/rls_registry.py:87
class RlsRegistry():
    # line 107
    def __init__(self) -> None:
    # line 112
    def register(self, rule: RlsRule) -> None:
    # line 125
    def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]:
    # line 150
    def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate:
```

```python
# packages/ai-parrot/src/parrot/auth/rls_registry.py:70
class RlsPredicate(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext():
```

### Dependency Contracts and Parallelism Evidence

- TASK-4469: consumes packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py, packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py (Fail-closed PBAC and full column lineage (M6a))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_rls_pushdown.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsRegistry",
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsPredicate",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext"
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

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py` (CREATE)

```python
"""RLS push-down: filtered base scans below aggregation, typed literals, fail closed."""
from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

from parrot.auth import PermissionContext, RlsRegistry, RlsPredicate

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema


class RlsPushdown:
    def __init__(self, registry: RlsRegistry) -> None:
        self.registry = registry
        self.logger = logging.getLogger(__name__)

    def apply(self, tree: exp.Expression, ctx: PermissionContext, driver: str) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
        """Wrap every RLS-governed base scan as a filtered subquery BELOW aggregation.

        Returns:
            (tree, applied rule descriptions — never values, ids of injected trusted nodes).
        Raises:
            SemanticAccessError: render failure or a construct the rewrite cannot place deterministically.
        """
        schema = self._schema  # set only on a fresh per-request pass by _for_schema
        # FILL IN: reject exp.Lateral / exp.Unnest / table-valued functions / recursive CTEs -> "rls_unplaceable";
        #   tables = {f"{t.db}.{t.name}" for t in physical exp.Table nodes}; rules = self.registry.lookup(driver, tables)
        #   for each table node with rules: pred = self.registry.render(rule, ctx) (exception -> "rls_render_failed");
        #   cond = self._predicate_expr(pred, schema, table); replace node with
        #   exp.Subquery(SELECT * FROM <same table> WHERE cond) aliased with the original alias (or table name);
        #   collect id() of every injected node
        raise NotImplementedError

    def _predicate_expr(self, pred: RlsPredicate, schema: PhysicalSchema, table: str) -> exp.Expression:
        """Parse pred.sql_predicate and replace `:pN` placeholders with typed exp.Literal from bound_params."""
        # FILL IN: literal type from schema.tables[table][column] (number vs string); lists -> exp.Tuple of literals
        raise NotImplementedError

    def _for_schema(self, schema: PhysicalSchema) -> RlsPushdown:
        """Return a fresh pass sharing only the read-only registry, bound to schema."""
        # FILL IN: no mutation of shared instances; governance creates one per call.
        ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_rls_pushdown.py` (CREATE)

```python
"""Regression contract: Request-local RLS below aggregation (M6b)."""
from pathlib import Path
import pytest


def test_rls_below_sum_for_two_subjects(tmp_path: Path) -> None:
    """Verify rls below sum for two subjects."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_typed_literals_and_render_failure(tmp_path: Path) -> None:
    """Verify typed literals and render failure."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_unsupported_sources_and_ast_isolation(tmp_path: Path) -> None:
    """Verify unsupported sources and ast isolation."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_rls_pushdown.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement RlsPushdown using registry lookup/render and typed sqlglot literals derived from the qualified schema; each physical base scan is wrapped below aggregation with aliases preserved.
- [ ] Keep schema binding request-local; pipeline supplies its qualified schema to the per-call pass without mutating shared registry/AST state. Preserve the public apply(tree, ctx, driver) contract.
- [ ] Reject unplaceable sources, table functions, lateral/unnest and recursive CTEs; missing subject values render deny predicates. Never wrap the aggregate as a fallback.
- [ ] Return applied descriptions and trusted node ids while holding referenced nodes alive. Test aggregates for two subjects, nested queries, joins and adversarial literals.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_rls_pushdown.py -q`

## Test Specification

- `test_rls_below_sum_for_two_subjects`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_typed_literals_and_render_failure`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_unsupported_sources_and_ast_isolation`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4470` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: gpt-5.6-sol (codex), 1 attempt, 235s.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
