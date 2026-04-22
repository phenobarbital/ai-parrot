# TASK-822: ConversationBackend ABC

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-116. Introduces `ConversationBackend`, the
domain-level ABC that every storage backend (DynamoDB, SQLite, Postgres, Mongo)
will implement. Freezing this contract first is the entire reason Phase A is
sequential — all later tasks depend on it.

Implements **Module 1** of the spec (§3).

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/backends/__init__.py` (empty, just makes it a package — the factory lives here later in TASK-829).
- Create `packages/ai-parrot/src/parrot/storage/backends/base.py` defining `ConversationBackend(ABC)` with every method listed in spec §2 "New Public Interfaces".
- Include the concrete default implementation of `build_overflow_prefix()` that preserves the existing DynamoDB-compatible S3 layout (`artifacts/USER#u/AGENT#a/THREAD#s/aid`).
- All method signatures MUST match the spec verbatim — parameter names, types, defaults, return types.
- Write unit tests at `packages/ai-parrot/tests/storage/backends/test_base_abc.py` covering:
  - `ConversationBackend` cannot be instantiated directly (raises `TypeError`).
  - `ConversationBackend.__abstractmethods__` contains every abstract method expected by the spec.
  - A minimal test subclass that implements only abstract methods can be instantiated.
  - Default `build_overflow_prefix(...)` returns `"artifacts/USER#u/AGENT#a/THREAD#s/aid"` for inputs `("u", "a", "s", "aid")`.

**NOT in scope**: No concrete backend implementation. No changes to `ConversationDynamoDB`, `ChatStorage`, `ArtifactStore`, or `conf.py`. No factory. No observability hooks (TASK-831). No overflow changes (TASK-823).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/__init__.py` | CREATE | Empty package marker (factory added in TASK-829) |
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | CREATE | `ConversationBackend` ABC |
| `packages/ai-parrot/tests/storage/backends/__init__.py` | CREATE | Empty tests package marker |
| `packages/ai-parrot/tests/storage/backends/test_base_abc.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Standard library — safe to use verbatim:
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
```

### Existing Signatures to Use

The ABC must exactly mirror the public surface of `ConversationDynamoDB` PLUS the new `delete_turn` method (extracted from `chat.py:572-582` — see TASK-824 and TASK-825).

```python
# parrot/storage/dynamodb.py — current public surface that the ABC must cover:
class ConversationDynamoDB:                                                            # line 20
    DEFAULT_TTL_DAYS = 180                                                             # line 38
    async def initialize(self) -> None: ...                                            # line 59
    async def close(self) -> None: ...                                                 # line 86
    @property
    def is_connected(self) -> bool: ...                                                # line 98
    async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None: ...  # line 133
    async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None: ...     # line 177
    async def query_threads(self, user_id: str, agent_id: str, limit: int = 50) -> List[dict]: ...          # line 224
    async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None: ...  # line 262
    async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int = 10, newest_first: bool = True) -> List[dict]: ...  # line 308
    async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int: ...          # line 346
    async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None: ...  # line 406
    async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]: ...    # line 452
    async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]: ...         # line 484
    async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None: ...  # line 526
    async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int: ...       # line 553
```

### Does NOT Exist

- ~~`parrot.storage.backends`~~ — does not exist; this task creates it.
- ~~`parrot.storage.ConversationBackend`~~ — no ABC exists yet; this task creates it.
- ~~`ConversationDynamoDB.delete_turn`~~ — this method is NEW; do NOT copy it from dynamodb.py (it's added in TASK-824).
- ~~`ConversationBackend.get_item(pk, sk)`~~ — DO NOT add DynamoDB-shaped helpers. The ABC is domain-level.
- ~~A `_build_pk` or similar partition-key method on the ABC~~ — use `build_overflow_prefix` only (DynamoDB will override it in TASK-824).
- ~~Any metrics / observability decorator~~ — that is TASK-831.

---

## Implementation Notes

### Pattern to Follow

Pure ABC — no state, no constructor body beyond `pass`-like behavior if at all. Follow the simple structure already used in `parrot/interfaces/file/abstract.py:18` (`FileManagerInterface`).

### Exact Shape (from spec §2)

```python
# parrot/storage/backends/base.py
from abc import ABC, abstractmethod
from typing import List, Optional


