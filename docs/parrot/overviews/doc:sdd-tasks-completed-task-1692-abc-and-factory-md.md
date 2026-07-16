---
type: Wiki Overview
title: 'TASK-1692: AbstractCodeReviewDispatcher ABC + Factory'
id: doc:sdd-tasks-completed-task-1692-abc-and-factory-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from abc import ABC, abstractmethod # stdlib'
relates_to:
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
---

# TASK-1692: AbstractCodeReviewDispatcher ABC + Factory

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec — the foundational abstract base
> class and factory that all concrete code review dispatchers will inherit from.
> Every other task in this feature depends on this one.

---

## Scope

- Create a new module `parrot/flows/dev_loop/code_review.py`.
- Implement `AbstractCodeReviewDispatcher` as an ABC with:
  - `agent_name: str` class attribute
  - `async review(*, brief, run_id, node_id, cwd) -> CodeReviewVerdict` abstract method
  - `build_review_profile() -> BaseModel` abstract method
- Implement `CodeReviewDispatcherFactory` with:
  - `_registry: dict[str, Type[AbstractCodeReviewDispatcher]]` class-level dict
  - `@classmethod register(cls, name)` decorator
  - `@classmethod create(cls, name, **kwargs) -> AbstractCodeReviewDispatcher`
  - `ValueError` on unknown name with available dispatchers listed
- Write unit tests for the factory (register, create, unknown raises).

**NOT in scope**: Concrete dispatcher implementations (Tasks 1694–1696), model definitions (Task 1693), QANode modifications (Task 1697).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | CREATE | ABC + factory |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | CREATE | Unit tests for ABC + factory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod                              # stdlib
from typing import Type, Dict                                    # stdlib
from pydantic import BaseModel                                   # pydantic
from parrot.flows.dev_loop.dispatcher import DevLoopCodeDispatcher  # dispatcher.py:124
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:124
class DevLoopCodeDispatcher(Protocol):
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str, node_id: str,
                       cwd: str) -> T: ...
```

### Does NOT Exist
- ~~`AbstractCodeReviewDispatcher`~~ — this task creates it
- ~~`CodeReviewDispatcherFactory`~~ — this task creates it
- ~~`parrot.flows.dev_loop.code_review`~~ — module does not exist yet
- ~~`CodeReviewVerdict`~~ — created in TASK-1693, not this task

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the register_dev_loop_node decorator pattern from nodes/base.py:133
def register_dev_loop_node(name: str):
    def _decorator(cls):
        if name in NODE_REGISTRY:
            return cls
        return register_node(name)(cls)
    return _decorator

# The factory's @register decorator should follow a similar pattern
```

### Key Constraints
- Use `abc.ABC` + `@abstractmethod` (NOT `typing.Protocol`)
- The `review()` method signature must use keyword-only args (`*`)
- Factory must fail fast with `ValueError` on unknown names — no silent fallback
- The ABC does NOT import `CodeReviewVerdict` at definition time (it will be
  defined in models.py by TASK-1693); use a forward reference or `BaseModel` return type
  and let concrete implementations narrow it. Alternatively, if TASK-1693 is
  done first, import directly.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py:133` — `register_dev_loop_node` decorator pattern
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:124` — `DevLoopCodeDispatcher` Protocol (the development-side contract this mirrors)

---

## Acceptance Criteria

- [ ] `AbstractCodeReviewDispatcher` is an ABC with `review()` and `build_review_profile()` abstract methods
- [ ] `CodeReviewDispatcherFactory.register("name")` decorator registers a class
- [ ] `CodeReviewDispatcherFactory.create("name")` returns the registered class instance
- [ ] `CodeReviewDispatcherFactory.create("unknown")` raises `ValueError`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_code_review.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
- [ ] Import works: `from parrot.flows.dev_loop.code_review import AbstractCodeReviewDispatcher, CodeReviewDispatcherFactory`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_code_review.py
import pytest
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)


class _DummyReviewer(AbstractCodeReviewDispatcher):
    agent_name = "dummy"

    async def review(self, *, brief, run_id, node_id, cwd):
        return None  # placeholder

    def build_review_profile(self):
        return None  # placeholder


class TestCodeReviewDispatcherFactory:
    def test_register_and_create(self):
        CodeReviewDispatcherFactory.register("dummy")(_DummyReviewer)
        instance = CodeReviewDispatcherFactory.create("dummy")
        assert isinstance(instance, _DummyReviewer)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown code review dispatcher"):
            CodeReviewDispatcherFactory.create("nonexistent")

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AbstractCodeReviewDispatcher()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `DevLoopCodeDispatcher` and `register_dev_loop_node` still exist at the listed locations
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1692-abc-and-factory.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Created `parrot/flows/dev_loop/code_review.py` with `AbstractCodeReviewDispatcher`
(ABC, `agent_name` attribute + abstract `review()`/`build_review_profile()`) and
`CodeReviewDispatcherFactory` (class-level registry, `register()` decorator,
`create()` raising `ValueError` on unknown name). Per the task's own guidance,
the ABC does not import `CodeReviewVerdict` at definition time (it isn't
defined until TASK-1693) — `review()` is typed to return `BaseModel`, to be
narrowed by concrete subclasses. Added
`tests/flows/dev_loop/test_code_review.py` covering register/create, unknown
name, and ABC non-instantiation. All 3 tests pass; `ruff check` clean.

**Deviations from spec**: none
