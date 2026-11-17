# TASK-5536: `AccountingToolkit` core — construction, snapshot acquisition, PBAC, list and explain

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5533, TASK-5534, TASK-5535
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (toolkit), U1/U2, AC13. `AccountingToolkit` (`tool_prefix = "finance"`) is the agent-facing
surface. This task writes its construction (runtimes, ledger, cache, catalog), the required snapshot acquisition
(`snapshot_provider` XOR `snapshot_manifests`), the per-call PBAC hook, lock-protected lazy model loading, and the
two read-only tools `list_metrics` and `explain_metric`. TASK-5537 adds `query_metric` and `validate_model`.

---

## Scope

- `toolkit.py` with `AccountingToolkit.__init__` (signature fixed by spec §3 M8), `_pre_execute`,
  `_resolve_tenant`, `_authorize_metric`, `_visible_names`, `_ensure_loaded`, `list_metrics`, `explain_metric`.
- Snapshot acquisition: exactly one of `snapshot_provider` / `snapshot_manifests` else `ValueError` at
  construction; manifests (`{tenant: {model: path}}`) are adapted into a provider that re-reads the file each call
  via `snapshot_from_manifest`; a missing key or provider failure fails closed (`AccountingExecutionError`).
- `_ensure_loaded(tenant, model)`: under an `asyncio.Lock`, fetch the snapshot, fetch journal columns for a
  `table` source through `DatabaseRuntime.fetch_columns`, then `catalog.load({key: snapshot}, {key: columns})`.
- PBAC (spec §3 M8): `_pre_execute` copies the `_permission_context` kwarg into core `_pctx_var`; with no guard or
  no context everything is allowed; otherwise list filters with `filter_datasets(pctx, names)` and explain requires
  `can_read_dataset(pctx, name)` ⇒ `AuthorizationRequired`. Names: `accounting:<tenant>:<model>:<metric>` (bare —
  the guard adds the `dataset:` prefix).
- Tenant resolution: argument → `pctx.tenant_id` → `default_tenant` → `RequestValidationError`.
- `tests/accounting/test_toolkit.py`: `test_toolkit_list_and_explain`, `test_toolkit_pbac_filtering` (list/explain
  half), `test_toolkit_allows_without_guard_or_context` (list/explain half), `test_policy_resource_names`,
  `test_snapshot_acquisition`.

**NOT in scope**: `query_metric`, `validate_model`, live validation, `test_toolkit_tools_and_prefix` (TASK-5537);
CLI (TASK-5539).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py` | CREATE | toolkit core |
| `packages/ai-parrot-semantic/tests/accounting/test_toolkit.py` | CREATE | toolkit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                      # CORE/tools/toolkit.py:225
from parrot.auth.context import _pctx_var                             # CORE/auth/context.py:33 (not re-exported by parrot.auth)
from parrot.auth.exceptions import AuthorizationRequired              # CORE/auth/exceptions.py:15
from parrot.auth.dataset_guard import DatasetPolicyGuard              # CORE/auth/dataset_guard.py:56
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit   # CORE/tools/databasequery/toolkit.py:115
from parrot.semantic.audit import SemanticAuditLedger                 # SL/audit.py:70
from parrot.semantic.cache import CompileCache                        # SL/cache.py:32
from parrot.semantic.execution import ConnectionResolver, Executor    # SL/execution.py:18, :52
from parrot.interfaces.duckdb_engine import DuckDBEngine              # TASK-5523
from parrot.semantic.accounting.audit import AuditMode, audit_mode_from_env       # TASK-5534
from parrot.semantic.accounting.catalog import ModelCatalog, SnapshotProvider     # TASK-5535
from parrot.semantic.accounting.runtime.database import DatabaseRuntime           # TASK-5533
from parrot.semantic.accounting.runtime.duckdb import DuckDBRuntime, FrameProvider  # TASK-5533
from parrot.semantic.accounting.snapshot import snapshot_from_manifest            # TASK-5528
from parrot.semantic.accounting.errors import AccountingExecutionError, RequestValidationError
```

### Existing Signatures to Use
```python
# CORE/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):        # :225 — subclasses call super().__init__(**kwargs) (see SL/toolkit.py:74)
    exclude_tools: tuple[str, ...] = ()                  # :262
    tool_prefix: str | None = None                       # :276
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # :491 — called at :179 with
        # hook_kwargs["_permission_context"] (:178), always present (may be None); stripped before the tool runs
    def _generate_tools(self) -> None                    # :575 — every public coroutine attribute becomes a tool
# CORE/auth/dataset_guard.py
class DatasetPolicyGuard:                                # :56
    async def filter_datasets(self, context, dataset_names: list[str]) -> set[str]   # :128 — ResourceType.DATASET, "dataset:read"
    async def can_read_dataset(self, context, dataset_name: str) -> bool             # :278
# CORE/auth/exceptions.py:15 — AuthorizationRequired(tool_name=..., message=...)
# CORE/auth/permission.py — PermissionContext.tenant_id (:137)
# CORE/tools/dataset_manager/tool.py:2846-2900 — DatasetManager._pre_execute (the pattern to copy):
#   pctx = kwargs.get("_permission_context"); _pctx_var.set(pctx); `if not self._policy_guard or not pctx: return`
```

