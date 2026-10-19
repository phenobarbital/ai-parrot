# TASK-4469: Governance: PBAC gate and column-usage lineage (M6a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4467
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (pbac + lineage) and §2 item 3: two-phase PBAC (manifest before compile, AST tables ⊆ manifest after) that never lets `ctx=None` reach the fail-open guard (AC3, AC4, AC19), and column-usage lineage that distinguishes projection from usage rights and fails closed on unresolved lineage (AC6).

---

## Scope

- Create `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py` (docstring only).
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`: `PbacGate` (`available`, `authorize_manifest`, `authorize`), `resources_from_ast`.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/governance/lineage.py`: `ColumnUse`, `resolve_column_uses`, `enforce_usage_rights`.
- Write `test_pbac.py` and `test_lineage.py`.

**NOT in scope**: RLS push-down (TASK-4470), masking/guard (TASK-4471), pipeline ordering (TASK-4472).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py` | CREATE | subpackage marker |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py` | CREATE | PbacGate |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/lineage.py` | CREATE | column lineage + usage rights |
| `packages/ai-parrot-semantic/tests/test_pbac.py` | CREATE | fail-closed PBAC tests |
| `packages/ai-parrot-semantic/tests/test_lineage.py` | CREATE | masked-inference matrix |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.auth import PermissionContext, DataPlanePolicyGuard              # verified: auth/__init__.py lazy map (33, 45)
from parrot.auth.exceptions import AuthorizationRequired                    # verified: packages/ai-parrot/src/parrot/auth/exceptions.py:12
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources  # verified: resolver.py:47
from parrot.semantic.loader import LoadedModel, PhysicalSchema              # TASK-4467
from parrot.semantic.policy import ModelPolicy                              # TASK-4465
from parrot.semantic.errors import SemanticAccessError                      # TASK-4464
from sqlglot import exp; from sqlglot.optimizer.qualify import qualify; from sqlglot.optimizer.scope import build_scope   # sqlglot 30.23.0
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/dataplane_guard.py
class DataPlanePolicyGuard:     # line 45 — ctx None → FAIL-OPEN (52, 193-200); ImportError navigator-auth → fail-open; evaluator error → fail-closed
    async def authorize_source(self, ctx: Optional[PermissionContext], resources: "PhysicalResources") -> None   # line 193 — raises AuthorizationRequired
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py
class PhysicalResources(BaseModel):   # line 47 — driver: Optional[str]; tables: set[str] ("driver:schema.table"); source_type; source_id
```

### Does NOT Exist
- ~~`DataPlanePolicyGuard` failing closed on `ctx=None`~~ — it fails OPEN; `PbacGate` must deny first.
- ~~`resolve_physical_resources(sql, driver)`~~ — takes a DataSource (resolver.py:120); build `PhysicalResources` directly.
- ~~`DataPlanePolicyGuard.is_available()`~~ — no such method; probe `guard is not None` and `importlib.util.find_spec("navigator_auth")` at construction.

---

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
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py#PhysicalResources"
  ]
}
```

---

## Implementation Notes

- Trusted nodes are tracked by `id(node)` within one pipeline pass — never by caller labels (spec §7).
- Lineage must resolve through aliases, CTEs, subqueries, windows and derived expressions; `SELECT *` is expanded by `qualify` first.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write `pbac.py` — *why*: AC3/AC4/AC19 fail-closed rules.
2. Write `lineage.py` using `qualify` + `build_scope` — *why*: AC6 usage rights.
3. Write the tests incl. the masked-inference matrix (WHERE/HAVING/JOIN/GROUP/ORDER/window/alias/CTE/derived).

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
        self.available = guard is not None and importlib.util.find_spec("navigator_auth") is not None
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
**Why**: spec §3 M6 skeleton; the `ColumnUse` context literal set is fixed.

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py` (CREATE)
```python
"""Governance pipeline: PBAC, lineage, RLS push-down, masking, positive guard (spec §3 Module 6)."""
```

### FILL IN checklist
- [ ] `PbacGate.authorize` error codes — bounded by AC3/AC4/AC19.
- [ ] CTE exclusion in `resources_from_ast`.
- [ ] `resolve_column_uses` — bounded by AC6 (fail closed).
- [ ] `enforce_usage_rights` + trusted-node handling (by `id()` only).

---

## Acceptance Criteria

- [ ] `test_pbac_gate_fail_closed`, `test_pbac_denied_table_blocks_sql`, `test_lineage_masked_column_inference` pass.
- [ ] `authorize_source` is never called with `ctx=None` (assert on the guard double) (AC3).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_pbac.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_lineage.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_pbac.py
import pytest
from parrot.semantic.governance.pbac import PbacGate
from parrot.semantic.errors import SemanticAccessError
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


async def test_pbac_gate_fail_closed(allow_all_guard, pctx_factory):
    res = PhysicalResources(driver="duckdb", tables={"duckdb:sales.orders"})
    with pytest.raises(SemanticAccessError):
        await PbacGate(allow_all_guard).authorize(None, res, governed=True)
    allow_all_guard.authorize_source.assert_not_called()
    with pytest.raises(SemanticAccessError):
        await PbacGate(None).authorize(pctx_factory(), res, governed=True)
    await PbacGate(None).authorize(None, res, governed=False)   # ungoverned passes
    # FILL IN: navigator_auth missing (monkeypatch importlib.util.find_spec) -> unavailable -> deny

# FILL IN: test_pbac_denied_table_blocks_sql (deny_table_guard("dim.customers")) in test_pbac.py;
#          test_lineage_masked_column_inference matrix in test_lineage.py
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4469 — Governance: PBAC gate and column-usage lineage (M6a)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4469 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
