# TASK-4477: Governed catalog, compile and query toolkit (M10a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4706, TASK-4472, TASK-4473, TASK-4474, TASK-4475, TASK-4476, TASK-4707, TASK-4709
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M10; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Create SemanticLayerToolkit composing loader/catalog/compiler/governance/executor/audit/handles. Reject any non-null static_subject on ordinary instances and governed construction without a guard.
- Implement list_models/list_metrics/get_dimensions/get_dimension_values/search_data_model/list_saved_queries/compile_query/query_metrics, with precompile manifest authorization, per-request governance and audit-before-return.
- Validate bound context in _pre_execute; do not set global identity there or clean up in _post_execute. Shared get_tools calls must not carry mutable per-request identity on the toolkit instance.
- Expose reload only as a host method. Retain results only with complete trusted identity; capture exact member/physical provenance. Keep raw SQL/save tools excluded until the security-gated extension task; finalize safe package exports.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | MODIFY | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_toolkit.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .context import current_pctx, current_identity, require_identity
from .errors import SemanticPolicyError, SemanticAccessError
from .models import SemanticQuery, SemanticQueryResult
from .toolkit import SemanticLayerToolkit
from __future__ import annotations
from parrot.tools.toolkit import AbstractToolkit
from pathlib import Path
from typing import Any
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:225
class AbstractToolkit(ServerManagedToolkit, ABC):
    # line 357
    def __init__(self, **kwargs):
    # line 491
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
    # line 506
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
    # line 522
    def get_tools(self, permission_context: Optional['PermissionContext']=None, resolver: Optional['AbstractPermissionResolver']=None) -> list[AbstractTool]:
```

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:37
class ToolkitTool(AbstractTool):
    # line 42
    def __init__(self, name: str, bound_method: callable, description: str=None, args_schema: type[BaseModel]=None, **kwargs):
    # line 142
    async def _execute(self, **kwargs) -> Any:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4706: consumes packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py (Join-grain safety, filtered and derived metrics (M5b))
- TASK-4472: consumes packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py (Governance composition and subject/provenance digest (M6d))
- TASK-4473: consumes packages/ai-parrot-semantic/src/parrot/semantic/catalog.py (Authorized catalog and saved-query expansion (M7))
- TASK-4474: consumes packages/ai-parrot-semantic/src/parrot/semantic/audit.py, packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql (Signed audit ledger and optional Postgres sink (M8))
- TASK-4475: consumes packages/ai-parrot-semantic/src/parrot/semantic/execution.py, packages/ai-parrot-semantic/src/parrot/semantic/cache.py (Execution bridge and pre-governance compile cache (M9a))
- TASK-4476: consumes packages/ai-parrot-semantic/src/parrot/semantic/results.py (Scoped result handles and exact retained provenance (M9b))
- TASK-4707: consumes packages/ai-parrot-semantic/src/parrot/semantic/context.py (Scoped identity binding and exception-safe cleanup (M10 context))
- TASK-4709: consumes packages/ai-parrot-semantic/src/parrot/semantic/handoff.py (Guarded dataset sink and read-time authorization (M9H))

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
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool"
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

### `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` (CREATE)

```python
"""Governed semantic tools with trusted host-bound request identity."""
from __future__ import annotations
from typing import Any
from parrot.tools.toolkit import AbstractToolkit
from .models import SemanticQuery, SemanticQueryResult
from .context import current_pctx, current_identity, require_identity
from .errors import SemanticPolicyError, SemanticAccessError

class SemanticLayerToolkit(AbstractToolkit):
    """Catalog, compile and metric query surface over one governance pipeline."""
    tool_prefix = "sl"
    exclude_tools = ("reload", "run_sql", "save_result_as_dataset")
    def __init__(self, **kwargs: Any) -> None:
        """Construct components; reject static_subject and missing governed guard."""
        # FILL IN: consume satellite kwargs before super(), wire dependencies,
        # resolve audit_required, retain results only with complete identity.
        ...
    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Validate bound trusted context; never set or fall back to static identity."""
        ...
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Serialize results; context cleanup belongs to the surrounding wrapper."""
        ...
    async def list_models(self) -> list[dict]:
        """List only models authorized for the current subject."""
        ...
    async def list_metrics(self, model: str) -> list[dict]:
        """Describe allowed metrics of an authorized model."""
        ...
    async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]:
        """Describe allowed dimensions compatible with requested metrics."""
        ...
    async def get_dimension_values(self, model: str, dimension: str,
                                   metrics: list[str] | None = None, limit: int = 50) -> SemanticQueryResult:
        """Query authorized dimension values through the complete governance path."""
        ...
    async def search_data_model(self, text: str, model: str | None = None) -> list[dict]:
        """Search only authorized model members."""
        ...
    async def list_saved_queries(self, model: str) -> list[dict]:
        """List saved queries whose referenced members are all allowed."""
        ...
    async def compile_query(self, query: SemanticQuery) -> dict:
        """Return audited governed SQL without database execution."""
        ...
    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult:
        """Authorize, compile, govern, execute and audit before returning rows."""
        ...
    def reload(self) -> None:
        """Reload model snapshots and invalidate caches; not an LLM tool."""
        ...
    # FILL IN: implement shared private orchestration helpers; AC3–AC10/AC25.
    # Caller binds contexts externally; direct HTTP calls use the same context manager.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (MODIFY)

Dependency-created anchor `__all__ = ["__version__"]` — expected occurrences: **1** in the producer blueprint. It is absent on dev; re-read its actual line/count after the producer lands, before any edit.

```python
# AFTER dependency-created __all__ = ["__version__"] (expected occurrences: 1).
from .models import SemanticQuery, SemanticQueryResult
from .toolkit import SemanticLayerToolkit
__all__ += ["SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]
# FILL IN: preserve lazy optional-backend imports; importing the namespace must
# not require a warehouse driver, static subject or provider SDK.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_toolkit.py` (CREATE)

```python
"""Regression contract: Governed catalog, compile and query toolkit (M10a)."""
from pathlib import Path
import pytest


def test_catalog_compile_query_govern_and_audit(tmp_path: Path) -> None:
    """Verify catalog compile query govern and audit."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_no_static_fallback_or_missing_guard(tmp_path: Path) -> None:
    """Verify no static fallback or missing guard."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_trusted_retention_and_audit_before_return(tmp_path: Path) -> None:
    """Verify trusted retention and audit before return."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_toolkit.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Create SemanticLayerToolkit composing loader/catalog/compiler/governance/executor/audit/handles. Reject any non-null static_subject on ordinary instances and governed construction without a guard.
- [ ] Implement list_models/list_metrics/get_dimensions/get_dimension_values/search_data_model/list_saved_queries/compile_query/query_metrics, with precompile manifest authorization, per-request governance and audit-before-return.
- [ ] Validate bound context in _pre_execute; do not set global identity there or clean up in _post_execute. Shared get_tools calls must not carry mutable per-request identity on the toolkit instance.
- [ ] Expose reload only as a host method. Retain results only with complete trusted identity; capture exact member/physical provenance. Keep raw SQL/save tools excluded until the security-gated extension task; finalize safe package exports.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_toolkit.py -q`

## Test Specification

- `test_catalog_compile_query_govern_and_audit`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_no_static_fallback_or_missing_guard`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_trusted_retention_and_audit_before_return`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4477` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