class ConversationBackend(ABC):
    """Abstract storage backend for conversations, threads, turns, and artifacts.

    All implementations MUST preserve the semantics of the DynamoDB reference
    implementation (see backends/dynamodb.py). Verified by the shared contract
    test suite in tests/storage/test_backend_contract.py.
    """

    # Lifecycle
    @abstractmethod
    async def initialize(self) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    # Threads
    @abstractmethod
    async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None: ...
    @abstractmethod
    async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None: ...
    @abstractmethod
    async def query_threads(self, user_id: str, agent_id: str, limit: int = 50) -> List[dict]: ...

    # Turns
    @abstractmethod
    async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None: ...
    @abstractmethod
    async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int = 10, newest_first: bool = True) -> List[dict]: ...
    @abstractmethod
    async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool: ...
    @abstractmethod
    async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int: ...

    # Artifacts
    @abstractmethod
    async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None: ...
    @abstractmethod
    async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]: ...
    @abstractmethod
    async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]: ...
    @abstractmethod
    async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None: ...
    @abstractmethod
    async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int: ...

    # Concrete default — backends MAY override. DynamoDB subclass will override
    # in TASK-824 to preserve byte-identical existing S3 key layout.
    def build_overflow_prefix(
        self, user_id: str, agent_id: str, session_id: str, artifact_id: str
    ) -> str:
        """Return a stable key prefix for overflow storage."""
        return f"artifacts/USER#{user_id}#AGENT#{agent_id}/THREAD#{session_id}/{artifact_id}"
```

### Key Constraints

- Pure ABC: no `__init__`, no instance attributes.
- `build_overflow_prefix` is NOT abstract — it has a concrete default that preserves the current DynamoDB S3 layout (see spec §7 "Known Risks — S3 key prefix back-compat").
- Do not import `ConversationDynamoDB` from `base.py` — no circular deps.
- Keep Google-style docstrings on every abstract method (short — one line is fine since the semantics are identical to the DynamoDB reference).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/storage/backends/__init__.py` exists (empty).
- [ ] `packages/ai-parrot/src/parrot/storage/backends/base.py` defines `ConversationBackend(ABC)` with all 14 abstract members exactly matching the spec signatures.
- [ ] `ConversationBackend.build_overflow_prefix("u", "a", "s", "aid")` returns `"artifacts/USER#u#AGENT#a/THREAD#s/aid"`.
- [ ] `TypeError` is raised when attempting to instantiate `ConversationBackend()` directly.
- [ ] All unit tests pass: `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/backends/test_base_abc.py -v`
- [ ] `from parrot.storage.backends.base import ConversationBackend` resolves.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/backends/test_base_abc.py
import pytest

from parrot.storage.backends.base import ConversationBackend


EXPECTED_ABSTRACT_METHODS = {
    "initialize", "close", "is_connected",
    "put_thread", "update_thread", "query_threads",
    "put_turn", "query_turns", "delete_turn", "delete_thread_cascade",
    "put_artifact", "get_artifact", "query_artifacts",
    "delete_artifact", "delete_session_artifacts",
}


def test_cannot_instantiate_directly():
    with pytest.raises(TypeError):
        ConversationBackend()  # type: ignore[abstract]


def test_abstract_methods_are_complete():
    assert EXPECTED_ABSTRACT_METHODS <= set(ConversationBackend.__abstractmethods__)


def test_build_overflow_prefix_default_layout():
    # build_overflow_prefix is concrete — test on a minimal subclass
    class _Stub(ConversationBackend):
        async def initialize(self): ...
        async def close(self): ...
        @property
        def is_connected(self): return False
        async def put_thread(self, *a, **kw): ...
        async def update_thread(self, *a, **kw): ...
        async def query_threads(self, *a, **kw): return []
        async def put_turn(self, *a, **kw): ...
        async def query_turns(self, *a, **kw): return []
        async def delete_turn(self, *a, **kw): return False
        async def delete_thread_cascade(self, *a, **kw): return 0
        async def put_artifact(self, *a, **kw): ...
        async def get_artifact(self, *a, **kw): return None
        async def query_artifacts(self, *a, **kw): return []
        async def delete_artifact(self, *a, **kw): ...
        async def delete_session_artifacts(self, *a, **kw): return 0

    backend = _Stub()
    assert backend.build_overflow_prefix("u", "a", "s", "aid") == \
        "artifacts/USER#u#AGENT#a/THREAD#s/aid"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dynamodb-fallback-redis.spec.md` §2 "New Public Interfaces" for the authoritative ABC surface.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `parrot/storage/dynamodb.py:20` still looks like the signatures listed above; if it has drifted, update the contract BEFORE writing code.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the ABC, using the "Exact Shape" template.
6. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/backends/test_base_abc.py -v`
7. **Move** this file to `sdd/tasks/completed/TASK-822-conversation-backend-abc.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
