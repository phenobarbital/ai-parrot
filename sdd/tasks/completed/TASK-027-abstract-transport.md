# TASK-027: AbstractTransport Interface

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

Per owner decision (spec Open Question 7.2), an `AbstractTransport` interface should be created now, provided it doesn't break existing transports. This defines the common interface that `FilesystemTransport` (and future `TelegramCrewTransport`) will implement: `send`, `broadcast`, `messages`, `list_agents`, `reserve`, `release`, `set_status`.

This task creates the abstract base class that `FilesystemTransport` (TASK-033) will inherit from.

---

## Scope

- Define `AbstractTransport` as an ABC with the public interface from the spec
- Define method signatures with type hints and docstrings
- Include lifecycle methods: `start()`, `stop()`, `__aenter__`, `__aexit__`
- Write tests verifying the interface contract (e.g., can't instantiate directly, subclass must implement abstract methods)

**NOT in scope**: Concrete implementation (that's TASK-033), modifying existing transports

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/base.py` | CREATE | `AbstractTransport` ABC |
| `tests/transport/test_abstract_transport.py` | CREATE | Interface contract tests |

---

## Implementation Notes

### Pattern to Follow
```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List, Optional

class AbstractTransport(ABC):
    """Abstract base for all multi-agent transports.

    Concrete implementations: FilesystemTransport, TelegramCrewTransport.
    """

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, to: str, content: str, ...) -> str: ...

    @abstractmethod
    async def broadcast(self, content: str, channel: str = "general", ...) -> None: ...

    @abstractmethod
    async def messages(self) -> AsyncGenerator[Dict, None]: ...

    @abstractmethod
    async def list_agents(self) -> List[Dict]: ...

    @abstractmethod
    async def reserve(self, paths: List[str], reason: str = "") -> bool: ...

    @abstractmethod
    async def release(self, paths: Optional[List[str]] = None) -> None: ...

    @abstractmethod
    async def set_status(self, status: str, message: str = "") -> None: ...
```

### Key Constraints
- Must NOT break any existing code — this is a new file
- Keep the interface minimal: only the methods defined in the spec's public interface
- Use type hints throughout
- Include `__aenter__` / `__aexit__` as concrete methods that call `start()` / `stop()`
- Do NOT add `channel_messages()` or `whois()` to the abstract — these can be optional

### References in Codebase
- `parrot/autonomous/hooks/base.py` — `BaseHook` ABC pattern
- Spec Section 2 "New Public Interfaces" for method signatures

---

## Acceptance Criteria

- [ ] `AbstractTransport` cannot be instantiated directly (ABC)
- [ ] All abstract methods match the spec's public interface
- [ ] `__aenter__` / `__aexit__` are concrete and call `start()` / `stop()`
- [ ] Type hints are complete and correct
- [ ] Tests pass: `pytest tests/transport/test_abstract_transport.py -v`
- [ ] Import works: `from parrot.transport.base import AbstractTransport`
- [ ] No existing code is modified or broken

---

## Test Specification

```python
# tests/transport/test_abstract_transport.py
import pytest
from parrot.transport.base import AbstractTransport


class TestAbstractTransport:
    def test_cannot_instantiate(self):
        """AbstractTransport cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractTransport()

    def test_requires_all_abstract_methods(self):
        """Subclass missing methods raises TypeError."""
        class Incomplete(AbstractTransport):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    @pytest.mark.asyncio
    async def test_context_manager_calls_lifecycle(self):
        """__aenter__/__aexit__ call start/stop."""
        class MockTransport(AbstractTransport):
            started = False
            stopped = False
            async def start(self): self.started = True
            async def stop(self): self.stopped = True
            async def send(self, *a, **kw): return ""
            async def broadcast(self, *a, **kw): pass
            async def messages(self): yield {}
            async def list_agents(self): return []
            async def reserve(self, *a, **kw): return True
            async def release(self, *a, **kw): pass
            async def set_status(self, *a, **kw): pass

        t = MockTransport()
        async with t:
            assert t.started
        assert t.stopped
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-027-abstract-transport.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `AbstractTransport` ABC with 9 abstract methods (`start`, `stop`, `send`, `broadcast`, `messages`, `list_agents`, `reserve`, `release`, `set_status`) plus concrete `__aenter__`/`__aexit__` that delegate to `start()`/`stop()`. All methods have full type hints and Google-style docstrings. 6 tests pass including lifecycle, exception safety, and partial-implementation rejection.

**Deviations from spec**: none
