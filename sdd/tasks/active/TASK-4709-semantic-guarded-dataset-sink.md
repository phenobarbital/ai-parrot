# TASK-4709: Guarded dataset sink and read-time authorization (M9H)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4472, TASK-4473, TASK-4476
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M9H; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement GovernedDatasetSink protocol: scope_id, immutable owner tuple, guarded_reads=True and async publish(name, handle, authorize_read). Reject raw/shared DatasetManager targets; no default session-manager adapter.
- Build an async authorize_read callback over immutable handle provenance and current model/catalog/PBAC providers. Compare exact owner/context/model/policy/expiry, authorize every member and physical usage; deny changed snapshots and evaluator failure.
- Supply reusable sink conformance helpers and representative private-manager test adapter. All list/metadata/sample/cache/query/export/derived paths invoke callback and withhold data/metadata after revocation; derived outputs inherit provenance and earliest expiry.
- Capability flags alone are not proof. Validate explicit host registration, owner and scope reuse. No unguarded manager, source, dataframe reference or alternate endpoint may escape. Callback uses current caller identity, never captured original context.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/sink_conformance.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_handoff_contract.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .catalog import RoleCatalog
from .context import SemanticRequestIdentity
from .errors import SemanticResultError
from .governance.pbac import PbacGate
from .governance.pipeline import subject_digest
from .loader import LoadedModel
from .results import ResultHandle
from __future__ import annotations
from collections.abc import Awaitable, Callable
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.handoff import GovernedDatasetSink
from pathlib import Path
from typing import Any
from typing import Any, Literal, Protocol, runtime_checkable
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:499
class DatasetManager(AbstractToolkit):
    # line 550
    def __init__(self, df_prefix: str='df', generate_guide: bool=True, include_summary_stats: bool=False, auto_detect_types: bool=True, policy_guard: Optional['DatasetPolicyGuard']=None, dataplane_guard: Optional['DataPlanePolicyGuard']=None, usage_rules: Optional[str]=None, **kwargs):
    # line 1091
    def add_dataframe(self, name: str, df: pd.DataFrame, description: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, is_active: bool=True, computed_columns: Optional[List[Any]]=None, usage_guidance: Optional[Dict[str, List[str]]]=None) -> str:
    # line 2761
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
    # line 2823
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
    # line 2980
    async def get_metadata(self, name: str, include_eda: bool=False, include_samples: bool=True, include_column_stats: bool=False, include_metrics_guide: bool=False, column: Optional[str]=None) -> Dict[str, Any]:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4472: consumes packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py (Governance composition and subject/provenance digest (M6d))
- TASK-4473: consumes packages/ai-parrot-semantic/src/parrot/semantic/catalog.py (Authorized catalog and saved-query expansion (M7))
- TASK-4476: consumes packages/ai-parrot-semantic/src/parrot/semantic/results.py (Scoped result handles and exact retained provenance (M9b))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/handoff.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/sink_conformance.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_handoff_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager"
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

### `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` (CREATE)

```python
"""Guarded host dataset-sink contract and per-read semantic authorization."""
from __future__ import annotations
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, runtime_checkable
from .context import SemanticRequestIdentity
from .results import ResultHandle
from .loader import LoadedModel
from .catalog import RoleCatalog
from .governance.pbac import PbacGate
from .governance.pipeline import subject_digest
from .errors import SemanticResultError
ReadAuthorizer = Callable[[SemanticRequestIdentity], Awaitable[None]]

@runtime_checkable
class GovernedDatasetSink(Protocol):
    """Trusted host adapter; every exposure invokes the registered read authorizer."""
    scope_id: str
    owner: tuple[str, str, str, str]
    guarded_reads: Literal[True]
    async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]:
        """Publish privately without exposing an unguarded manager or source."""
        ...

def build_read_authorizer(handle: ResultHandle, *,
                          models: Callable[[], dict[str, LoadedModel]],
                          catalog: Callable[[], RoleCatalog], pbac: PbacGate) -> ReadAuthorizer:
    """Close over copied provenance; reload current policy before every read."""
    # FILL IN: complete owner, subject, expiry, versions, PBAC and all-member/usage
    # checks; reject reload races before return. Never capture original caller ctx.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/sink_conformance.py` (CREATE)

```python
"""Reusable contract cases for trusted host adapters; flags alone are insufficient."""
from collections.abc import Awaitable, Callable
from typing import Any
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.handoff import GovernedDatasetSink

async def assert_sink_conformance(factory: Callable[..., Awaitable[GovernedDatasetSink]],
                                  identities: tuple[SemanticRequestIdentity, ...]) -> None:
    """Exercise every adapter exposure with authorization revocation and expiry."""
    # FILL IN: publish, list/describe/sample/query/cache/export/derived probes;
    # host fixture exposes its routes through a test-only adapter harness.
    # Check no raw manager/source escapes, callbacks see current caller, stale data
    # is withheld, and copied/derived data inherits provenance and earliest expiry.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_handoff_contract.py` (CREATE)

```python
"""Regression contract: Guarded dataset sink and read-time authorization (M9H)."""
from pathlib import Path
import pytest


def test_exact_provenance_and_scope_rejection(tmp_path: Path) -> None:
    """Verify exact provenance and scope rejection."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_every_exposure_revocation_and_expiry(tmp_path: Path) -> None:
    """Verify every exposure revocation and expiry."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_cached_derived_inheritance_and_reload_race(tmp_path: Path) -> None:
    """Verify cached derived inheritance and reload race."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/sink_conformance.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_handoff_contract.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement GovernedDatasetSink protocol: scope_id, immutable owner tuple, guarded_reads=True and async publish(name, handle, authorize_read). Reject raw/shared DatasetManager targets; no default session-manager adapter.
- [ ] Build an async authorize_read callback over immutable handle provenance and current model/catalog/PBAC providers. Compare exact owner/context/model/policy/expiry, authorize every member and physical usage; deny changed snapshots and evaluator failure.
- [ ] Supply reusable sink conformance helpers and representative private-manager test adapter. All list/metadata/sample/cache/query/export/derived paths invoke callback and withhold data/metadata after revocation; derived outputs inherit provenance and earliest expiry.
- [ ] Capability flags alone are not proof. Validate explicit host registration, owner and scope reuse. No unguarded manager, source, dataframe reference or alternate endpoint may escape. Callback uses current caller identity, never captured original context.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_handoff_contract.py -q`

## Test Specification

- `test_exact_provenance_and_scope_rejection`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_every_exposure_revocation_and_expiry`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_cached_derived_inheritance_and_reload_race`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4709` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