### Does NOT Exist
- ~~`_permission_context` reaching a tool method~~ — only `_pre_execute` sees it; tools read `_pctx_var.get()`.
- ~~`parrot.semantic.context.current_pctx()`~~ for this toolkit — it reads the satellite's own ContextVar, which
  this toolkit does not bind.
- ~~`parrot.auth._pctx_var`~~ — import from `parrot.auth.context`.
- ~~public helper coroutines~~ — every non-tool coroutine must start with `_` (else `_generate_tools` exposes it).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/auth/dataset_guard.py#DatasetPolicyGuard",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager._pre_execute"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Construction never touches a snapshot or a journal — identities and permissions come from `catalog.specs()`.
- `engine` defaults to a lazily created `DuckDBEngine(threads=duckdb_threads)` only when a dataframe-backed model
  is first queried, so constructing the toolkit does not require the `duckdb` extra.
- `models_dir` default: `FINANCE_MODELS_DIR` env, else `./models`. `audit_mode` default: `audit_mode_from_env()`.
- Ledger: `SemanticAuditLedger(signer=signer, storage=audit_storage)`; cache: `CompileCache()`; executor:
  `Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver())`.
- `explain_metric` output is plain text: formula, inlined formula, each set with its accounts, covering assertions.
- Model selection when `model` is omitted: the unique model of the tenant defining the metric; ambiguous ⇒
  `RequestValidationError` listing candidates.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor and snapshot-acquisition adapter — *why*: everything else depends on it; XOR is a hard rule.
2. `_pre_execute`, tenant resolution, authorization helpers.
3. `_ensure_loaded`, `list_metrics`, `explain_metric`.
4. Tests with a fake guard whose evaluator allows a fixed set of names.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py` (CREATE)
```python
"""Finance tools over the accounting metrics layer (FEAT-713 M8).

Governance posture: metric visibility through DatasetPolicyGuard; with no guard or no permission context every
metric is allowed (as DatasetManager). The ``sl_*`` tools of this package fail closed instead.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from parrot.auth.context import _pctx_var
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic.audit import SemanticAuditLedger
from parrot.semantic.cache import CompileCache
from parrot.semantic.execution import ConnectionResolver, Executor
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit

from .audit import AuditMode, audit_mode_from_env
from .catalog import ModelCatalog, SnapshotProvider
from .errors import AccountingExecutionError, RequestValidationError
from .runtime.database import DatabaseRuntime
from .runtime.duckdb import FrameProvider
from .snapshot import snapshot_from_manifest


class AccountingToolkit(AbstractToolkit):
    """Finance tools: the LLM picks metric + grain + filters + period; the compiler writes the SQL."""

    tool_prefix = "finance"

    def __init__(self, *, models_dir: Path | str | None = None,
                 snapshot_provider: SnapshotProvider | None = None,
                 snapshot_manifests: Mapping[str, Mapping[str, Path | str]] | None = None,
                 database_toolkit: DatabaseQueryToolkit | None = None,
                 frame_provider: FrameProvider | None = None,
                 engine: Any = None,
                 policy_guard: Any = None,
                 signer: Any = None,
                 audit_storage: Callable[[str], Awaitable[None]] | None = None,
                 audit_mode: AuditMode | None = None, default_tenant: str | None = None,
                 duckdb_threads: int = 4, result_limit: int = 10_000, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if (snapshot_provider is None) == (snapshot_manifests is None):
            raise ValueError("configure exactly one of snapshot_provider or snapshot_manifests")
        self._catalog = ModelCatalog(Path(models_dir or os.environ.get("FINANCE_MODELS_DIR", "./models")))
        self._snapshot_provider = snapshot_provider or self._manifest_provider(snapshot_manifests)
        self._frame_provider = frame_provider
        self._engine = engine
        self._duckdb_threads = duckdb_threads
        self._policy_guard = policy_guard
        self._ledger = SemanticAuditLedger(signer=signer, storage=audit_storage)
        self._audit_mode: AuditMode = audit_mode or audit_mode_from_env()
        self._cache = CompileCache()
        self._database = DatabaseRuntime(Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver()),
                                         result_limit=result_limit)
        self._default_tenant = default_tenant
        self._load_lock = asyncio.Lock()

    @staticmethod
    def _manifest_provider(manifests: Mapping[str, Mapping[str, Path | str]]) -> SnapshotProvider:
        async def provider(tenant: str, model: str, spec) -> Any:
            # FILL IN: missing tenant/model key ⇒ AccountingExecutionError; re-read the file every call
            #   (asyncio.to_thread(snapshot_from_manifest, Path(path))).
            raise NotImplementedError
        return provider

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Per-call PBAC hook (hook verified: toolkit.py:491; pattern: dataset_manager/tool.py:2846)."""
        _pctx_var.set(kwargs.get("_permission_context"))

    def _resolve_tenant(self, tenant: str | None) -> str:
        # FILL IN: argument → _pctx_var.get().tenant_id → default_tenant → RequestValidationError.
        raise NotImplementedError

    @staticmethod
    def _resource(tenant: str, model: str, metric: str) -> str:
        return f"accounting:{tenant}:{model}:{metric}"

    async def _authorize(self, tool_name: str, names: list[str]) -> None:
        """Every name must be readable; no guard or no context ⇒ allowed."""
        # FILL IN: for each name can_read_dataset; first denial ⇒ AuthorizationRequired(tool_name=..., message=...).
        raise NotImplementedError

    async def _ensure_loaded(self, tenant: str, model: str) -> Any:
        """Load (tenant, model) once under the lock; return the AccountingModel."""
        # FILL IN: see Scope; provider failure ⇒ AccountingExecutionError; never publish a partial model.
        raise NotImplementedError

    async def list_metrics(self, tenant: str | None = None) -> list[dict]:
        """Catalog of metrics visible to the caller (PBAC-filtered)."""
        # FILL IN: specs only (no snapshot); filter_datasets when guard + context; dicts with model, metric,
        #   description, unit, dimensions.
        raise NotImplementedError

    async def explain_metric(self, metric: str, model: str | None = None, tenant: str | None = None) -> str:
        """Formula, resolved accounts per set, and covering assertions, as plain text."""
        # FILL IN: resolve model, authorize, _ensure_loaded, render the explanation.
        raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/accounting/test_toolkit.py` (CREATE)
```python
"""FEAT-713 M8 — AccountingToolkit core."""

