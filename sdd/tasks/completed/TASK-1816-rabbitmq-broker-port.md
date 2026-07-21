# TASK-1816: Port RabbitMQ broker (navconfig DSN desacople)

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1814
**Assigned-to**: unassigned

> **Repo**: `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`).
> Source: `/home/jesuslara/proyectos/navigator/navigator/brokers/rabbitmq/`.

---

## Context

Spec §3 Module 4. Ports `rabbitmq/{connection,consumer,producer}.py`
(385+142+42 LOC) with the DSN read moved from `navigator.conf.rabbitmq_dsn` to a
local navconfig build, plus the ValidationError and json_encoder/decoder
replacements.

---

## Scope

- Create `src/navigator_eventbus/brokers/rabbitmq/__init__.py` re-exporting
  `RabbitMQConnection`, `RMQConsumer`, `RMQProducer`.
- Create `rabbitmq/connection.py` — port `RabbitMQConnection`:
  - Build `rabbitmq_dsn` locally from navconfig
    (`RABBITMQ_HOST/PORT/USER/PASS/VHOST`) in `brokers/_conf.py` (extend it),
    replacing `from ...conf import rabbitmq_dsn`.
  - Replace `navigator.exceptions.ValidationError` with local `Exception`
    handling + warning log.
  - Replace `datamodel.parsers.json.json_encoder/json_decoder` with
    `navigator_eventbus.serialization.dumps/loads`.
