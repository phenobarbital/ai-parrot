# TASK-4471: Projection masks and positive SQL guard (M6c)

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

- Implement null/hash/partial projection masking using resolved physical lineage; return masked names and retained trusted-node identities.
- Implement default/additive function allowlist and PositiveGuard.check_and_limit(tree). Require one SELECT root, known physical tables/columns, allowlisted functions and policy limit cap; no DDL/DML/Command or extra statements.
- Handle compiler-owned CASE/filter expressions and trusted masking functions explicitly without granting arbitrary caller functions. Resolve CTE references to physical scans.
- Add the adversarial matrix across postgres/bigquery/duckdb: star, aliases, case/quoted identifiers, CTEs, subqueries, windows and sensitive derived projections.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_masking.py` | CREATE | Focused regression evidence |
| `packages/ai-parrot-semantic/tests/test_positive_guard.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from ..errors import SemanticValidationError
from ..loader import PhysicalSchema
from ..models import Limits
from ..policy import ModelPolicy
from .lineage import ColumnUse
from __future__ import annotations
from pathlib import Path
from sqlglot import exp
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_masking.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_positive_guard.py",
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

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py` (CREATE)

```python
"""Rewrite projected masked columns per MaskRule.strategy (null / md5-hash / partial)."""
from __future__ import annotations

from sqlglot import exp

from ..policy import ModelPolicy
from .lineage import ColumnUse


def apply_masks(tree: exp.Expression, uses: list[ColumnUse], policy: ModelPolicy, roles: frozenset[str],
                dialect: str) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
    """Returns (tree, masked column names "table.column", ids of injected trusted nodes)."""
    # FILL IN: for each projection use with policy.mask_for(roles, f"{u.table}.{u.column}") -> rule:
    #   replace the projected expression with the strategy expression aliased to the original output name;
    #   record id() of every injected node — bounded by AC6
    raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py` (CREATE)

```python
"""Positive SQL guard: single SELECT, allowlisted tables/columns/functions, forced LIMIT."""
from __future__ import annotations

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import PhysicalSchema
from ..models import Limits
from ..policy import ModelPolicy

# §8 Q4 — COUNT DISTINCT is exp.Count(distinct); operators are nodes, always allowed
DEFAULT_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {"SUM", "COUNT", "AVG", "MIN", "MAX", "DATE_TRUNC", "EXTRACT", "COALESCE", "CAST", "LOWER", "UPPER"})


def effective_allowed_functions(policy: ModelPolicy, extra: frozenset[str] | None) -> frozenset[str]:
    """DEFAULT ∪ (extra or ∅) ∪ policy.allowed_functions — additive only (§8 Q4)."""
    return DEFAULT_ALLOWED_FUNCTIONS | (extra or frozenset()) | {f.upper() for f in policy.allowed_functions}


class PositiveGuard:
    def __init__(self, schema: PhysicalSchema, allowed_functions: frozenset[str], limits: Limits) -> None:
        self.schema = schema
        self.allowed_functions = allowed_functions
        self.limits = limits

    def check_and_limit(self, tree: exp.Expression) -> exp.Expression:
        """Exactly one exp.Select root (CTEs allowed); every table/column in schema; functions allowlisted;
        no exp.Command/DDL/DML; inject (policy default) or clamp (policy max) LIMIT.

        Raises:
            SemanticValidationError: codes "not_select", "unknown_table", "unknown_column",
                "function_not_allowed", "command_forbidden".
        """
        # FILL IN: root must be exp.Select (exp.Union etc. -> not_select); any exp.Command/Insert/Update/Delete/
        #   Create/Drop/Alter anywhere -> command_forbidden; physical tables (excluding CTE names) in
        #   self.schema.tables; qualified columns in that table's column map; functions by sql_name in the allowset;
        #   limit = min(existing LIMIT or limits.default, limits.max) -> tree.limit(limit, copy=False)
        raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_masking.py` (CREATE)

```python
"""Regression contract: Projection masks and positive SQL guard (M6c)."""
from pathlib import Path
import pytest


def test_mask_strategies_and_derived_projection(tmp_path: Path) -> None:
    """Verify mask strategies and derived projection."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_allowlist_and_limits(tmp_path: Path) -> None:
    """Verify allowlist and limits."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_three_dialect_adversarial_matrix(tmp_path: Path) -> None:
    """Verify three dialect adversarial matrix."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_positive_guard.py` (CREATE)

```python
"""Regression contract: Projection masks and positive SQL guard (M6c)."""
from pathlib import Path
import pytest


def test_mask_strategies_and_derived_projection(tmp_path: Path) -> None:
    """Verify mask strategies and derived projection."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_allowlist_and_limits(tmp_path: Path) -> None:
    """Verify allowlist and limits."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_three_dialect_adversarial_matrix(tmp_path: Path) -> None:
    """Verify three dialect adversarial matrix."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_masking.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_positive_guard.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement null/hash/partial projection masking using resolved physical lineage; return masked names and retained trusted-node identities.
- [ ] Implement default/additive function allowlist and PositiveGuard.check_and_limit(tree). Require one SELECT root, known physical tables/columns, allowlisted functions and policy limit cap; no DDL/DML/Command or extra statements.
- [ ] Handle compiler-owned CASE/filter expressions and trusted masking functions explicitly without granting arbitrary caller functions. Resolve CTE references to physical scans.
- [ ] Add the adversarial matrix across postgres/bigquery/duckdb: star, aliases, case/quoted identifiers, CTEs, subqueries, windows and sensitive derived projections.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_masking.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_positive_guard.py -q`

## Test Specification

- `test_mask_strategies_and_derived_projection`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_allowlist_and_limits`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_three_dialect_adversarial_matrix`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4471` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
