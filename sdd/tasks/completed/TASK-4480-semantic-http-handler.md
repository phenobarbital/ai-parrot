# TASK-4480: Authenticated HTTP routes and guarded hand-off wiring (M11a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4710
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M11; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Create SemanticLayerHandler GET catalog and POST compile/query/results-id/dataset; session-auth decorators and lazy package registration follow current BaseView patterns.
- Resolve trusted authorized agent id and authenticated server session id, bind SemanticRequestIdentity across direct toolkit calls. Drop caller-supplied identity/context fields and reject LocalSemanticLayerToolkit.
- No default DatasetManager session factory: require configured conforming sink or return handoff_unavailable. Test 401, malformed input, denial, agent/session separation and absent sink.
- Register only when parrot.semantic is importable; do not touch handlers/datasets.py or alter existing server public APIs.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/semantic.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Scoped deliverable per blueprint |
| `packages/ai-parrot-server/tests/unit/test_semantic_handler.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from ..handlers.semantic import SemanticLayerHandler
from __future__ import annotations
from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from parrot.auth import PermissionContext
from pathlib import Path
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/datasets.py:142
class DatasetManagerHandler(BaseView):
```

```python
# packages/ai-parrot-server/src/parrot/manager/manager.py:212
class BotManager():
    # line 222
    def __init__(self, enable_database_bots: bool=ENABLE_DATABASE_BOTS, enable_crews: bool=ENABLE_CREWS, enable_registry_bots: bool=ENABLE_REGISTRY_BOTS, enable_swagger_api: bool=ENABLE_SWAGGER) -> None:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4710: consumes packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py (MCP-local identity and configured PBAC bootstrap (M10c))

- Consumer-specific evidence: LocalSemanticLayerToolkit class rejection and final run_sql/save tool behavior

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
      "path": "packages/ai-parrot-server/src/parrot/handlers/semantic.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_semantic_handler.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/datasets.py#DatasetManagerHandler",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager"
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

### `packages/ai-parrot-server/src/parrot/handlers/semantic.py` (CREATE)

```python
"""Authenticated semantic-layer HTTP views with trusted session identity."""
from __future__ import annotations
from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from parrot.auth import PermissionContext

@is_authenticated()
@user_session()
class SemanticLayerHandler(BaseView):
    """Resolve host identity and call semantic tools within scoped binding."""
    async def get(self) -> web.Response:
        """Return only the authenticated subject's authorized catalog."""
        # FILL IN: trusted session + scoped identity, authorized catalog only.
        ...
    async def post(self) -> web.Response:
        """Dispatch compile/query or guarded result publication."""
        # FILL IN: validated request, trusted agent/session, bind/reset context,
        # reject local-only subclass and return handoff_unavailable without sink.
        ...
    async def _toolkit(self, agent_id: str) -> object:
        """Resolve the authorized agent's ordinary SemanticLayerToolkit lazily."""
        ...
    async def _pctx(self) -> PermissionContext:
        """Build from authenticated navigator session, never caller JSON."""
        ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)

Anchor `from ..handlers.datasets import DatasetManagerHandler` — occurrences: **1**, freshly verified at `packages/ai-parrot-server/src/parrot/manager/manager.py:45`.

Anchor `        router.add_view("/api/v1/agents/datasets/{agent_id}", DatasetManagerHandler)` — occurrences: **1**, freshly verified at `packages/ai-parrot-server/src/parrot/manager/manager.py:2571`.

```python
# At the two verified DatasetManagerHandler import/route anchors (counts below):
# FILL IN: use importlib.util.find_spec("parrot.semantic") and lazy handler import
# only when the satellite is installed; add views beside the existing datasets routes.
if importlib.util.find_spec("parrot.semantic") is not None:
    from ..handlers.semantic import SemanticLayerHandler
    router.add_view("/api/v1/agents/semantic/{agent_id}", SemanticLayerHandler)
    router.add_view("/api/v1/agents/semantic/{agent_id}/{tail:.*}", SemanticLayerHandler)
# Preserve datasets registration unchanged; no edits to handlers/datasets.py.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-server/tests/unit/test_semantic_handler.py` (CREATE)

```python
"""Regression contract: Authenticated HTTP routes and guarded hand-off wiring (M11a)."""
from pathlib import Path
import pytest


def test_routes_session_401_and_no_satellite(tmp_path: Path) -> None:
    """Verify routes session 401 and no satellite."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_trusted_agent_session_and_local_class_rejection(tmp_path: Path) -> None:
    """Verify trusted agent session and local class rejection."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_handoff_unavailable_without_guarded_sink(tmp_path: Path) -> None:
    """Verify handoff unavailable without guarded sink."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/semantic.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-server/src/parrot/manager/manager.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-server/tests/unit/test_semantic_handler.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Create SemanticLayerHandler GET catalog and POST compile/query/results-id/dataset; session-auth decorators and lazy package registration follow current BaseView patterns.
- [ ] Resolve trusted authorized agent id and authenticated server session id, bind SemanticRequestIdentity across direct toolkit calls. Drop caller-supplied identity/context fields and reject LocalSemanticLayerToolkit.
- [ ] No default DatasetManager session factory: require configured conforming sink or return handoff_unavailable. Test 401, malformed input, denial, agent/session separation and absent sink.
- [ ] Register only when parrot.semantic is importable; do not touch handlers/datasets.py or alter existing server public APIs.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_semantic_handler.py -q`

## Test Specification

- `test_routes_session_401_and_no_satellite`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_trusted_agent_session_and_local_class_rejection`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_handoff_unavailable_without_guarded_sink`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4480` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: gpt-5.6-terra (codex), 1 attempt, 365s. Merge-tier selector timed out sweeping direct importers of manager.py; pre-existing failures in tests/bots/prompts/test_yaml_prompt_config.py (BotManager._build_prompt_builder missing on origin/dev too) are unrelated. Own tests verified directly: test_semantic_handler.py + test_botmanager_wiring.py 6 passed. 1 residual ruff finding left for /sdd-done.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
