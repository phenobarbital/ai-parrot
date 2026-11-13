# TASK-5672: AgentMemoryMixin and lazy brain service boundary

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5671, TASK-5654, TASK-5653
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes create_memory_manager from TASK-5671; Consumes request-local scope contract from TASK-5654; Consumes lightweight package initializer; shared-file serialization from TASK-5653

## Context

Implement the bounded A1 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Cooperative configuration, memory hooks and shutdown (`packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py`).
- Export the new facade without importing brain/storage eagerly (`packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py`).
- Injected sibling fake on real Agent and no-brain imports (`packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py`).
- Cooperative configure/reconfigure and shutdown (`packages/ai-parrot/tests/memory/agent_memory/test_facade.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` | CREATE | Cooperative configuration, memory hooks and shutdown |
| `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` | MODIFY | Export the new facade without importing brain/storage eagerly |
| `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` | CREATE | Injected sibling fake on real Agent and no-brain imports |
| `packages/ai-parrot/tests/memory/agent_memory/test_facade.py` | CREATE | Cooperative configure/reconfigure and shutdown |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .factory import create_memory_manager
from .models import MemoryEvent, MemoryRequestScope
from __future__ import annotations
from parrot.bots.abstract import AbstractBot
from parrot.memory.dream.service import BrainService
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryContext
from typing import TYPE_CHECKING, Any
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` is created by TASK-5653; anchor `"""Agent persistent-memory contracts; no eager storage or brain imports."""` is planned, not an existing verified symbol.
- `packages/ai-parrot/src/parrot/bots/abstract.py`: 216:class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):
- `packages/ai-parrot/src/parrot/memory/unified/manager.py`: 53:class UnifiedMemoryManager:
- `packages/ai-parrot/src/parrot/bots/abstract.py:1681` — `AbstractBot.configure`: `async def configure(self, app=None) -> None:`
- `packages/ai-parrot/src/parrot/bots/abstract.py:5527` — `AbstractBot.cleanup`: `async def cleanup(self) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:83` — `UnifiedMemoryManager.__init__`: `def __init__(self, namespace: MemoryNamespace, conversation_memory: Optional[ConversationMemory]=None, episodic_store: Optional[EpisodicMemoryStore]=None, skill_registry: Optional[Any]=None, config: Optional[MemoryConfig]=None, cross_domain_router: Optional[CrossDomainRouter]=None, brain: Optional[BrainStore]=None, org_brain: Optional[BrainStore]=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:109` — `UnifiedMemoryManager.configure`: `async def configure(self, **kwargs: Any) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:124` — `UnifiedMemoryManager.cleanup`: `async def cleanup(self) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:139` — `UnifiedMemoryManager.get_context_for_query`: `async def get_context_for_query(self, query: str, user_id: str, session_id: str) -> MemoryContext:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:178` — `UnifiedMemoryManager.record_interaction`: `async def record_interaction(self, query: str, response: Any, tool_calls: list[Any], user_id: str, session_id: str) -> None:`

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_facade.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_facade.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.cleanup",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.cleanup",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.configure",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.get_context_for_query",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.record_interaction"
  ]
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` (CREATE)

```python
"""Agent lifecycle adapter; stores retain ownership of persistence and dynamics."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
from parrot.memory.unified.models import MemoryContext
from .models import MemoryEvent, MemoryRequestScope
from .factory import create_memory_manager

if TYPE_CHECKING:
    from parrot.memory.dream.service import BrainService

class AgentMemoryMixin:
    """Integrate independently enabled persistent-memory capabilities with a host agent."""
    brain_service: BrainService | None

    async def configure(self, app: Any = None) -> None:
        """Await host setup, respect configure_skipped and initialize/rebind owned resources once."""
        # FILL IN: cooperative super, explicit precedence, genuine app rebind and rollback — AC07.
        # Lazy brain construction uses only the future sibling service; absence -> invalid_configuration.
        raise NotImplementedError

    async def prepare_memory(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
        """Return one scoped supplementary block without loading conversation history."""
        # FILL IN: delegate to manager.prepare_context — AC03/AC05.
        raise NotImplementedError

    async def complete_memory(self, event: MemoryEvent) -> None:
        """Route exactly one completed invocation event to its owning store."""
        # FILL IN: owned write drain/durable queue, not detached swallowed success — AC09/AC12.
        raise NotImplementedError

    async def cleanup(self) -> None:
        """Stop the brain service and drain owned writes before host LLM/storage cleanup."""
        # FILL IN: idempotent stop, derivative retries and cooperative super — AC07/AC15.
        raise NotImplementedError
```

**Why:** Cooperative configuration respects the host's real rebind guard, and lazy brain construction avoids a circular dependency on FEAT-889.

### `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` (MODIFY)

```python
# DEPENDENCY-CREATED MODIFY: packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py from TASK-5653.
# Expected unique anchor: """Agent persistent-memory contracts; no eager storage or brain imports."""
# occurrences now: 0 (file does not exist on base); prerequisite blueprint declares 1.
# Re-read and verify exact count 1 after dependency lands; stop on mismatch.
# Export AgentMemoryMixin with lazy loading if needed to preserve disabled-mode imports.
# FILL IN: __getattr__/__all__ wiring for the documented public facade import — AC04/AC08.
```

**Why:** Cooperative configuration respects the host's real rebind guard, and lazy brain construction avoids a circular dependency on FEAT-889.

### `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` (CREATE)

```python
"""Behavioral acceptance tests for AgentMemoryMixin and lazy brain service boundary."""
import pytest

def test_configure_repeat_and_changed_app() -> None:
    """Verify configure repeat and changed app."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_lazy_missing_brain_and_public_service() -> None:
    """Verify lazy missing brain and public service."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_stop_drain_before_host_cleanup() -> None:
    """Verify stop drain before host cleanup."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Cooperative configuration respects the host's real rebind guard, and lazy brain construction avoids a circular dependency on FEAT-889.

### `packages/ai-parrot/tests/memory/agent_memory/test_facade.py` (CREATE)

```python
"""Behavioral acceptance tests for AgentMemoryMixin and lazy brain service boundary."""
import pytest

def test_configure_repeat_and_changed_app() -> None:
    """Verify configure repeat and changed app."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_lazy_missing_brain_and_public_service() -> None:
    """Verify lazy missing brain and public service."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_stop_drain_before_host_cleanup() -> None:
    """Verify stop drain before host cleanup."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Cooperative configuration respects the host's real rebind guard, and lazy brain construction avoids a circular dependency on FEAT-889.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` — Cooperative configuration, memory hooks and shutdown; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` — Export the new facade without importing brain/storage eagerly; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py` — Injected sibling fake on real Agent and no-brain imports; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_facade.py` — Cooperative configure/reconfigure and shutdown; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC07: repeated configure skips duplicate toolkit/service registration, changed app triggers needed rebinding, and partial initialization unwinds.
- [ ] AC15/R1–R10: one public brain_service with start/stop/search/forget_derived only; disabled brain imports no missing service; unavailable enabled service reports invalid_configuration.
- [ ] AC07/AC15: stop/drain precede host resource cleanup; no direct brain stores/runners or agent-side BrainAdminToolkit. This task tests a cooperative facade host; the dependent lifecycle task moves the boundary test onto real Agent.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_brain_contract.py packages/ai-parrot/tests/memory/agent_memory/test_facade.py -q`

## Test Specification

- `configure_repeat_and_changed_app`: AC07: repeated configure skips duplicate toolkit/service registration, changed app triggers needed rebinding, and partial initialization unwinds.
- `lazy_missing_brain_and_public_service`: AC15/R1–R10: one public brain_service with start/stop/search/forget_derived only; disabled brain imports no missing service; unavailable enabled service reports invalid_configuration.
- `stop_drain_before_host_cleanup`: AC07/AC15: stop/drain precede host resource cleanup; no direct brain stores/runners or agent-side BrainAdminToolkit. This task tests a cooperative facade host; the dependent lifecycle task moves the boundary test onto real Agent.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.
