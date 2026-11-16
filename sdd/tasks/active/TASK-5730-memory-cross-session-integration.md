# TASK-5730: Prove cross-session recall with real SQLite

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5728, TASK-5729
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement M5's four integration cases; unit tests belong to their respective implementation tasks.

## Scope

- Implement M5's four integration cases; unit tests belong to their respective implementation tasks.
- Use tmp_path SQLite, explicit runtime scopes/UTC events and fake extraction; build managers through the real factory.
- Record response events, close session A, then reopen a new manager/session B and assert profile/interaction content and refs.
- Check the fake extractor received TASK-5729's durability/language prompt; test user and tenant isolation.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/memory/unified/test_cross_session_recall.py` | CREATE | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import pytest
from parrot.memory.agent_memory.factory import create_memory_manager
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager
```

### Dependency-created Imports

No unimplemented import is assumed before its dependency is complete.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/factory.py#create_memory_manager` — `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py:144`: `async def create_memory_manager(config: AgentMemoryConfig, *, namespace: MemoryNamespace, evidence_tenant_resolver: EvidenceTenantResolver | None=None) -> UnifiedMemoryManager`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#AgentMemoryConfig` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:15`: `class AgentMemoryConfig(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryEvent` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:136`: `class MemoryEvent(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:52`: `class MemoryRequestScope(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.record_event` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:299`: `async def record_event(self, event: MemoryEvent) -> MemoryWriteReceipt`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.prepare_context` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:206`: `async def prepare_context(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.cleanup` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:144`: `async def cleanup(self) -> None`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace` — `packages/ai-parrot/src/parrot/memory/episodic/models.py:214`: `class MemoryNamespace(BaseModel)`

### Does NOT Exist

- This integration module does not exist; no shared conftest.py change is necessary.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_cross_session_recall.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/factory.py#create_memory_manager",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#AgentMemoryConfig",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryEvent",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.record_event",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.prepare_context",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.cleanup",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace"
  ]
}
```

## Implementation Notes

Tests TASK-5728's automatic profile/recall output and consumes TASK-5729's extraction prompt through recorded fake-client calls.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/tests/memory/unified/test_cross_session_recall.py` (CREATE)

```python
"""Factory-to-store-to-prompt cross-session proof without network calls."""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import pytest
from parrot.memory.agent_memory.factory import create_memory_manager
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager


class FakeExtractionClient:
    """Return fixed explicit knowledge and record extraction prompts."""
    model = "fixture"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ask(self, prompt: str, **kwargs: Any) -> SimpleNamespace:
        """Return a deterministic Spanish preference without network access."""
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(output=json.dumps([{
            "kind": "preference", "normalized_key": "response_length",
            "value": "Prefiere respuestas cortas", "provenance": "explicit",
        }]))


@pytest.mark.asyncio
async def test_user_knowledge_reaches_new_session(tmp_path: Path) -> None:
    """Reopened managers deliver learned preferences for unrelated questions."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_episode_from_earlier_session_is_recalled(tmp_path: Path) -> None:
    """New-session queries recall the earlier matching interaction."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_same_session_episode_is_not_recalled(tmp_path: Path) -> None:
    """The originating session excludes its own interaction."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_other_user_sees_nothing(tmp_path: Path) -> None:
    """Another user receives neither private facts nor episodes."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Close session A and build a new manager against the same file; shared in-memory objects cannot prove persistence.

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/memory/unified/test_cross_session_recall.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: All four tests run without Redis, providers, network or optional FAISS.
- [ ] **AC-2**: Session B has no session-A conversation history yet receives profile and matching earlier interaction.
- [ ] **AC-3**: Every manager/store closes in finally on success or failure.
- [ ] **AC-4**: The cached feature validation contract remains the merge/feature gate, including unchanged FEAT-903 review tests.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_cross_session_recall.py -q`

## Test Specification

Use named blueprint cases as the acceptance matrix. Cover the adversarial boundaries in Scope/ACs and preserve existing regressions.

## Agent Instructions

1. Use the host session and feature worktree provisioned by `parrot sdd worktree ensure --slug user-memory-recall-e2e --feature-id FEAT-904`; never implement on dev.
2. Read the spec and confirm every dependency is done in `sdd/tasks/index/user-memory-recall-e2e.json`.
3. Re-verify contracts and use sdd-start lifecycle; never silently expand target files.
4. Activate the shared venv and set PYTHONPATH=packages/ai-parrot/src for worktree tests; never uv sync there.
5. Run scoped validation and applicable lint; retain logs in artifacts/logs/.
6. Commit implementation, then use parrot sdd task finalize with real TaskCompletionEvidence and exact implementation HEAD.
7. Inspect generated Completion Note and active-to-completed move; commit only task SDD state. Do not hand-edit completion state or push from the worker.

## Completion Note

Pending; the task finalizer generates this after implementation and validation.
