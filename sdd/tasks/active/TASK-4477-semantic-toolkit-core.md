# TASK-4477: SemanticLayerToolkit — catalog, compile and query tools (M10a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4468, TASK-4472, TASK-4473, TASK-4474, TASK-4475, TASK-4476
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 + §2 New Public Interfaces + §8 Q5: the `AbstractToolkit` surface (`tool_prefix="sl"`). `_pre_execute` sets the satellite ContextVar AND `parrot.auth.context._pctx_var` from `_permission_context` (or a flagged `static_subject`); every tool goes catalog-check → compile (cached) → govern → execute/return → audit. This task ships the governed metric tools; `run_sql` and `save_result_as_dataset` are TASK-4479 (security-gated last, spec Worktree Strategy).

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/context.py` (`_semantic_pctx_var`, `current_pctx`).
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`: `StaticSubject`, `SemanticLayerToolkit` with `list_models`, `list_metrics`, `get_dimensions`, `get_dimension_values`, `search_data_model`, `list_saved_queries`, `compile_query`, `query_metrics`, `reload`, `_pre_execute`, `_post_execute`.
- Constructor: load models, register policy RLS rules into the `RlsRegistry`, refuse governed models without `dataplane_guard` (`SemanticPolicyError`), resolve `audit_required=None` → `ledger.durable` with a startup log line (§8 Q5), `exclude_tools` includes `run_sql` and `save_result_as_dataset` (TASK-4479 makes them conditional).
- Finalize `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` exports.
- Write `test_toolkit.py` (exposure, static subject, audit_required resolution).

**NOT in scope**: `run_sql`, `save_result_as_dataset`, `_dataset_manager_for` (TASK-4479); the e2e security suite (TASK-4478); HTTP/MCP (TASK-4480/4481).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/context.py` | CREATE | per-call subject ContextVar |
| `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` | CREATE | SemanticLayerToolkit |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | MODIFY | public exports |
| `packages/ai-parrot-semantic/tests/test_toolkit.py` | CREATE | toolkit unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                       # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:225
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit    # verified: databasequery/toolkit.py:115
from parrot.auth import PermissionContext, UserSession, RlsRegistry, DataPlanePolicyGuard   # verified: auth/__init__.py lazy map
from parrot.auth.context import _pctx_var                              # verified: packages/ai-parrot/src/parrot/auth/context.py:33
from parrot.security import AbstractKMSSigner                          # verified: security/__init__.py:50-55
from parrot.semantic.loader import SemanticModelLoader, LoadedModel    # TASK-4467
from parrot.semantic.engines import compile as compile_query_sql      # TASK-4467 (native branch: TASK-4468)
from parrot.semantic.governance.pbac import PbacGate                   # TASK-4469
from parrot.semantic.governance.rls import RlsPushdown                 # TASK-4470
from parrot.semantic.governance.pipeline import GovernancePipeline, subject_digest   # TASK-4472
from parrot.semantic.catalog import RoleCatalog                        # TASK-4473
from parrot.semantic.audit import SemanticAuditLedger, SemanticAuditEntry   # TASK-4474
from parrot.semantic.execution import ConnectionResolver, Executor     # TASK-4475
from parrot.semantic.cache import CompileCache                         # TASK-4475
from parrot.semantic.results import ResultHandleStore, ResultHandle    # TASK-4476
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):   # line 37 — re-injects hook_kwargs["_permission_context"] = pctx before toolkit._pre_execute (174-178)
class AbstractToolkit(ServerManagedToolkit, ABC):   # line 225
    exclude_tools: tuple[str, ...] = ()   # line 262
    tool_prefix: str | None = None        # line 276
    def __init__(self, **kwargs)          # line 357 — reads return_direct/base_url/credential_provider/executor/...
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None             # line 491
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any   # line 506 — tool params only (no _permission_context)
    def get_tools(...)                    # line 522
# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:175-176 — conditional exclusion pattern:
#     if self._output_dir is None: self.exclude_tools = self.exclude_tools + ("save_result",)
# packages/ai-parrot/src/parrot/auth/context.py:33 — _pctx_var: ContextVar["PermissionContext | None"]
# packages/ai-parrot/src/parrot/auth/rls_registry.py:112 — RlsRegistry.register(rule)
```

### As-built signatures from earlier waves (added 2026-10-19 — use these, not the spec skeleton)
- `RoleCatalog.visible_members(model, roles, *, authorized: bool)` and `RoleCatalog.search(..., *, authorized: dict[str, bool])`
  — keyword-only `authorized`; pass the PBAC manifest outcome per model (governed + unauthorized ⇒ empty).
- `SemanticAuditLedger.verify(entry)` is **async** (core `AbstractKMSSigner.sign/verify` are async) — `await` it.
- `GovernancePipeline.govern(...)` already threads RLS/mask trusted nodes into `PositiveGuard`; never call the
  guard yourself on governed SQL.
