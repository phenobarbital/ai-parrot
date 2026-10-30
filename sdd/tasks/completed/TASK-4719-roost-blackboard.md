# TASK-4719: Blackboard — versioned single-writer keys, ACLs, subscriptions; FlowContext binding (M6)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4711
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6**: agents read state, not transcript. A key-value store scoped to a conversation or
channel where each key has one writer; writes carry a version and a stale write is refused, never merged; a key
change is an `inform` to subscribers (exactly once per subscriber, gate L-S5). Resolved: `digest` is owned by the
coordinator if one exists, else by the **last agent that closed a Request**. Resolved U4: `FlowContext.shared_data`
and crews stay untouched; FlowContext only gains an optional `blackboard` binding excluded from snapshots.

---

## Scope

- Create `parrot/roost/blackboard.py` (`BlackboardKey`, `KeyACL`, `BlackboardEntry`, three errors, `WriterPolicy`, abstract `Blackboard`, `InMemoryBlackboard`).
- Add `blackboard: Optional[Any] = field(default=None, repr=False)` to `FlowContext` after `trace_context`.
- Write `tests/roost/test_blackboard.py` and a FlowContext regression test.

**NOT in scope**: the Matrix room-state backend (TASK-4727); any change to `shared_data` or `to_snapshot()` (AC-16)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/blackboard.py` | CREATE | Blackboard |
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | Optional `blackboard` field |
| `packages/ai-parrot/tests/roost/test_blackboard.py` | CREATE | Unit tests incl. FlowContext snapshot regression |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.roost.messages import AgentAddress, RoostMessage            # TASK-4711
from parrot.roost.performatives import InteractionProtocol, Performative  # TASK-4711
from parrot.bots.flows.core.context import FlowContext                  # verified: bots/flows/core/context.py:56
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                                      # line 56
    shared_data: Dict[str, Any] = field(default_factory=dict)           # line 94
    trace_context: Optional["TraceContext"] = field(default=None)       # line 112 — anchor (docstring follows on 113-119)
    def to_snapshot(self, ...) -> ContextSnapshot                       # line 287 — builds ContextSnapshot(...) field by
                                                                        # field (~334-342); a new field is NOT included

# parrot/roost/messages.py (TASK-4711)
class AgentAddress(BaseModel): name: str; carrier: CarrierKind = IN_PROCESS; endpoint: Optional[str] = None
class RoostMessage(BaseModel):
    message_id; performative; protocol; conversation_id; in_reply_to; sender: AgentAddress; receivers: list[AgentAddress]
    capability_filter: Optional[str]; content: Any; content_type: Optional[str]; body: Optional[str]; envelope: Any
    failure: Optional[FailureInfo]; permission_context: Any; auth_token: Optional[str]; created_at: datetime
    def reply(self, performative, *, content=None, body=None, failure=None) -> RoostMessage
    def is_addressed_to(self, name: str) -> bool
    def trace_id(self) -> Optional[str]
```

