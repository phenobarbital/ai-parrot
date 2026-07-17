# TASK-1818: Rewire broker hooks to internal module + pyproject extras

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1815, TASK-1816, TASK-1817
**Assigned-to**: unassigned

> **Repo**: `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`).

---

## Context

Spec §3 Modules 6 + 7. The phase-1 hook stubs still lazy-import
`navigator.brokers.*` inside `connect()`. With the internal port complete
(TASK-1815/1816/1817), flip the three lazy-imports to
`navigator_eventbus.brokers.*` and add the packaging extras so `[brokers]`
no longer pulls the navigator framework.

---

## Scope

- Modify `src/navigator_eventbus/hooks/brokers/redis.py` — change the
  lazy-import in `connect()` to `from navigator_eventbus.brokers.redis import RedisConnection`.
  Update the module docstring (it currently documents the phase-1 "TAL CUAL" state).
- Modify `src/navigator_eventbus/hooks/brokers/rabbitmq.py` — same, to
  `from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection`.
- Modify `src/navigator_eventbus/hooks/brokers/sqs.py` — same, to
  `from navigator_eventbus.brokers.sqs import SQSConnection`.
- Modify `pyproject.toml` `[project.optional-dependencies]`:
  - `brokers = ["navigator-eventbus[redis]"]`
  - `rabbitmq = ["aiormq>=6.7"]`
  - `sqs = ["aioboto3>=12"]`
  - `pickle = ["cloudpickle>=3"]`
  - `serializer = ["cloudpickle>=3", "msgpack>=1", "jsonpickle>=3"]`
  - extend `all` to include `brokers`, `rabbitmq`, `sqs`.
- Tests: `tests/brokers/test_hook_rewire.py` — the three hooks resolve their
  connection class from `navigator_eventbus.brokers.*` (no `navigator.brokers`
  reference anywhere in the package).

**NOT in scope**: behavioral changes to the hooks (public `BaseBrokerHook`
start/stop contract is untouched — spec non-goal); the mqtt hook (uses gmqtt
directly, unaffected); version bump / release (TASK-1819).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/hooks/brokers/redis.py` | MODIFY | Rewire lazy-import (line 27) |
| `src/navigator_eventbus/hooks/brokers/rabbitmq.py` | MODIFY | Rewire lazy-import (line 31) |
| `src/navigator_eventbus/hooks/brokers/sqs.py` | MODIFY | Rewire lazy-import (line 28) |
| `pyproject.toml` | MODIFY | Add extras: brokers, rabbitmq, sqs, pickle, serializer |
| `tests/brokers/test_hook_rewire.py` | CREATE | Rewire verification tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-18 in the navigator-eventbus repo (FEAT-312 branch).

### Verified Imports / Exact Lines to Change

```python
# src/navigator_eventbus/hooks/brokers/redis.py:27 (inside connect()):
from navigator.brokers.redis import RedisConnection
#   → from navigator_eventbus.brokers.redis import RedisConnection

# src/navigator_eventbus/hooks/brokers/rabbitmq.py:31 (inside connect()):
from navigator.brokers.rabbitmq import RabbitMQConnection
#   → from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection

# src/navigator_eventbus/hooks/brokers/sqs.py:28 (inside connect()):
from navigator.brokers.sqs import SQSConnection
#   → from navigator_eventbus.brokers.sqs import SQSConnection

# Also update the stale reference in the package docstring:
# src/navigator_eventbus/hooks/brokers/__init__.py:5 mentions navigator.brokers.*
```

### Existing Signatures to Use

```python
# src/navigator_eventbus/hooks/brokers/redis.py:14
class RedisBrokerHook(BaseBrokerHook):
    hook_type = HookType.BROKER_REDIS
    def __init__(self, config: BrokerHookConfig, **kwargs) -> None
    async def connect(self) -> None        # ← the ONLY line that changes is the import
    async def disconnect(self) -> None
    async def start_consuming(self) -> None

# pyproject.toml — current [project.optional-dependencies] (verified):
#   redis, grpc, notify, scheduler, watchdog, mqtt, all, dev
#   all = ["navigator-eventbus[redis,grpc,notify,scheduler,watchdog,mqtt]"]
```

### Does NOT Exist

- ~~`pickle`, `serializer`, `brokers`, `rabbitmq`, `sqs` extras~~ — NOT in
  pyproject.toml yet (despite `serialization.py`'s docstring mentioning
  `[pickle]`); THIS task adds all five.
- ~~an mqtt broker in `navigator_eventbus.brokers`~~ — `hooks/brokers/mqtt`-style
  rewiring does not apply; leave the mqtt hook alone.
- ~~`RabbitMQConsumer`~~ — real names are `RMQConsumer`/`RMQProducer`; the hooks
  only import the `*Connection` classes anyway.

---

## Implementation Notes

- Three one-line import changes + docstring touch-ups; keep everything else
  byte-identical (spec non-goal: no public API change).
- After editing pyproject, refresh the venv:
  `source .venv/bin/activate && uv pip install -e ".[brokers,rabbitmq,sqs,serializer,dev]"`.

---

## Acceptance Criteria

- [ ] `grep -rn "navigator.brokers" src/` returns NO import statements (docstring
  mentions removed/updated too).
- [ ] `pyproject.toml` has extras `brokers`, `rabbitmq`, `sqs`, `pickle`,
  `serializer`; `all` includes brokers, rabbitmq, sqs.
- [ ] `uv pip install -e ".[brokers,rabbitmq,sqs,dev]"` succeeds.
- [ ] All tests pass: `pytest tests/brokers/test_hook_rewire.py -v`
- [ ] `ruff check src/navigator_eventbus/hooks/brokers/` passes.

---

## Test Specification

```python
# tests/brokers/test_hook_rewire.py
import inspect
import pytest
from navigator_eventbus.hooks.models import BrokerHookConfig


@pytest.fixture
def broker_config():
    return BrokerHookConfig(
        queue_name="test_stream",
        group_name="test_group",
        consumer_name="test_consumer",
    )


@pytest.mark.parametrize("mod,klass", [
    ("navigator_eventbus.hooks.brokers.redis", "RedisBrokerHook"),
    ("navigator_eventbus.hooks.brokers.rabbitmq", "RabbitMQBrokerHook"),
    ("navigator_eventbus.hooks.brokers.sqs", "SQSBrokerHook"),
])
def test_hook_rewire(mod, klass):
    """connect() sources its Connection from navigator_eventbus.brokers.*"""
    import importlib
    m = importlib.import_module(mod)
    src = inspect.getsource(getattr(m, klass).connect)
    assert "navigator_eventbus.brokers" in src
    assert "from navigator.brokers" not in src
```

---

## Agent Instructions

1. Read spec §3 Modules 6-7. Check TASK-1815/1816/1817 are in `sdd/tasks/completed/`.
2. Verify the Codebase Contract (line numbers may have shifted).
3. Update index → `"in-progress"`; implement; run tests.
4. Move this file to `sdd/tasks/completed/`, index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
