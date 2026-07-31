---
type: Wiki Overview
title: 'TASK-1173: Update AbstractClient `ask_stream` Return Type'
id: doc:sdd-tasks-completed-task-1173-abstract-client-type-signature-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task. The abstract `ask_stream` method in `AbstractClient`
relates_to:
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1173: Update AbstractClient `ask_stream` Return Type

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task. The abstract `ask_stream` method in `AbstractClient`
currently declares `AsyncIterator[str]` as its return type. All subsequent tasks
depend on this being updated to `AsyncIterator[Union[str, AIMessage]]` so
subclasses can yield the final `AIMessage` without type-checker complaints.

Implements: Spec §3 Module 1.

---

## Scope

- Change the return type annotation of `AbstractClient.ask_stream()` from
  `AsyncIterator[str]` to `AsyncIterator[Union[str, AIMessage]]`.
- Add the `AIMessage` import if not already present.
- Update the docstring to document the streaming contract: N-1 `str` yields
  followed by 1 final `AIMessage`.

**NOT in scope**: Modifying any concrete client implementations (separate tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Change return type on line 1337, add AIMessage import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import AsyncIterator, Union  # verified: base.py:3,7
from parrot.models import AIMessage  # verified: parrot/models/__init__.py exports AIMessage
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py:1322-1339
@abstractmethod
async def ask_stream(
    self,
    prompt: str,
    model: str = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    files: Optional[List[Union[str, Path]]] = None,
    system_prompt: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    deep_research: bool = False,
    agent_config: Optional[Dict[str, Any]] = None,
    lazy_loading: bool = False,
) -> AsyncIterator[str]:  # line 1337 — CHANGE THIS
    """Stream the model's response."""
    raise NotImplementedError("Subclasses must implement this method.")
```

### Does NOT Exist
- ~~`AbstractClient.build_stream_aimessage()`~~ — no such helper; each client builds its own
- ~~`AbstractClient.stream_response()`~~ — not a method on this class

---

## Implementation Notes

### Pattern to Follow
Simply change the return type annotation and add the import:

```python
# BEFORE (line 1337):
) -> AsyncIterator[str]:

# AFTER:
) -> AsyncIterator[Union[str, AIMessage]]:
```

### Key Constraints
- Do NOT add a default implementation — keep it abstract.
- Ensure `AIMessage` is imported at the top of `base.py` (check if it's already
  imported via `from parrot.models import ...` or add it).

---

## Acceptance Criteria

- [ ] `AbstractClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] `AIMessage` is properly imported in `base.py`
- [ ] Docstring updated to mention the streaming contract
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/base.py`

---

## Test Specification

```python
# tests/unit/test_abstract_client_type.py
import inspect
from typing import get_type_hints, Union, AsyncIterator
from parrot.clients.base import AbstractClient
from parrot.models import AIMessage


def test_ask_stream_return_type():
    """ask_stream return type includes Union[str, AIMessage]."""
    hints = get_type_hints(AbstractClient.ask_stream)
    assert hints["return"] == AsyncIterator[Union[str, AIMessage]]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/homologate-llm-clients-askstream.spec.md`
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `ask_stream` is still at line 1323 in base.py
4. **Implement** the type annotation change
5. **Verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/TASK-1173-abstract-client-type-signature.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented 2026-05-15. Changed `AbstractClient.ask_stream` return type from
`AsyncIterator[str]` to `AsyncIterator[Union[str, AIMessage]]` in
`packages/ai-parrot/src/parrot/clients/base.py`. Added `AIMessage` to the
models import block. Updated docstring to document the N-1 str + 1 AIMessage
contract. Lint passes clean.