### Does NOT Exist
- ~~`class Blackboard` anywhere today — 0 hits~~
- ~~`FlowContext.blackboard` — created here~~
- ~~`SetContextAction` writing to the blackboard — out of scope; `shared_data` stays the flow store~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/blackboard.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_blackboard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/context.py#FlowContext",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/context.py#FlowContext.to_snapshot"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Insert the FlowContext field AFTER the `trace_context` docstring (line 119), not between the field and its docstring — the attribute docstring convention binds a string to the preceding field.
- `put`: `expected_version is None` ⇒ create (StaleWriteError if the key exists); else must equal the current version; version increments by 1. Writer must equal `policy.owner_of(key, ...)` (WriterDeniedError). Use an `asyncio.Lock` per key so concurrent writers serialise and exactly one lands (L-S5).
- Subscriber notification: after the write commits, build ONE `RoostMessage(performative=INFORM, protocol=SUBSCRIBE, conversation_id=subscription_id, content=entry)` per subscriber and await its callback; a failing subscriber is logged, never blocks others.
- `render_prefix`: deterministic — keys in the given order, values via `json.dumps(..., sort_keys=True, default=str)`, skip unreadable keys.
- Owners: roster/definitions → `harness`; tasks → `engine`; digest → coordinator or last Request closer (`record_request_closed`); artifacts → the `producer` argument; unknown keys → the first writer.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/core/context.py:112` — field + attribute-docstring style

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `blackboard.py`.
2. Add the FlowContext field after line 119.
3. Write tests: CAS, stale refusal, writer policy, digest ownership move, one inform per subscriber, render stability, `to_snapshot()` unchanged.

### `packages/ai-parrot/src/parrot/roost/blackboard.py` (CREATE)
```python
"""Roost blackboard — versioned single-writer keys with ACLs and subscriptions (FEAT-747 M6)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .messages import AgentAddress, RoostMessage
from .performatives import InteractionProtocol, Performative


class BlackboardKey(str, Enum):
    ROSTER = "roster"; DEFINITIONS = "definitions"; TASKS = "tasks"; DIGEST = "digest"; ARTIFACTS = "artifacts"


class KeyACL(BaseModel):
    readers: list[str] = Field(default_factory=lambda: ["*"])
    writer: str


class BlackboardEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    key: str
    value: Any
    version: int
    writer: str
    acl: KeyACL
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: dict[str, Any] = Field(default_factory=dict)


class StaleWriteError(Exception): ...
class WriterDeniedError(Exception): ...
class ReadDeniedError(Exception): ...


Subscriber = Callable[[RoostMessage], Awaitable[None]]


class WriterPolicy:
    def __init__(self, *, harness: str = "harness", engine: str = "engine", coordinator: Optional[str] = None) -> None:
        self.harness, self.engine, self.coordinator = harness, engine, coordinator
        self._last_request_closer: Optional[str] = None

    def owner_of(self, key: str, *, last_request_closer: Optional[str] = None, producer: Optional[str] = None) -> str:
        raise NotImplementedError  # FILL IN — Key Constraints, last bullet

    def record_request_closed(self, agent_name: str) -> None:
        self._last_request_closer = agent_name
```
**Why**: Models and error names are spec §3 M6 verbatim; `WriterPolicy` keeps the last closer itself so callers need not thread it.

### `packages/ai-parrot/src/parrot/roost/blackboard.py` (CREATE (continued, same file))
```python
class Blackboard(ABC):
    def __init__(self, *, scope: str, policy: WriterPolicy) -> None:
        self.logger = logging.getLogger(__name__)
        self.scope = scope
        self.policy = policy
        self._subs: dict[str, tuple[str, Subscriber, str]] = {}   # sub_id -> (key, callback, subscriber_name)

    @abstractmethod
    async def get(self, key: str, *, reader: str) -> Optional[BlackboardEntry]: ...

    @abstractmethod
    async def put(self, key: str, value: Any, *, writer: str, expected_version: Optional[int],
                  acl: Optional[KeyACL] = None, provenance: Optional[dict[str, Any]] = None,
                  producer: Optional[str] = None) -> BlackboardEntry: ...

    async def subscribe(self, key: str, subscriber: Subscriber, *, subscriber_name: str) -> str:
        sub_id = uuid.uuid4().hex
        self._subs[sub_id] = (key, subscriber, subscriber_name)
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        return self._subs.pop(subscription_id, None) is not None

    async def _notify(self, entry: BlackboardEntry) -> None:
        """Exactly one ``inform`` per subscriber of ``entry.key``."""
        raise NotImplementedError  # FILL IN — Key Constraints bullet 3

    @abstractmethod
    async def keys(self, *, reader: str) -> list[str]: ...

    def render_prefix(self, *, reader: str, keys: Sequence[str] = ("roster", "definitions", "tasks", "digest")) -> str:
        """Deterministic text rendering for prompt-cache-friendly prefixes."""
        raise NotImplementedError  # FILL IN — bullet 4 (sync: read a local cache kept by put())


class InMemoryBlackboard(Blackboard):
    def __init__(self, *, scope: str, policy: WriterPolicy) -> None:
        super().__init__(scope=scope, policy=policy)
        self._entries: dict[str, BlackboardEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # FILL IN: get / put (CAS under per-key lock, then _notify) / keys — bullet 2
```
**Why**: `put` gains a keyword-only `producer` (owner of `artifacts`) beyond the skeleton — needed because the writer of `artifacts` is whoever produced the handle; it is additive and optional. `render_prefix` is sync in the skeleton, so backends keep the last-read entries in memory.

### `packages/ai-parrot/src/parrot/bots/flows/core/context.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    trace_context: Optional\["TraceContext"\] = field(default=None)' context.py)
# AFTER — insert below the trace_context attribute docstring that ends at context.py:119 (field at :112)
    blackboard: Optional[Any] = field(default=None, repr=False)
    """Optional Roost ``Blackboard`` binding (FEAT-747). Not part of ``to_snapshot()``; ``shared_data`` is unchanged."""
```
**Why**: A plain `Any` keeps core flows free of a `parrot.roost` import; `to_snapshot()` builds its snapshot field by field, so the new field is excluded without editing it (AC-16).

### FILL IN checklist
- [ ] `WriterPolicy.owner_of`
- [ ] `_notify`
- [ ] `render_prefix`
- [ ] `InMemoryBlackboard.get/put/keys`
- [ ] tests

---

## Acceptance Criteria

- [ ] Stale `expected_version` ⇒ `StaleWriteError`; value unchanged (never merged)
- [ ] Two concurrent writers with the same expected version ⇒ exactly one lands (L-S5)
- [ ] Each accepted write delivers exactly one inform per subscriber
- [ ] `digest` owner moves to the last Request closer when no coordinator is set
- [ ] `FlowContext().blackboard is None` and `to_snapshot()` output is unchanged; existing `tests/bots/flows/core/test_context.py` green
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/blackboard.py packages/ai-parrot/src/parrot/bots/flows/core/context.py packages/ai-parrot/tests/roost/test_blackboard.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_blackboard.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/core/test_context.py -q`

---

## Test Specification

```python
import asyncio

import pytest

from parrot.roost.blackboard import InMemoryBlackboard, StaleWriteError, WriterDeniedError, WriterPolicy


@pytest.fixture
def bb():
    return InMemoryBlackboard(scope="chan", policy=WriterPolicy())


async def test_cas_and_stale(bb):
    e1 = await bb.put("roster", ["a"], writer="harness", expected_version=None)
    await bb.put("roster", ["a", "b"], writer="harness", expected_version=e1.version)
    with pytest.raises(StaleWriteError):
        await bb.put("roster", ["x"], writer="harness", expected_version=e1.version)


async def test_single_writer_concurrent_and_inform_once(bb):
    got = []
    await bb.subscribe("tasks", lambda m: asyncio.sleep(0, got.append(m)), subscriber_name="s")
    await bb.put("tasks", {}, writer="engine", expected_version=None)
    res = await asyncio.gather(bb.put("tasks", 1, writer="engine", expected_version=1),
                               bb.put("tasks", 2, writer="engine", expected_version=1), return_exceptions=True)
    assert sum(isinstance(r, StaleWriteError) for r in res) == 1 and len(got) == 2


async def test_writer_denied(bb):
    with pytest.raises(WriterDeniedError):
        await bb.put("roster", [], writer="agent-a", expected_version=None)
# FILL IN: digest ownership move, render_prefix stability, FlowContext().blackboard is None
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4719 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Blackboard + optional FlowContext.blackboard field; 10+10 tests green. Coder made one premature commit then a fix commit. Task text drift: FlowContext needs initial_task and to_snapshot needs serializer (tests use both); task file not edited.
Seat: opus (native) · Attempts: 1

**Deviations from spec**: none
