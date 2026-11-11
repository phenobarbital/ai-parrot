# TASK-5520: SemanticDataSource in ai-parrot-semantic, with identity bridge (M4)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5515
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview, 'Identity' (rev 0.3 bridge) and §3 Module 4. The source binds one model of a `SemanticLayerToolkit` and runs `query_metrics` — the existing governed path — on every fetch.

---

## Scope

- New module `dataset_source.py` with `QUERY_FIELDS`, `SemanticDataSource` and `from_models_dir`.
- Subject resolution: semantic ctx and core ctx equal → use; semantic only → use; core only and a `PermissionContext` → bridge with `bind_semantic_context(core)`; else `context_required`.
- DataFrame conversion with `attrs["semantic"]`.
- Export from `parrot.semantic`.

**NOT in scope**: DatasetManager changes; add_semantic (TASK-5521); docs (TASK-5522).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/dataset_source.py` | CREATE | the source |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | MODIFY | export |
| `packages/ai-parrot-semantic/tests/test_dataset_source.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
from parrot.auth import PermissionContext                               # verified: semantic/context.py:11
from parrot.auth.context import _pctx_var                               # verified: semantic/context.py:12
from parrot.tools.dataset_manager.sources.base import DataSource       # verified: sources/base.py:23
from .context import bind_semantic_context, current_pctx               # verified: semantic/context.py:44, :86
from .errors import SemanticAccessError, SemanticPolicyError, SemanticValidationError  # verified: errors.py:23-31
from .governance.pipeline import subject_digest                         # verified: pipeline.py:77
from .models import SemanticQuery, SemanticQueryResult                 # verified: models.py:102, :217
from .toolkit import SemanticLayerToolkit                               # verified: toolkit.py:38
```

### Existing Signatures to Use
```python
# semantic/toolkit.py
class SemanticLayerToolkit(AbstractToolkit):     # line 38; __init__(**kwargs) line 43 (models_dir, dialect, ...)
    _dialect: str                                # line 75
    _models: dict[str, LoadedModel]              # line 77
    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult  # line 200
# semantic/context.py
def current_pctx() -> PermissionContext | None  # line 44 (reads the SEMANTIC variable)
@asynccontextmanager async def bind_semantic_context(ctx, *, identity=None)  # line 86; raises
#   SemanticAccessError('context_required') unless isinstance(ctx, PermissionContext) (line 101)
# semantic/governance/pipeline.py
def subject_digest(ctx: PermissionContext | None) -> str   # line 77
# semantic/models.py — SemanticQuery(extra='forbid') line 102; SemanticQueryResult line 217:
#   columns, rows, row_count, truncated, duration_ms, compiled_sql, audit_id, result_id
# semantic/errors.py — SemanticError(code, message='', *, details=None) line 17
# semantic/__init__.py — `__all__ = [` line 7
```

### Does NOT Exist
- ~~a public models accessor on SemanticLayerToolkit~~ — use `toolkit._models` (same distribution).
- ~~`timezone` support~~ — not in QUERY_FIELDS; the compiler rejects it.
- ~~`require_identity` for bridged calls~~ — a bridged call has no identity; `query_metrics` then retains no handle.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/dataset_source.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_dataset_source.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit.query_metrics",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/context.py#bind_semantic_context",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/context.py#current_pctx",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py#subject_digest",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py#DataSource"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_pctx_var.get(None)` may hold anything; accept only `PermissionContext` instances.
- Equality check uses `==` on the two contexts, like `SemanticLayerToolkit._pre_execute` (toolkit.py:113-116).
- `current_owner()` never raises and never runs a query.
- Never put SQL into `attrs`.