- `ModelPolicy.usage_allowed/mask_for` take physical `<schema>.<table>.<column>` names.
- Core DuckDB `databasequery` source is broken in this env (issue:58d44d14dd8a); tests patch the source `query()`
  the way `tests/test_execution.py` does.

### Does NOT Exist
- ~~`_post_execute` receiving `_permission_context`~~ — read the ContextVar set in `_pre_execute`.
- ~~Storing the subject on `self`~~ — forbidden (concurrent calls); ContextVar only.
- ~~`SemanticLayerToolkit.run_sql` / `.save_result_as_dataset`~~ — TASK-4479; this task only lists them in `exclude_tools`.
- ~~`RlsRegistry()` with required args~~ — FILL IN: read its `__init__` (rls_registry.py:87-111) before constructing a default.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/context.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_toolkit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool",
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsRegistry"
  ]
}
```

---

## Implementation Notes

- Tool methods are public `async def` with Google docstrings — the docstring IS the LLM tool description.
- Errors: tools catch `SemanticError` and return `{"error": code, "message": ..., "details": ...}` — never SQL; every outcome (ok/denied/validation_error/execution_error) still appends an audit entry.
- `static_subject` → `PermissionContext(UserSession(...))` built per call, logged at WARNING once per call, audit `static_subject=True`, `channel="mcp-local"`.
- Blueprint size: toolkit.py exceeds 80 lines in total — write the skeleton below, then the tool bodies, each following the same `_run_governed` helper.

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
1. Write `context.py` — *why*: per-call subject isolation.
2. Write the constructor wiring (loader, registry, pbac, pipeline, catalog, ledger, executor, cache, handles) — *why*: fail closed at startup when governed + no guard.
3. Write `_pre_execute`/`_post_execute` — *why*: ContextVars + dict serialization.
4. Write `_run_governed(query, *, execute: bool)` once and make every tool use it — *why*: one governance path (AC3-AC9).
5. Finalize `__init__.py`; write tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/context.py` (CREATE)
```python
"""Per-call subject ContextVar for the semantic toolkit (never stored on the instance)."""
from __future__ import annotations

import contextvars

from parrot.auth import PermissionContext

_semantic_pctx_var: contextvars.ContextVar[PermissionContext | None] = contextvars.ContextVar(
    "semantic_pctx", default=None)
_static_subject_var: contextvars.ContextVar[bool] = contextvars.ContextVar("semantic_static", default=False)


def current_pctx() -> PermissionContext | None:
    """PermissionContext of the current tool call, or None."""
    return _semantic_pctx_var.get()
```

### `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` (CREATE — skeleton; tool bodies follow the same pattern)
```python
"""SemanticLayerToolkit — governed metric queries for agents (spec §3 Module 10)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from parrot.auth import PermissionContext, UserSession
from parrot.auth.context import _pctx_var
from parrot.tools.toolkit import AbstractToolkit

from .context import _semantic_pctx_var, _static_subject_var, current_pctx
from .errors import SemanticError, SemanticPolicyError
from .models import SemanticQuery, SemanticQueryResult


class StaticSubject(BaseModel):
    user_id: str
    tenant_id: str
    roles: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticLayerToolkit(AbstractToolkit):
    """Governed semantic-layer tools: catalog, compile and metric queries."""
    tool_prefix = "sl"
    exclude_tools = ("reload", "run_sql", "save_result_as_dataset")

    def __init__(self, **kwargs: Any) -> None:
        """kwargs: models_dir, dialect, dataplane_guard, rls_registry, database_toolkit, signer, audit_storage,
        allow_raw_sql=False, static_subject=None, dataset_manager_factory=None, result_ttl_s=900,
        result_store_max=256, allowed_functions=None, audit_required=None."""
        super().__init__(**kwargs)
        # FILL IN: pop our kwargs; loader = SemanticModelLoader(Path(models_dir), driver=...); self._models = loader.load();
        #   any governed model and dataplane_guard is None -> SemanticPolicyError("guard_required");
        #   registry = rls_registry or RlsRegistry(...); register every model.policy.rls rule;
        #   self._pipeline = GovernancePipeline(pbac=PbacGate(guard), rls=RlsPushdown(registry), allowed_functions=...);
        #   self._catalog, self._ledger (SemanticAuditLedger(signer, audit_storage)), self._cache, self._handles,
        #   self._executor (Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver()));
        #   self._audit_required = ledger.durable if audit_required is None else bool(audit_required)  (§8 Q5)
        #   + self.logger.info("semantic audit_required=%s (durable sink=%s)", ...)

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Set both ContextVars from kwargs['_permission_context'] or the static subject (flagged + logged)."""
        # FILL IN: pctx = kwargs.get("_permission_context"); if None and self._static_subject: build
        #   PermissionContext(session=UserSession(...), channel="mcp-local"), _static_subject_var.set(True),
        #   self.logger.warning("static_subject %s used for %s", user_id, tool_name);
        #   _semantic_pctx_var.set(pctx); _pctx_var.set(pctx)

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Serialize pydantic results to plain dicts for the LLM."""
        return result.model_dump(mode="json") if isinstance(result, BaseModel) else result

    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult | dict:
        """Run a governed metric query: role check, compile, govern (PBAC, lineage, RLS, masking, guard),
        execute and audit. Returns rows plus the governed SQL as executed."""
        # FILL IN: return await self._run_governed(query, execute=True)

    async def _run_governed(self, query: SemanticQuery, *, execute: bool) -> Any:
        """The single governance path every tool uses."""
        # FILL IN: ctx = current_pctx(); roles = frozenset(ctx.session.roles) if ctx else frozenset();
        #   model = self._models[query.model]; query = self._catalog.expand_saved_query(query) if saved;
        #   await pbac.authorize_manifest (governed); self._catalog.check_query_rights(query, roles);
        #   compiled = await compile_query_sql(query, model, dialect, cache=self._cache);
        #   governed = await self._pipeline.govern(compiled.sql, model=..., ctx=ctx, roles=roles, requested_limit=query.limit);
        #   execute -> self._executor.run(...); store handle when enabled; audit entry for EVERY outcome
        #   (await self._ledger.append(entry, required=self._audit_required) — required failure withholds rows);
        #   SemanticError -> {"error": e.code, ...} after auditing
        raise NotImplementedError

    # FILL IN: list_models, list_metrics, get_dimensions, get_dimension_values (governed SELECT DISTINCT via
    #   _run_governed-equivalent path), search_data_model, list_saved_queries, compile_query (govern, no execute),
    #   reload (not a tool — excluded) — signatures verbatim from spec §2 New Public Interfaces
```
**Why**: spec §3 M10 skeleton; one `_run_governed` path is what makes AC3-AC9 hold for every tool.