- Create `rabbitmq/consumer.py` — port `RMQConsumer` (near-verbatim).
- Create `rabbitmq/producer.py` — port `RMQProducer` (inherits fix #3 from TASK-1814).
- `aiormq` must be lazy-guarded OR documented as required only when the
  `[rabbitmq]` extra is installed — the top-level
  `navigator_eventbus.brokers` package must import fine without aiormq
  (only `brokers.rabbitmq.*` requires it).
- Tests: `tests/brokers/test_rabbitmq.py` (DSN from navconfig, constructor MRO,
  no navigator imports) with `aiormq` mocked.

**NOT in scope**: redis/sqs ports; hooks; extras in pyproject (TASK-1818);
live-RabbitMQ integration tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/brokers/rabbitmq/__init__.py` | CREATE | Re-exports |
| `src/navigator_eventbus/brokers/rabbitmq/connection.py` | CREATE | `RabbitMQConnection` |
| `src/navigator_eventbus/brokers/rabbitmq/consumer.py` | CREATE | `RMQConsumer` |
| `src/navigator_eventbus/brokers/rabbitmq/producer.py` | CREATE | `RMQProducer` |
| `src/navigator_eventbus/brokers/_conf.py` | MODIFY | Add RABBITMQ_* + dsn builder |
| `tests/brokers/test_rabbitmq.py` | CREATE | Unit tests (aiormq mocked) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-18.

### Verified Imports

```python
# Keep:
import aiormq                                          # navigator/brokers/rabbitmq/connection.py:8
from aiormq.abc import AbstractConnection, AbstractChannel  # :9
from datamodel import BaseModel                        # :10

# REPLACE during port:
# from datamodel.parsers.json import json_encoder, json_decoder  # :11
# from navigator.exceptions import ValidationError               # :12
# from ...conf import rabbitmq_dsn                               # :13

# New internal:
from ..connection import BaseConnection
from ..wrapper import BaseWrapper
from navigator_eventbus.serialization import dumps, loads
```

### Existing Signatures to Use (source: navigator repo)

```python
# navigator/brokers/rabbitmq/connection.py:17
class RabbitMQConnection(BaseConnection):
    def __init__(self, credentials: Union[str, dict] = None,
                 timeout: Optional[int] = 5, **kwargs)

# navigator/brokers/rabbitmq/consumer.py:19  ← NOTE real name: RMQConsumer
class RMQConsumer(RabbitMQConnection, BrokerConsumer):
    def __init__(...)   # :27

# navigator/brokers/rabbitmq/producer.py:15  ← NOTE real name: RMQProducer
class RMQProducer(BrokerProducer, RabbitMQConnection):
    def __init__(...)   # :28

# navigator/brokers/rabbitmq/__init__.py (exports to preserve):
from .connection import RabbitMQConnection
from .consumer import RMQConsumer
from .producer import RMQProducer

# navigator/conf.py:220-226 — values to localize in brokers/_conf.py:
RABBITMQ_HOST = config.get("RABBITMQ_HOST", fallback="localhost")
RABBITMQ_PORT = config.get("RABBITMQ_PORT", fallback=5672)
RABBITMQ_USER = config.get("RABBITMQ_USER", fallback="guest")
RABBITMQ_PASS = config.get("RABBITMQ_PASS", fallback="guest")
RABBITMQ_VHOST = config.get("RABBITMQ_VHOST", fallback="navigator")
rabbitmq_dsn = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/{RABBITMQ_VHOST}"
```

### Does NOT Exist

- ~~`RabbitMQConsumer` / `RabbitMQProducer`~~ — the spec's component diagram
  uses these names loosely, but the REAL class names are `RMQConsumer` and
  `RMQProducer`. Preserve the real names (non-goal: no public API breaks).
- ~~`navigator_eventbus.brokers.rabbitmq`~~ — created by THIS task.
- ~~`aio_pika`~~ — the implementation uses `aiormq`, not aio-pika.

---

## Implementation Notes

### Key Constraints

- `RMQProducer(BrokerProducer, RabbitMQConnection)` has the REVERSED MRO vs the
  redis/sqs producers — port the bases exactly as in the source.
- Module import of `brokers/rabbitmq` may import aiormq at top (matching the
  source); just ensure `navigator_eventbus.brokers` (top-level `__init__`) does
  NOT import the rabbitmq subpackage eagerly.
- async/await throughout; `self.logger`; Google-style docstrings + typing.

### References in Codebase

- `navigator/brokers/rabbitmq/*.py` (navigator repo) — sources; read IN FULL.
- TASK-1815's `_conf.py` pattern for the navconfig reads.

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection, RMQConsumer, RMQProducer` works (with aiormq installed).
- [ ] DSN is built from navconfig vars — no `navigator.conf` reference
  (`test_rabbitmq_connection_dsn_navconfig`).
- [ ] No `navigator.*` imports in `src/navigator_eventbus/brokers/rabbitmq/`.
- [ ] `import navigator_eventbus.brokers` succeeds WITHOUT aiormq installed.
- [ ] All tests pass: `pytest tests/brokers/test_rabbitmq.py -v`
- [ ] `ruff check src/navigator_eventbus/brokers/rabbitmq/` passes.

---

## Test Specification

```python
# tests/brokers/test_rabbitmq.py
import pytest
from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection


def test_rabbitmq_connection_dsn_navconfig(monkeypatch):
    """DSN comes from navconfig env vars, not navigator.conf."""
    monkeypatch.setenv("RABBITMQ_HOST", "mq.example.com")
    monkeypatch.setenv("RABBITMQ_USER", "svc")
    # re-evaluate dsn (function or reload, depending on _conf.py design)
    conn = RabbitMQConnection()
    assert "mq.example.com" in conn._dsn  # or however the DSN is exposed


def test_rabbitmq_no_navigator_imports():
    import navigator_eventbus.brokers.rabbitmq.connection as m
    import inspect
    src = inspect.getsource(m)
    assert "from navigator." not in src and "import navigator." not in src
```

---

## Agent Instructions

1. Read spec §3 Module 4, §7. Read the three rabbitmq source files IN FULL.
2. Check TASK-1814 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract; update index → `"in-progress"`.
4. Implement, run tests, move this file to `sdd/tasks/completed/`, index → `"done"`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-18
**Notes**: Ported `RabbitMQConnection`, `RMQConsumer`, `RMQProducer` into
`src/navigator_eventbus/brokers/rabbitmq/{connection,consumer,producer,
__init__}.py` (worktree `feat-FEAT-316-eventbus-brokers-port`, commit
`3abd563`). Extended `brokers/_conf.py` with `RABBITMQ_{HOST,PORT,USER,
PASS,VHOST}` + a locally-built `rabbitmq_dsn` (navconfig-native, replacing
`navigator.conf.rabbitmq_dsn`). Replaced `datamodel.parsers.json.
json_encoder/json_decoder` with `navigator_eventbus.serialization.dumps/
loads`; replaced the three `navigator.exceptions.ValidationError` catches in
`process_message` with generic `Exception` catches (still logging the same
warnings, same text-fallback behavior). Dropped the stray `print('DSN > ',
rabbitmq_dsn)` debug line from the source. Preserved real class names
`RMQConsumer`/`RMQProducer` (not `RabbitMQConsumer`/`RabbitMQProducer`) and
`RMQProducer`'s reversed base order (`BrokerProducer, RabbitMQConnection`)
exactly as in the source; verified both construct cleanly with the expected
MRO. `aiormq` installed locally (`uv pip install aiormq`, not added to
`pyproject.toml` — that's TASK-1818) purely to exercise the port; the
top-level `navigator_eventbus.brokers` package still imports fine with
`aiormq` blocked (verified). `pytest tests/brokers/ -v` → 20 passed, 1
skipped (msgpack, expected until TASK-1818). `ruff check` clean; `grep -rn
"navigator\." src/navigator_eventbus/brokers/rabbitmq/` (excluding
`navigator_eventbus`) empty.

**Deviations from spec**: (1) same `_conf.py`-not-in-file-table gap noted in
TASK-1815 — extended it here too, as this task's own file table directs.
(2) `.gitignore` has a global `rabbitmq/` rule (Python gitignore template's
"RabbitMQ data" section, `mnesia/`/`rabbitmq/`/`rabbitmq-data/`) that
matches our `brokers/rabbitmq/` source subpackage by directory name; used
`git add -f` to track it (same pattern as the documented `templates/`
heads-up in `docs/sdd/WORKFLOW.md` for ai-parrot) — flagging in case the
ignore pattern should be tightened. (3) `test_rabbitmq_connection_dsn_
navconfig` reloads `navigator_eventbus.brokers._conf` directly rather than
asserting via `RabbitMQConnection()._dsn` (module-level constants are
computed once at import time, matching the existing `_conf.py` pattern from
TASK-1814/1815) — permitted explicitly by the task's own test-spec comment
("function or reload, depending on `_conf.py` design").