### References in Codebase
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:110-116` — the context agreement rule.
- `packages/ai-parrot-semantic/tests/test_e2e_governed.py:20-75` — toolkit + context fixtures.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create the module from the block — *why*: names fixed by the spec skeleton.
2. Fill `_resolve_context` and `fetch` — *why*: this is the identity decision.
3. Export `SemanticDataSource` in `__init__.py`.
4. Write the unit tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/dataset_source.py` (CREATE)
```python
"""DatasetManager source backed by one governed semantic model (FEAT-880)."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pandas as pd

from parrot.auth import PermissionContext
from parrot.auth.context import _pctx_var
from parrot.tools.dataset_manager.sources.base import DataSource

from .context import bind_semantic_context, current_pctx
from .errors import SemanticAccessError, SemanticPolicyError, SemanticValidationError
from .governance.pipeline import subject_digest
from .models import SemanticQuery
from .toolkit import SemanticLayerToolkit

QUERY_FIELDS: frozenset[str] = frozenset(
    {"metrics", "dimensions", "time_dimensions", "filters", "order_by", "limit", "offset", "saved_query"}
)


class SemanticDataSource(DataSource):
    """Dataset source backed by one governed semantic model."""

    def __init__(self, *, name: str, toolkit: SemanticLayerToolkit, model: str,
                 default_query: dict[str, Any] | None = None, description: str | None = None,
                 routing_meta: dict | None = None) -> None:
        """Bind ``model`` of ``toolkit``.

        Raises:
            SemanticPolicyError: ``model_not_found`` / ``invalid_default_query``.
        """
        super().__init__(routing_meta=routing_meta)
        if model not in toolkit._models:
            raise SemanticPolicyError("model_not_found", "Unknown semantic model", details={"model": model})
        if default_query and set(default_query) - QUERY_FIELDS:
            raise SemanticPolicyError("invalid_default_query", "default_query has unsupported keys")
        self.name = name
        self.toolkit = toolkit
        self.model = model
        self.default_query = dict(default_query or {})
        self.description = description

    @classmethod
    def from_models_dir(cls, *, name: str, model: str, models_dir: Path, dialect: str,
                        default_query: dict[str, Any] | None = None, description: str | None = None,
                        **toolkit_kwargs: Any) -> "SemanticDataSource":
        """Build a SemanticLayerToolkit and bind ``model``; toolkit errors propagate unchanged."""
        toolkit = SemanticLayerToolkit(models_dir=Path(models_dir), dialect=dialect, **toolkit_kwargs)
        return cls(name=name, toolkit=toolkit, model=model, default_query=default_query, description=description)

    @property
    def self_governed(self) -> bool:
        return True

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        return f"semantic:{self.toolkit._dialect}:{self.model}:{self.name}"

    def describe(self) -> str:
        # FILL IN: static text — model name, pass the query via fetch_dataset `conditions` (QUERY_FIELDS), discover
        #   members with the semantic catalog tools. Bounded by AC: no metric/dimension names.
        ...

    async def prefetch_schema(self) -> dict[str, str]:
        return {}

    def _resolve_context(self) -> tuple[PermissionContext, bool]:
        """Return (context, bridged) or raise SemanticAccessError('context_required')."""
        semantic = current_pctx()
        core = _pctx_var.get(None)
        # FILL IN: both set → must be equal (else raise); semantic only → (semantic, False);
        #   core only → must be isinstance PermissionContext → (core, True); neither → raise. Bounded by spec §2 Identity.
        ...

    def current_owner(self) -> str | None:
        try:
            context, _ = self._resolve_context()
        except SemanticAccessError:
            return None
        return subject_digest(context)

    async def fetch(self, **params: Any) -> pd.DataFrame:
        """Run one governed semantic query and return its rows (see spec §3 M4 for errors)."""
        params.pop("force_refresh", None)
        context, bridged = self._resolve_context()
        # FILL IN: reject "model" and keys outside QUERY_FIELDS (invalid_params); empty → default_query, none →
        #   query_required; build SemanticQuery(model=self.model, **query), wrap pydantic errors as invalid_query.
        query: SemanticQuery
        scope = bind_semantic_context(context) if bridged else contextlib.nullcontext()
        async with scope:
            result = await self.toolkit.query_metrics(query)
        frame = pd.DataFrame(result.rows, columns=result.columns)
        frame.attrs["semantic"] = {"model": self.model, "audit_id": result.audit_id,
                                   "truncated": result.truncated, "row_count": result.row_count}
        return frame
```
**Why**: the bridge binds only when the semantic variable is empty, so a host-bound identity is never replaced.
`contextlib.nullcontext()` supports `async with` on Python ≥ 3.10.

### `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__all__ = \[' __init__.py; line 7)
# AFTER — insert above `__all__` (verified: __init__.py:5):
from .dataset_source import SemanticDataSource
# and add "SemanticDataSource" to __all__.
```

### FILL IN checklist
- [ ] `describe` text — no member names.
- [ ] `_resolve_context` four cases.
- [ ] param validation + SemanticQuery build in `fetch`.
- [ ] tests listed in spec §4 for M4 (incl. `test_fetch_bridges_core_context`, `test_fetch_rejects_non_context_object`, `test_current_owner_resolution`).

---

## Acceptance Criteria

- [ ] All M4 unit tests in spec §4 pass
- [ ] `from parrot.semantic import SemanticDataSource` works
- [ ] No SQL in attrs; description lists no members
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_dataset_source.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_toolkit.py -q`

---

## Test Specification

Reuse `models_dir` / `duckdb_warehouse` from `tests/_models.py` and the `_toolkit` / `_context` pattern of `tests/test_e2e_governed.py:20-75` (copy the helpers into the new file; do not import from another test module). Set the core variable with `token = _pctx_var.set(ctx)` / `_pctx_var.reset(token)`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug datasetmanager-semantic-source --feature-id FEAT-880`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/datasetmanager-semantic-source.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/datasetmanager-semantic-source.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH` set to the absolute `src` dirs of every changed package (worktree rule)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5520 datasetmanager-semantic-source verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
