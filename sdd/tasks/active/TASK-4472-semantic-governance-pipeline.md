# TASK-4472: Governance pipeline orchestration (M6d)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4469, TASK-4470, TASK-4471
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (pipeline) + §2 item 3: the fixed-order pass on a parsed CLONE, used for compiled SQL, saved queries, dimension-value lookups and raw SQL alike; no partial SQL ever leaves it.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py`: `GovernancePipeline(pbac, rls, allowed_functions)` + `govern(...)` → `GovernedQuery`, plus `subject_digest(ctx)`.
- Write `test_pipeline.py` (order, clone isolation, every failure denies, cache-hit re-governance).

**NOT in scope**: compile/cache (TASK-4467/4475); audit (TASK-4474).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py` | CREATE | ordered governance pass |
| `packages/ai-parrot-semantic/tests/test_pipeline.py` | CREATE | pipeline tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.security import QueryValidator                                 # verified: security/__init__.py:14 (import site), query_validator.py:29
from parrot.auth import PermissionContext                                  # verified: auth/__init__.py lazy map
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect   # verified: dialects.py:41
from parrot.semantic.governance.pbac import PbacGate, resources_from_ast   # TASK-4469
from parrot.semantic.governance.lineage import resolve_column_uses, enforce_usage_rights   # TASK-4469
from parrot.semantic.governance.rls import RlsPushdown                     # TASK-4470
from parrot.semantic.governance.masking import apply_masks                 # TASK-4471
from parrot.semantic.governance.guard import PositiveGuard, effective_allowed_functions   # TASK-4471
from parrot.semantic.loader import LoadedModel                             # TASK-4467
from parrot.semantic.models import GovernedQuery                           # TASK-4464
from parrot.semantic.errors import SemanticAccessError, SemanticValidationError   # TASK-4464
import sqlglot; from sqlglot.optimizer.qualify import qualify
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/query_validator.py
class QueryValidator:   # line 29
    @classmethod
    def validate_sql_ast(cls, query: str, dialect: Optional[str] = None, read_only: bool = True,
                         require_pk_in_where: bool = False, primary_keys: Optional[List[str]] = None) -> Dict[str, Any]   # line 165
# packages/ai-parrot/src/parrot/auth/permission.py — UserSession.metadata is NOT part of its hash (line 49); hash it explicitly
```

### Trusted nodes (added 2026-10-19, TASK-4471 review fix)
- `PositiveGuard.check_and_limit(tree, *, requested_limit=None, trusted_nodes: set[int] | None = None)`.
  Pass the UNION of the `set[int]` returned by `RlsPushdown.apply(...)` (3rd element) and `apply_masks(...)`
  (3rd element) as `trusted_nodes=`; otherwise every RLS-filtered or masked query is denied
  (`unknown_column *` / `function_not_allowed MD5`).
- `RlsPushdown._literal` now raises `ValueError` for non-numeric values on numeric columns, and `apply` denies
  (`rls_unplaceable`) when a subject attribute resolves to no values.

### Column-key convention (added 2026-10-19, TASK-4469 review fix c42dcbcb0)
- `ModelPolicy.usage_allowed(roles, column)` and `ModelPolicy.mask_for(roles, column)` take the **physical**
  `<schema>.<table>.<column>` name (as produced by `governance/lineage.py` `ColumnUse`: `f"{use.table}.{use.column}"`).
  Mask keys (`<table>.<member>`) match as a dotted suffix; usage grants (bare member names) match the last segment.
  Do NOT pass bare names or re-implement key matching at the call site.

### Does NOT Exist
- ~~`QueryValidator.validate_sql_ast` raising~~ — it RETURNS a dict; inspect its result keys (read query_validator.py:165-) and map a failure to `SemanticValidationError('unsafe_sql')`.
- ~~Caching a `GovernedQuery`~~ — never; only pre-governance `CompiledQuery` is cacheable (AC8).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_pipeline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/query_validator.py#QueryValidator"
  ]
}
```

---

## Implementation Notes

- Order is FIXED: validate_sql_ast(read_only=True) → parse clone → qualify(schema) → resources_from_ast → PbacGate.authorize(manifest=...) → lineage usage rights → RLS push-down → masking → PositiveGuard → render.
- `subject_digest(ctx)` = SHA-256 over (user_id, tenant_id, sorted roles, sorted session.metadata items) — the toolkit (TASK-4477) reuses it for audit entries and result-handle claims.

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
1. Write `govern()` in the fixed order — *why*: spec §3 M6.
2. Write `subject_digest` — *why*: audit + handles need one definition.
3. Write tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py` (CREATE)
```python
"""Fixed-order governance pass over a parsed clone (spec §2 step 3)."""
from __future__ import annotations

