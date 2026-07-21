---
type: Wiki Overview
title: 'TASK-1417: Sandbox ABCs + `NoopSandbox` (`parrot/eval/sandbox/base.py`)'
id: doc:sdd-tasks-completed-task-1417-sandbox-abcs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Defines the execution-environment contract used by every rollout and the
  runner. Implements spec §3
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.models
  rel: mentions
- concept: mod:parrot.eval.sandbox.base
  rel: mentions
---

# TASK-1417: Sandbox ABCs + `NoopSandbox` (`parrot/eval/sandbox/base.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 3
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1415
**Assigned-to**: unassigned

---

## Context

Defines the execution-environment contract used by every rollout and the runner. Implements spec §3
Module 3 and the `SandboxSpec`/`Sandbox`/`SandboxProvider`/`AgentFactory` interfaces from §2. Also
provides `NoopSandbox` (no world state — conversational/RAG path) so the runner has a default.

---

## Scope

- Create `parrot/eval/sandbox/__init__.py` and `parrot/eval/sandbox/base.py`.
- Implement `SandboxSpec` (Pydantic, per §2), `ExecResult` (small Pydantic model: `exit_code`,
  `stdout`, `stderr`), the `Sandbox` ABC, the `SandboxProvider` ABC, and the `AgentFactory` type
  alias `Callable[["Sandbox"], Awaitable["AbstractBot"]]`.
- `Sandbox.exec()` default raises `NotImplementedError`.
- Implement `NoopSandbox` + `NoopSandboxProvider` (reset/snapshot/health_check are trivial;
  `snapshot()` returns `{}`).
- Resolve `EvalTask.sandbox_spec` forward ref (call `EvalTask.model_rebuild()` once `SandboxSpec` is
  importable, e.g. from `parrot/eval/__init__.py`).
- Export the names from `parrot/eval/__init__.py`.

**NOT in scope**: `InMemoryStateSandbox`, `StateBackend`, binders (TASK-1418/1419/1420),
`DockerSandbox` (out of scope for the whole feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/sandbox/__init__.py` | CREATE | Subpackage init |
| `packages/ai-parrot/src/parrot/eval/sandbox/base.py` | CREATE | ABCs + NoopSandbox |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export sandbox names + `model_rebuild()` |
| `packages/ai-parrot/tests/eval/test_sandbox_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable
from pydantic import BaseModel, Field
from typing import Any, Literal
from parrot.eval.models import EvalTask   # from TASK-1415
# Type-only (avoid runtime cycle):
# from parrot.bots.abstract import AbstractBot   # bots/abstract.py:155 — use under TYPE_CHECKING
```

### Existing Signatures to Use
```python
# bots/abstract.py:155
class AbstractBot(...): ...   # only referenced in the AgentFactory type alias
```

### Does NOT Exist
- ~~`DockerSandbox`~~ — not implemented in this feature (Non-Goal).
- ~~`StateBackend` / `InMemoryStateSandbox`~~ — created in TASK-1418/1419.

---

## Implementation Notes

### Pattern to Follow
Use `async def __aenter__/__aexit__` so sandboxes are usable as async context managers (spec §2).
`AgentFactory = Callable[["Sandbox"], Awaitable["AbstractBot"]]` — import `AbstractBot` under
`TYPE_CHECKING` to avoid a runtime import cycle.

### Key Constraints
- Async throughout; ABCs use `@abstractmethod`.
- `NoopSandbox.health_check()` returns `True`; `snapshot()` returns `{}`.

---

## Acceptance Criteria

- [ ] `from parrot.eval import Sandbox, SandboxSpec, SandboxProvider, NoopSandbox, AgentFactory` resolves.
- [ ] `EvalTask(..., sandbox_spec=SandboxSpec(kind="noop"))` validates (forward ref resolved).
- [ ] `NoopSandbox` works as an async context manager; `exec()` raises `NotImplementedError`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_sandbox_base.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/sandbox/`

---

## Test Specification

```python
import pytest
from parrot.eval import SandboxSpec, NoopSandbox
from parrot.eval.sandbox.base import NoopSandboxProvider

async def test_noop_sandbox_lifecycle():
    prov = NoopSandboxProvider()
    sb = await prov.acquire(SandboxSpec(kind="noop"))
    async with sb:
        await sb.reset(None)
        assert await sb.health_check() is True
        assert await sb.snapshot() == {}
        with pytest.raises(NotImplementedError):
            await sb.exec(["echo", "hi"])
    await prov.release(sb)
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
