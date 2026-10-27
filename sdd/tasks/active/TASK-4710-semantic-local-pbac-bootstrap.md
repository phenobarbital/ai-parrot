# TASK-4710: MCP-local identity and configured PBAC bootstrap (M10c)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4479
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M10; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Create LocalSemanticLayerToolkit as the sole static-identity entry. Require trusted static_subject, agent_id, guard_factory and optional configured kwargs; generate per-instance random session id and fixed mcp-local channel.
- Load dotted factory from host configuration only; call with rls_registry and configured kwargs, require DataPlanePolicyGuard and exact evaluator modules. No role-derived allow-all policy and no factory from tool arguments.
- Wrap actual tool execution in bind_semantic_context with supplied static PermissionContext; reset on failure/cancellation, log/audit every static call. Ordinary HTTP/agent paths reject this local-only class.
- Ship a test fixture factory with explicit allow/deny evaluator behavior and actual MCP construction tests; missing factory/invalid return/policy-load error/unavailable evaluator fail startup. S3 is mandatory.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/_guard_factory.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_bootstrap.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .context import SemanticRequestIdentity, bind_semantic_context
from .errors import SemanticPolicyError
from .toolkit import SemanticLayerToolkit
from __future__ import annotations
from parrot.auth import DataPlanePolicyGuard, RlsRegistry
from parrot.auth import PermissionContext, UserSession, RlsRegistry, DataPlanePolicyGuard
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:37
class ToolkitTool(AbstractTool):
    # line 42
    def __init__(self, name: str, bound_method: callable, description: str=None, args_schema: type[BaseModel]=None, **kwargs):
    # line 142
    async def _execute(self, **kwargs) -> Any:
```

```python
# packages/ai-parrot/src/parrot/auth/dataplane_guard.py:45
class DataPlanePolicyGuard():
    # line 71
    def __init__(self, evaluator: 'PolicyEvaluator', rls_registry: 'RlsRegistry', sensitive_drivers: frozenset[str]=frozenset(), logger: Optional[logging.Logger]=None) -> None:
    # line 193
    async def authorize_source(self, ctx: Optional[PermissionContext], resources: 'PhysicalResources') -> None:
```

```python
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py:137
def create_toolkit_mcp_server(name: str, root: Path=Path.cwd(), **overrides: Any) -> StdioMCPServer:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4479: consumes packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py (Security-gated raw SQL and guarded hand-off tools (M10b))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/_guard_factory.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_bootstrap.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool",
    "sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server"
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

### `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py` (CREATE)

```python
"""Trusted stdio-only semantic toolkit bootstrap; never an HTTP identity fallback."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from parrot.auth import PermissionContext, UserSession, RlsRegistry, DataPlanePolicyGuard
from .context import SemanticRequestIdentity, bind_semantic_context
from .toolkit import SemanticLayerToolkit
from .errors import SemanticPolicyError

class StaticSubject(BaseModel):
    """Trusted local operator identity, never accepted as a tool argument."""
    user_id: str
    tenant_id: str
    roles: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

class LocalSemanticLayerToolkit(SemanticLayerToolkit):
    """Stdio-local subclass that builds its configured PBAC guard at startup."""
    def __init__(self, *, static_subject: StaticSubject | dict[str, Any], agent_id: str,
                 guard_factory: str, guard_factory_kwargs: dict[str, Any] | None = None,
                 **kwargs: Any) -> None:
        """Resolve trusted factory, validate evaluator, create local process session."""
        # FILL IN: configured dotted callable, factory(rls_registry=..., **kwargs),
        # required real guard + evaluator modules; consume static_subject before
        # calling ordinary toolkit constructor; no allow-all role synthesis.
        ...
    # FILL IN: wrap generated tools with a satellite-owned ToolkitTool subclass
    # or equivalent wrapper preserving schemas/names. Its _execute binds/reset
    # static identity in try/finally and supplies _permission_context to hooks.
    # Caller args cannot override identity/channel; HTTP rejects this class (AC26).
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/_guard_factory.py` (CREATE)

```python
"""Explicit test-only PBAC factory for governed MCP startup fixtures."""
from typing import Any
from parrot.auth import DataPlanePolicyGuard, RlsRegistry

def build_guard(*, rls_registry: RlsRegistry, policy_dir: str) -> DataPlanePolicyGuard:
    """Load fixture allow/deny decisions; fail when configuration is missing."""
    # FILL IN: deterministic evaluator implementing check_access/filter_resources
    # with explicit fixture policy decisions; never a production allow-all default.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_bootstrap.py` (CREATE)

```python
"""Regression contract: MCP-local identity and configured PBAC bootstrap (M10c)."""
from pathlib import Path
import pytest


def test_configured_factory_governed_allow_deny(tmp_path: Path) -> None:
    """Verify configured factory governed allow deny."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_missing_invalid_factory_fails_closed(tmp_path: Path) -> None:
    """Verify missing invalid factory fails closed."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_local_only_identity_and_wrapper_cleanup(tmp_path: Path) -> None:
    """Verify local only identity and wrapper cleanup."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/_guard_factory.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_bootstrap.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Create LocalSemanticLayerToolkit as the sole static-identity entry. Require trusted static_subject, agent_id, guard_factory and optional configured kwargs; generate per-instance random session id and fixed mcp-local channel.
- [ ] Load dotted factory from host configuration only; call with rls_registry and configured kwargs, require DataPlanePolicyGuard and exact evaluator modules. No role-derived allow-all policy and no factory from tool arguments.
- [ ] Wrap actual tool execution in bind_semantic_context with supplied static PermissionContext; reset on failure/cancellation, log/audit every static call. Ordinary HTTP/agent paths reject this local-only class.
- [ ] Ship a test fixture factory with explicit allow/deny evaluator behavior and actual MCP construction tests; missing factory/invalid return/policy-load error/unavailable evaluator fail startup. S3 is mandatory.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_bootstrap.py -q`

## Test Specification

- `test_configured_factory_governed_allow_deny`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_missing_invalid_factory_fails_closed`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_local_only_identity_and_wrapper_cleanup`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4710` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