import hashlib
import json
import logging

import sqlglot
from sqlglot.optimizer.qualify import qualify

from parrot.auth import PermissionContext
from parrot.security import QueryValidator
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..models import GovernedQuery
from .guard import PositiveGuard, effective_allowed_functions
from .lineage import enforce_usage_rights, resolve_column_uses
from .masking import apply_masks
from .pbac import PbacGate, resources_from_ast
from .rls import RlsPushdown


def subject_digest(ctx: PermissionContext | None) -> str:
    """SHA-256 over (user_id, tenant_id, sorted roles, sorted metadata items); "anonymous" digest for None."""
    if ctx is None:
        return hashlib.sha256(b"anonymous").hexdigest()
    s = ctx.session
    raw = json.dumps([s.user_id, s.tenant_id, sorted(s.roles), sorted((k, repr(v)) for k, v in s.metadata.items())])
    return hashlib.sha256(raw.encode()).hexdigest()


class GovernancePipeline:
    def __init__(self, *, pbac: PbacGate, rls: RlsPushdown, allowed_functions: frozenset[str]) -> None:
        self.pbac = pbac
        self.rls = rls
        self.allowed_functions = allowed_functions
        self.logger = logging.getLogger(__name__)

    async def govern(self, sql: str, *, model: LoadedModel, ctx: PermissionContext | None,
                     roles: frozenset[str], requested_limit: int | None = None) -> GovernedQuery:
        """Full pass on a parsed clone; any failure raises — no partial SQL leaves the pipeline."""
        driver = model.schema.driver
        dialect = driver_to_dialect(driver) or driver
        # FILL IN (order fixed):
        #  1. QueryValidator.validate_sql_ast(sql, dialect, read_only=True) -> failure => SemanticValidationError("unsafe_sql")
        #  2. tree = qualify(sqlglot.parse_one(sql, dialect=dialect), schema=model.schema.sqlglot_schema(), dialect=dialect)
        #  3. manifest = await self.pbac.authorize_manifest(ctx, model);
        #     await self.pbac.authorize(ctx, resources_from_ast(tree, driver), governed=model.policy.governed, manifest=manifest)
        #  4. governed models: enforce_usage_rights(resolve_column_uses(tree, model.schema), model.policy, roles, trusted_nodes=set())
        #  5. tree, rls_applied, t1 = self.rls.apply(tree, ctx, driver, schema=model.schema)   (skip when not governed)
        #  6. tree, masked, t2 = apply_masks(tree, uses, model.policy, roles, dialect)
        #  7. PositiveGuard(model.schema, effective_allowed_functions(model.policy, self.allowed_functions),
        #                   model.policy.limits).check_and_limit(tree, requested_limit=requested_limit)
        #  8. return GovernedQuery(sql=tree.sql(dialect=dialect), dialect=, driver=, tables=, rls_applied=, masked_columns=,
        #                          limit=, subject_digest=subject_digest(ctx))
        raise NotImplementedError
```
**Why**: the ordering comment IS the contract (spec §3 M6 responsibility); `requested_limit` threads `SemanticQuery.limit` into the guard.

### FILL IN checklist
- [ ] `govern` steps 1-8 — bounded by the fixed order and AC3-AC7.
- [ ] QueryValidator result-key mapping (read the method body first).

---

## Acceptance Criteria

- [ ] `test_pipeline.py` passes: original SQL string/AST unchanged after govern; each stage's failure raises; ungoverned models skip PBAC/RLS/lineage but still pass the positive guard.
- [ ] Governing the same compiled SQL for two subjects yields different RLS literals and identical input objects (AC8 precondition).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_pipeline.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_pipeline.py
import pytest
from ._models import models_dir, loaded_models  # noqa: F401
from parrot.semantic.governance.pipeline import GovernancePipeline, subject_digest


def test_subject_digest_includes_metadata(pctx_factory):
    a = pctx_factory(programs=["n"]); b = pctx_factory(programs=["s"])
    assert subject_digest(a) != subject_digest(b)

# FILL IN: test_govern_order_and_clone, test_govern_denies_without_ctx, test_ungoverned_still_guarded
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4472 — Governance pipeline orchestration (M6d)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4472 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