### `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified at task start: grep -c -F '__all__ = ["__version__"]' packages/ai-parrot-semantic/src/parrot/semantic/__init__.py — created by TASK-4463)
# REPLACE `__all__ = ["__version__"]` with:
from .errors import (SemanticAccessError, SemanticError, SemanticExecutionError, SemanticPolicyError,
                     SemanticResultError, SemanticValidationError)
from .models import SemanticQuery, SemanticQueryResult
from .toolkit import SemanticLayerToolkit, StaticSubject

__all__ = ["__version__", "SemanticLayerToolkit", "StaticSubject", "SemanticQuery", "SemanticQueryResult",
           "SemanticError", "SemanticValidationError", "SemanticPolicyError", "SemanticAccessError",
           "SemanticExecutionError", "SemanticResultError"]
```

### FILL IN checklist
- [ ] Constructor wiring — bounded by spec M10 (fail closed without guard) and §8 Q5.
- [ ] `_pre_execute` — bounded by AC13 (static subject logged + flagged).
- [ ] `_run_governed` — bounded by AC3-AC9, AC19.
- [ ] Remaining catalog tools — bounded by AC19 (nothing without an authorized subject).

---

## Acceptance Criteria

- [ ] `test_toolkit_tool_exposure` (core half: no `sl_run_sql`, no `sl_save_result_as_dataset`; governed + no guard → constructor error), `test_toolkit_static_subject_logged`, `test_audit_required_resolution` pass.
- [ ] Tool names are prefixed `sl_` (`sl_query_metrics`, ...).
- [ ] `from parrot.semantic import SemanticLayerToolkit` works.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_toolkit.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_toolkit.py
import pytest
from ._models import models_dir, duckdb_warehouse  # noqa: F401
from parrot.semantic import SemanticLayerToolkit, SemanticPolicyError


def test_toolkit_tool_exposure(models_dir):
    with pytest.raises(SemanticPolicyError):
        SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb")   # governed model, no guard
    # FILL IN: with allow_all_guard -> names include sl_query_metrics, exclude sl_run_sql / sl_save_result_as_dataset


def test_audit_required_resolution(models_dir, allow_all_guard):
    # FILL IN: no audit_storage -> _audit_required False; audit_storage=AsyncMock() -> True; explicit False wins;
    #          True + failing sink -> query_metrics returns error audit_unavailable and no rows
    ...


async def test_toolkit_static_subject_logged(models_dir, allow_all_guard, caplog):
    # FILL IN: static_subject={"user_id": "operator", "tenant_id": "local", "roles": ["admin"]};
    #          call a tool without _permission_context -> warning logged; ledger entry static_subject True
    ...
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4477 — SemanticLayerToolkit — catalog, compile and query tools (M10a)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4477 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