from __future__ import annotations


async def test_toolkit_list_and_explain(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: provider returning chart_snapshot; list_metrics("troc") lists all metrics; explain_metric names sets.


async def test_toolkit_pbac_filtering(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    # FILL IN: fake guard allowing one metric; list shows one; explain on another ⇒ AuthorizationRequired.


async def test_toolkit_allows_without_guard_or_context(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    # FILL IN: no guard ⇒ all visible; guard but no context ⇒ all visible.


async def test_policy_resource_names(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    # FILL IN: a real DatasetPolicyGuard over a recording evaluator receives bare "accounting:troc:troc_pnl:<m>"
    #   names; the evaluator sees dataset resources and action "dataset:read".


async def test_snapshot_acquisition(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    # FILL IN: neither / both configured ⇒ ValueError; provider receives (tenant, model, spec); manifest adapter
    #   re-reads the file; missing manifest key or provider error ⇒ AccountingExecutionError and nothing loaded.
```

### FILL IN checklist
- [ ] `_manifest_provider`, `_resolve_tenant`, `_authorize`, `_ensure_loaded`, `list_metrics`, `explain_metric`.
- [ ] Five tests.

---

## Acceptance Criteria

- [ ] Construction requires exactly one snapshot source and touches no snapshot or journal (AC15 half).
- [ ] PBAC hides/blocks metrics with guard + context; allows everything without either (AC13 half).
- [ ] The guard receives bare `accounting:<tenant>:<model>:<metric>` names.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_toolkit.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5536 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt c2ff8d55b60748528b1cf1060883f3cc), commit f085a16b77
**Date**: 2026-11-12
**Notes**: `accounting/toolkit.py` AccountingToolkit core (tool_prefix `finance`): construction rules, snapshot provider/manifests, tenant resolution, PBAC filtering for list_metrics/explain_metric (`accounting:<tenant>:<model>:<metric>`), lazy all-or-nothing `_ensure_loaded`, list_metrics, explain_metric. engine/frame_provider/duckdb_threads are stored for TASK-5537. 7 tests green + neighbours; ruff clean.
Notes for review: explain_metric uses its own small `_render`/`_metric_closure` helpers (built on grammar.parse_expr/parse_assertion/references) instead of the compiler's private `_lineage`/`_metric_closure`; the manifest test compares account ids and natures, not snapshot_hash (snapshot_from_rows sorts tags); manifest reading uses asyncio.to_thread but no thread-id spy test covers it.

**Deviations from spec**: added `_authorize_metric`, `_visible_names`, `_guarded_context`, `_resolve_model` helpers beyond the blueprint's `_authorize`.
