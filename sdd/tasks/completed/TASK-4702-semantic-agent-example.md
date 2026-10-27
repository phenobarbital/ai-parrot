# TASK-4702: Agent example with guarded DatasetManager facade

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4481
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 owner example; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Preserve the runnable Agent example while upgrading its hand-off to M9H: keep a private per-owner DatasetManager behind a conforming host sink/facade, never attach unguarded DatasetManager tools.
- Build temporary DuckDB warehouse/models, scoped subjects, guarded sink and SemanticLayerToolkit, then Agent with semantic tools plus guarded dataset facade tools. Scripted no-LLM path exercises query/save/read and two-session denial.
- Example guard uses explicit fixture allow/deny policies, not a production allow-all recommendation. All outputs use logging, no print exception to repository conventions.
- Test cached/derived read after expiry/revocation, exact member grants, shared manager refusal and actual Agent tool wiring. README explains production guard/audit/factory wiring and context binding. Gitignored example artifacts need scoped force-add, never blanket staging.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/semantic/agent_semantic_example.py` | CREATE | Scoped deliverable per blueprint |
| `examples/semantic/README.md` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_example_agent.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from __future__ import annotations
from parrot.bots import Agent
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.handoff import GovernedDatasetSink
from parrot.semantic.toolkit import SemanticLayerToolkit
from parrot.tools.dataset_manager import DatasetManager
from parrot.tools.toolkit import AbstractToolkit
from pathlib import Path
from typing import Any
import asyncio
import logging
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
# packages/ai-parrot/src/parrot/bots/agent.py:1576
class Agent(BasicAgent):
```

### Dependency Contracts and Parallelism Evidence

- TASK-4481: consumes .parrot/mcp-toolkits.yaml, .mcp.json (Local MCP configuration and semantic-layer documentation (M11b))

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
      "path": "examples/semantic/agent_semantic_example.py",
      "action": "CREATE"
    },
    {
      "path": "examples/semantic/README.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_agent.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent"
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

### `examples/semantic/agent_semantic_example.py` (CREATE)

```python
"""Runnable Agent example with semantic tools and a guarded private dataset facade."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Any
from parrot.bots import Agent
from parrot.tools.dataset_manager import DatasetManager
from parrot.tools.toolkit import AbstractToolkit
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.toolkit import SemanticLayerToolkit
from parrot.semantic.handoff import GovernedDatasetSink

LOGGER = logging.getLogger(__name__)

class GuardedDatasetFacade(AbstractToolkit):
    """Host example adapter; only guarded methods are exposed to the Agent."""
    # FILL IN: private per-owner DatasetManager + M9H sink protocol and callbacks.
    # Implement list/describe/query/export through authorize_read; reject stale
    # cache/derived data and never return raw manager/source/dataframe references.
    # A raw DatasetManager.get_tools() must never be attached to this Agent.
    ...

def build_warehouse(directory: Path) -> Path:
    """Create deterministic DuckDB fixtures for two subjects."""
    ...

def build_models_dir(directory: Path) -> Path:
    """Write own-format graph and governed policy fixtures."""
    ...

def build_toolkits(directory: Path) -> tuple[SemanticLayerToolkit, GuardedDatasetFacade]:
    """Wire explicit fixture policies and a conforming per-owner host factory."""
    ...

def build_agent(toolkits: tuple[SemanticLayerToolkit, GuardedDatasetFacade]) -> Agent:
    """Construct Agent with semantic and guarded dataset tools, no real LLM call."""
    # FILL IN: tools=[*toolkits[0].get_tools(), *toolkits[1].get_tools()].
    ...

async def main() -> None:
    """Run scripted scoped query, publication, guarded read and denial examples."""
    # FILL IN: bind trusted identities, log results; CPU fixture setup before I/O
    # or in to_thread. No print, credentials or unguarded tool exposure.
    ...

if __name__ == "__main__":
    asyncio.run(main())
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `examples/semantic/README.md` (CREATE)

```markdown
# Semantic Agent example

Run `python examples/semantic/agent_semantic_example.py` with the DuckDB extra.
The scripted mode requires no LLM or network.

<!-- FILL IN: fixture policy and identity setup, private guarded DatasetManager
facade, expiry/revocation demo, smoke test command and production factory/audit
requirements. Never recommend attaching raw dataset tools after hand-off. -->
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_example_agent.py` (CREATE)

```python
"""Regression contract: Agent example with guarded DatasetManager facade."""
from pathlib import Path
import pytest


def test_agent_has_semantic_and_guarded_facade_tools(tmp_path: Path) -> None:
    """Verify agent has semantic and guarded facade tools."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_scripted_no_llm_full_chain(tmp_path: Path) -> None:
    """Verify scripted no llm full chain."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_two_sessions_and_stale_cached_reads(tmp_path: Path) -> None:
    """Verify two sessions and stale cached reads."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `examples/semantic/agent_semantic_example.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `examples/semantic/README.md` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_example_agent.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Preserve the runnable Agent example while upgrading its hand-off to M9H: keep a private per-owner DatasetManager behind a conforming host sink/facade, never attach unguarded DatasetManager tools.
- [ ] Build temporary DuckDB warehouse/models, scoped subjects, guarded sink and SemanticLayerToolkit, then Agent with semantic tools plus guarded dataset facade tools. Scripted no-LLM path exercises query/save/read and two-session denial.
- [ ] Example guard uses explicit fixture allow/deny policies, not a production allow-all recommendation. All outputs use logging, no print exception to repository conventions.
- [ ] Test cached/derived read after expiry/revocation, exact member grants, shared manager refusal and actual Agent tool wiring. README explains production guard/audit/factory wiring and context binding. Gitignored example artifacts need scoped force-add, never blanket staging.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q`

## Test Specification

- `test_agent_has_semantic_and_guarded_facade_tools`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_scripted_no_llm_full_chain`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_two_sessions_and_stale_cached_reads`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4702` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note


- Task: TASK-4702
- Feature: semantic-layer
- Implementation SHA: 67a6c41b92a720a35d1d6fa78d5dfd8aa6123f5c
- Closed at (UTC): 2026-10-26T22:49:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 188.4s · Tokens: n/a |
