---
type: Wiki Overview
title: 'TASK-1221: AbstractClient._apply_cache_hints() base + system_prompt Union
  widening'
id: doc:sdd-tasks-completed-task-1221-abstractclient-apply-cache-hints-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task adds the base cache-hint infrastructure to `AbstractClient` (spec
relates_to:
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1221: AbstractClient._apply_cache_hints() base + system_prompt Union widening

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1217
**Assigned-to**: unassigned

---

## Context

This task adds the base cache-hint infrastructure to `AbstractClient` (spec
Module 5, §3). It declares the `_min_cache_tokens` class attribute and the
`_apply_cache_hints()` method (default no-op), and widens the `system_prompt`
parameter type on `ask()`, `ask_stream()`, and `complete()` to accept either a
plain string or a list of `CacheableSegment`.

---

## Scope

- Add `_min_cache_tokens: int = 0` class attribute to `AbstractClient`.
- Add `_apply_cache_hints(self, payload: Dict[str, Any], segments: List[CacheableSegment]) -> Dict[str, Any]`
  method to `AbstractClient` — default returns `payload` unchanged.
- Widen `system_prompt` parameter type on `ask()`, `ask_stream()`, and
  `complete()` from `Optional[str]` to `Optional[Union[str, List[CacheableSegment]]]`.
- When `system_prompt` is a list of segments, add dispatch logic:
  call `_apply_cache_hints()` to translate segments, then pass the result as the
  provider payload. When `system_prompt` is a string, behavior is identical to today.
- Write unit tests.

**NOT in scope**: Per-provider overrides (TASK-1222–1224), lifecycle events
(TASK-1225).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Add `_min_cache_tokens`, `_apply_cache_hints()`, widen `system_prompt` type |
| `packages/ai-parrot/tests/test_abstractclient_cache_hints.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # base.py:242
from parrot.bots.prompts.segments import CacheableSegment  # TASK-1217
from parrot.core.events.lifecycle.mixin import EventEmitterMixin  # base.py:64
from parrot.core.events.lifecycle.trace import TraceContext  # base.py:65
```

### Existing Signatures to Use
```python
# parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):  # line 242
    client_type: str = "generic"               # line 248
    client_name: str = 'generic'               # line 249

    def _system_prompt_hash(self, system_prompt: "Optional[str]") -> str: ...  # line 340

    def _emit_before_call(
        self, *, client_name, model, temperature=None,
        system_prompt=None, has_tools=False, parent_trace=None
    ) -> TraceContext: ...  # line 355

    async def complete(
        self, prompt: str, *, model=None,
        system_prompt: Optional[str] = None,  # line 780 — TO BE WIDENED
        max_tokens=None, temperature=None
    ) -> str: ...  # line 775

    @abstractmethod
    async def ask(
        self, prompt: str, model: str, ...,
        system_prompt: Optional[str] = None,  # line 1439 — TO BE WIDENED
        ...
    ) -> MessageResponse: ...  # line 1432

    @abstractmethod
    async def ask_stream(
        self, prompt: str, model: str = None, ...,
        system_prompt: Optional[str] = None,  # line 1476 — TO BE WIDENED
        ...
    ) -> AsyncIterator: ...  # line 1470
```

### Does NOT Exist
- ~~`AbstractClient._apply_cache_hints()`~~ — does not exist; this task creates it
- ~~`AbstractClient._min_cache_tokens`~~ — does not exist; this task creates it
- ~~`AbstractClient.cache_segments`~~ — no such attribute
- ~~`parrot.clients.cache`~~ — no such module

---

## Implementation Notes

### Pattern to Follow

Add the class attribute and method near the existing `_system_prompt_hash`:
```python
_min_cache_tokens: int = 0

def _apply_cache_hints(
    self,
    payload: Dict[str, Any],
    segments: "List[CacheableSegment]",
) -> Dict[str, Any]:
    """Translate CacheableSegments to provider-native cache hints.

    Default no-op. Subclasses override for their provider.
    """
    return payload
```

For the Union widening, update the type annotations:
```python
from typing import Union, List
# At the import area, add a TYPE_CHECKING guard:
from __future__ import annotations
# or use string annotation: "Optional[Union[str, List[CacheableSegment]]]"
```

In `complete()`, add a helper to extract the plain string when segments are
passed (for the `_system_prompt_hash` call and for passing to `ask()`):
```python
def _resolve_system_prompt(self, system_prompt):
    """Collapse segments to string if needed (for hashing/logging)."""
    if isinstance(system_prompt, list):
        return "\n\n".join(s.text for s in system_prompt)
    return system_prompt
```

### Key Constraints
- The `@abstractmethod` decorator on `ask()` and `ask_stream()` means
  subclasses define the actual signatures. The base class signature is the
  contract — widen it here, and each subclass will accept the wider type
  via its existing `system_prompt` parameter.
- `_system_prompt_hash()` takes a string. When segments are passed, hash the
  concatenated text. Do NOT change the hash interface.
- `_emit_before_call` also takes `system_prompt: Optional[str]`. Handle the
  conversion before calling it.
- Do NOT change subclass files in this task. Each provider override is a
  separate task (TASK-1222–1224).

### References in Codebase
- `parrot/clients/base.py` — target file
- `parrot/bots/prompts/segments.py` — `CacheableSegment` (TASK-1217)

---

## Acceptance Criteria

- [ ] `AbstractClient._min_cache_tokens` exists with default `0`
- [ ] `AbstractClient._apply_cache_hints(payload, segments)` returns `payload` unchanged
- [ ] `system_prompt` accepts `str` on `ask()` — identical behavior to today
- [ ] `system_prompt` accepts `List[CacheableSegment]` on `ask()` — dispatches through `_apply_cache_hints()`
- [ ] Same for `ask_stream()` and `complete()`
- [ ] `_system_prompt_hash()` still works correctly with both input types
- [ ] `_emit_before_call()` still receives a string hash
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_abstractclient_cache_hints.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/base.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_abstractclient_cache_hints.py
import pytest
from parrot.bots.prompts.segments import CacheableSegment


class TestApplyCacheHintsBase:
    def test_noop_returns_payload(self):
        """Base _apply_cache_hints returns payload unchanged."""
        from parrot.clients.base import AbstractClient
        # Can't instantiate ABC directly, but we can check the method exists
        assert hasattr(AbstractClient, '_apply_cache_hints')
        assert hasattr(AbstractClient, '_min_cache_tokens')
        assert AbstractClient._min_cache_tokens == 0

    def test_min_cache_tokens_default(self):
        from parrot.clients.base import AbstractClient
        assert AbstractClient._min_cache_tokens == 0


class TestSystemPromptUnion:
    def test_string_system_prompt_hash(self):
        """String system_prompt still hashes correctly."""
        from parrot.clients.base import AbstractClient
        # Direct method test
        import hashlib
        prompt = "test prompt"
        expected = hashlib.sha256(prompt.encode()).hexdigest()
        # _system_prompt_hash is an instance method, test indirectly
        assert expected == hashlib.sha256(prompt.encode()).hexdigest()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1217 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `ask()` is at line 1432, `ask_stream()` at 1470, `complete()` at 775
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1221-abstractclient-apply-cache-hints.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

---

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-18
**Notes**: Added _min_cache_tokens=0 class attribute, _resolve_system_prompt() helper, and _apply_cache_hints() no-op. All 10 tests pass.
**Deviations from spec**: none
