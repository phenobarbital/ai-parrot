# TASK-5666: User knowledge models and bounded extraction

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5653
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes MemoryEvent and trusted MemoryRequestScope contract from TASK-5653

## Context

Implement the bounded U1 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Lightweight user knowledge package (`packages/ai-parrot/src/parrot/memory/user/__init__.py`).
- Knowledge, candidate, command and receipt models (`packages/ai-parrot/src/parrot/memory/user/models.py`).
- AbstractClient-based proposal extraction (`packages/ai-parrot/src/parrot/memory/user/extraction.py`).
- Schema, provenance and temporal extraction bounds (`packages/ai-parrot/tests/memory/user/test_extraction.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/user/__init__.py` | CREATE | Lightweight user knowledge package |
| `packages/ai-parrot/src/parrot/memory/user/models.py` | CREATE | Knowledge, candidate, command and receipt models |
| `packages/ai-parrot/src/parrot/memory/user/extraction.py` | CREATE | AbstractClient-based proposal extraction |
| `packages/ai-parrot/tests/memory/user/test_extraction.py` | CREATE | Schema, provenance and temporal extraction bounds |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import UserKnowledgeCandidate
from __future__ import annotations
from datetime import datetime
from parrot.clients.base import AbstractClient
from parrot.memory.agent_memory.models import MemoryEvent
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/clients/base.py`: 297:class AbstractClient(EventEmitterMixin, ABC):
- `packages/ai-parrot/src/parrot/clients/base.py:1952` — `AbstractClient.ask`: `async def ask(self, prompt: str, model: str, max_tokens: Optional[int]=None, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, history: Optional[Sequence[HistoryMessage]]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, deep_research: bool=False, background: bool=False, lazy_loading: bool=False) -> MessageResponse:`

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/user/__init__.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/src/parrot/memory/user/models.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/src/parrot/memory/user/extraction.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/user/test_extraction.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/user/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/user/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/user/extraction.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/user/test_extraction.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient.ask"
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

### `packages/ai-parrot/src/parrot/memory/user/__init__.py` (CREATE)

```python
"""Independent cross-session user knowledge; no episodic store is required."""
```

**Why:** Extraction proposes bounded claims, while a separately trusted scope prevents prompt content from selecting another user's profile.

### `packages/ai-parrot/src/parrot/memory/user/models.py` (CREATE)

```python
"""Cross-session user knowledge, candidates, commands and durable receipts."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class UserKnowledge(BaseModel):
    """A scoped fact with independent provenance, revision and validity."""
    model_config = ConfigDict(extra="forbid")
    knowledge_id: str
    tenant_id: str
    agent_id: str
    user_id: str
    kind: Literal["fact", "preference", "goal", "constraint"]
    normalized_key: str | None = None
    value: Any
    context: dict[str, str] = Field(default_factory=dict)
    provenance: Literal["explicit", "inferred"]
    evidence_refs: tuple[str, ...] = ()
    status: Literal["active", "pending", "superseded", "invalidated"]
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    revision: int = Field(ge=0)
    supersedes_id: str | None = None
    # FILL IN: bounded validated values/keys, aware UTC and context consistency — AC06/Q1.

class UserKnowledgeCandidate(BaseModel):
    """A bounded extraction proposal; it cannot choose its trusted principal."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["fact", "preference", "goal", "constraint"]
    value: Any
    provenance: Literal["explicit", "inferred"]
    evidence_refs: tuple[str, ...]
    context: dict[str, str] = Field(default_factory=dict)
    # FILL IN: normalized key and temporal bounds — AC06; temporary statements are not eternal.

class UserKnowledgeCommand(BaseModel):
    """Idempotent revision-checked operation applied under a separate trusted scope."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    knowledge_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    candidate: UserKnowledgeCandidate | None = None
    # FILL IN: operation/evidence constraints for correct/forget — AC06/Q2.

class UserMemoryReceipt(BaseModel):
    """Acknowledge only committed changes; duplicate/conflict retain their identities."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    knowledge_id: str | None = None
    revision: int | None = None
    status: Literal["applied", "duplicate", "conflict", "ignored", "storage_unavailable"]
```

**Why:** Extraction proposes bounded claims, while a separately trusted scope prevents prompt content from selecting another user's profile.

### `packages/ai-parrot/src/parrot/memory/user/extraction.py` (CREATE)

```python
"""Extract bounded user claims without selecting scope or persisting them."""
from parrot.clients.base import AbstractClient
from parrot.memory.agent_memory.models import MemoryEvent
from .models import UserKnowledgeCandidate

async def extract_user_knowledge(event: MemoryEvent, *, client: AbstractClient) -> list[UserKnowledgeCandidate]:
    """Propose claims from user evidence; inference is pending until explicitly confirmed."""
    # FILL IN: bounded client call, schema validation and temporal/provenance admission — AC06/Q1.
    # Partial assistant streams and forged principal instructions cannot create learned facts.
    raise NotImplementedError
```

**Why:** Extraction proposes bounded claims, while a separately trusted scope prevents prompt content from selecting another user's profile.

### `packages/ai-parrot/tests/memory/user/test_extraction.py` (CREATE)

```python
"""Behavioral acceptance tests for User knowledge models and bounded extraction."""
import pytest

def test_explicit_vs_inferred_and_temporary() -> None:
    """Verify explicit vs inferred and temporary."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_candidate_cannot_override_principal() -> None:
    """Verify candidate cannot override principal."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_malformed_or_oversized_extraction() -> None:
    """Verify malformed or oversized extraction."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Extraction proposes bounded claims, while a separately trusted scope prevents prompt content from selecting another user's profile.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/user/__init__.py` — Lightweight user knowledge package; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/user/models.py` — Knowledge, candidate, command and receipt models; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/user/extraction.py` — AbstractClient-based proposal extraction; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/user/test_extraction.py` — Schema, provenance and temporal extraction bounds; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC06/Q1: explicit declarations may become active, inference remains pending; temporary/project-specific statements preserve context and validity.
- [ ] AC05: extraction cannot set tenant/agent/user or bypass missing identity; use AbstractClient and never a provider SDK.
- [ ] AC06: commands carry event ID and expected revision; values/evidence payloads are bounded and UTC timestamps validated.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/user/test_extraction.py -q`

## Test Specification

- `explicit_vs_inferred_and_temporary`: AC06/Q1: explicit declarations may become active, inference remains pending; temporary/project-specific statements preserve context and validity.
- `candidate_cannot_override_principal`: AC05: extraction cannot set tenant/agent/user or bypass missing identity; use AbstractClient and never a provider SDK.
- `malformed_or_oversized_extraction`: AC06: commands carry event ID and expected revision; values/evidence payloads are bounded and UTC timestamps validated.

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
