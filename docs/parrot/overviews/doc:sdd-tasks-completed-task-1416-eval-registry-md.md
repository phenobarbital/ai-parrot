---
type: Wiki Overview
title: 'TASK-1416: Eval registry (`@register_evaluator` / `@register_metric`)'
id: doc:sdd-tasks-completed-task-1416-eval-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 2. A NEW lightweight `name -> class` decorator
  registry for evaluators and
relates_to:
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.registry
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
---

# TASK-1416: Eval registry (`@register_evaluator` / `@register_metric`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1415
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. A NEW lightweight `name -> class` decorator registry for evaluators and
metrics. The existing `AgentRegistry` is bot-specific and is NOT reused (see spec §6 "Does NOT
Exist"). This task only provides the registry primitives; concrete evaluators register themselves in
later tasks.

---

## Scope

- Create `parrot/eval/registry.py` with two small registries (plain dict-backed) and their decorators:
  - `register_evaluator(name: str)` → class decorator; `get_evaluator(name)`; `list_evaluators()`.
  - `register_metric(name: str)` → class decorator; `get_metric(name)`; `list_metrics()`.
- Duplicate registration of the same name raises `ValueError`.
- Export the decorators from `parrot/eval/__init__.py`.

**NOT in scope**: any concrete evaluator/metric (TASK-1422), `AbstractEvaluator`/`Metric` ABCs
(TASK-1421). The registry stores classes by name without importing the ABCs (avoid a cycle — accept
`type` generically).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/registry.py` | CREATE | Decorator registries |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export decorators + getters |
| `packages/ai-parrot/tests/eval/test_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Reference only — DO NOT reuse this for eval (it is bot-specific):
# from parrot.registry import register_agent   # registry/__init__.py:12 → register_bot_decorator
```

### Existing Signatures to Use
```python
# parrot/registry/registry.py:1205  (reference pattern for decorator ergonomics ONLY — do not import)
def register_bot_decorator(self, *, name=None, priority=0, ...): ...
```

### Does NOT Exist
- ~~`@register_evaluator` / `@register_metric` (pre-existing)~~ — this task creates them.
- ~~A generic `AgentRegistry.register(arbitrary_type)`~~ — `AgentRegistry` only registers `AbstractBot`
  subclasses (`registry.py:1241` raises `TypeError` otherwise). Build a fresh, minimal registry.

---

## Implementation Notes

### Pattern to Follow
```python
_EVALUATORS: dict[str, type] = {}

def register_evaluator(name: str):
    def deco(cls):
        if name in _EVALUATORS:
            raise ValueError(f"evaluator '{name}' already registered")
        _EVALUATORS[name] = cls
        return cls
    return deco
```
Mirror the same shape for metrics.

### Key Constraints
- No dependency on the ABCs (keep it import-cycle-free).
- Pure, in-process dict registry; no DB.

---

## Acceptance Criteria

- [ ] `from parrot.eval import register_evaluator, register_metric` resolves.
- [ ] Registering two classes under the same name raises `ValueError`.
- [ ] `get_evaluator(name)` returns the registered class; unknown name raises `KeyError`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_registry.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/registry.py`

---

## Test Specification

```python
import pytest
from parrot.eval.registry import register_evaluator, get_evaluator

def test_register_and_resolve():
    @register_evaluator("dummy")
    class Dummy: ...
    assert get_evaluator("dummy") is Dummy

def test_duplicate_raises():
    @register_evaluator("dup")
    class A: ...
    with pytest.raises(ValueError):
        @register_evaluator("dup")
        class B: ...
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
