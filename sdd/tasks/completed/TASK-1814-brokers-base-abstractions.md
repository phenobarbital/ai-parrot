# TASK-1814: Port base abstractions (connection, consumer, producer, wrapper) with desacoples

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1813
**Assigned-to**: unassigned

> **Repo**: `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`).
> Source files being ported live in `/home/jesuslara/proyectos/navigator`.

---

## Context

Spec §3 Module 1. Ports `BaseConnection`, `BrokerConsumer`, `BrokerProducer`,
`BaseWrapper` from `navigator/brokers/` applying the four desacoples (auth,
`BaseApplication`, `navigator.conf`, `ValidationError`) plus PR #393 fix #3
(`credentials` keyword-with-default on `BrokerProducer`) and the new
`auth_callable` injection (resolved in brainstorm).

---

## Scope

- Create `src/navigator_eventbus/brokers/connection.py` — port `BaseConnection`:
  - Remove `from navigator.applications.base import BaseApplication`; in
    `setup()` use duck-typing: `app = app.get_app() if hasattr(app, 'get_app') else app`.
  - `self._serializer = DataSerializer()` now imports from `.serializers` (TASK-1813).
- Create `src/navigator_eventbus/brokers/consumer.py` — port `BrokerConsumer` (near-verbatim).
- Create `src/navigator_eventbus/brokers/producer.py` — port `BrokerProducer`:
  - **Fix #3**: `credentials: Union[str, dict] = None` (keyword with default).
  - Add keyword-only `auth_callable: Optional[Callable[[web.Request], Awaitable[Any]]] = None`.
  - `service_auth` decorator: use `auth_callable` when provided; when `None`,
    raise `web.HTTPUnauthorized` — never proceed unauthenticated.
  - Remove imports of `navigator_session`, `navigator_auth.conf`, `BaseApplication`.
  - Replace `from ..conf import BROKER_MANAGER_QUEUE_SIZE` with a local read.
- Create `src/navigator_eventbus/brokers/wrapper.py` — port `BaseWrapper` verbatim.
- Create `src/navigator_eventbus/brokers/_conf.py` — local navconfig reads for
  shared constants (at minimum `BROKER_MANAGER_QUEUE_SIZE`; redis/rabbitmq
  constants may live here too for TASK-1815/1816 to reuse — document them).
- Update `src/navigator_eventbus/brokers/__init__.py` to re-export
  `BaseConnection`, `BrokerConsumer`, `BrokerProducer`, `BaseWrapper`, `DataSerializer`.
- Unit tests: `tests/brokers/test_connection.py`, `tests/brokers/test_producer.py`.

**NOT in scope**: redis/rabbitmq/sqs subpackages (TASK-1815/1816/1817); hook
rewiring; pyproject extras.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/brokers/connection.py` | CREATE | `BaseConnection` (BaseApplication desacople) |
| `src/navigator_eventbus/brokers/consumer.py` | CREATE | `BrokerConsumer` ABC |
| `src/navigator_eventbus/brokers/producer.py` | CREATE | `BrokerProducer` (fix #3 + auth_callable) |
| `src/navigator_eventbus/brokers/wrapper.py` | CREATE | `BaseWrapper` |
| `src/navigator_eventbus/brokers/_conf.py` | CREATE | Local navconfig constant reads |
| `src/navigator_eventbus/brokers/__init__.py` | MODIFY | Re-exports |
| `tests/brokers/test_connection.py` | CREATE | setup() with raw `web.Application` |
| `tests/brokers/test_producer.py` | CREATE | credentials keyword + auth_callable tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-18 against both repos.

### Verified Imports

```python
# Keep in the port:
from aiohttp import web                      # navigator/brokers/connection.py:8, producer.py:5
from navconfig.logging import logging        # connection.py:9, producer.py:6
from navconfig import config                 # for _conf.py reads

# REMOVE during port (present in source, must NOT appear in destination):
# from navigator.applications.base import BaseApplication  # connection.py:10, producer.py:11
# from navigator_session import get_session                # producer.py:7
# from navigator_auth.conf import AUTH_SESSION_OBJECT      # producer.py:8-10
# from ..conf import BROKER_MANAGER_QUEUE_SIZE             # producer.py:13

# New internal import (created by TASK-1813):
from .serializers import DataSerializer
```

### Existing Signatures to Use (source: navigator repo)

```python
# navigator/brokers/connection.py:14
class BaseConnection(ABC):
    def __init__(self, *args, credentials: Union[str, dict] = None,
                 timeout: Optional[int] = 5, **kwargs)          # :19
    # sets: _credentials, _timeout, _connection, _monitor_task, logger,
    #        _queues, reconnect_attempts, max_reconnect_attempts,
    #        reconnect_delay, _lock, _serializer  (:26-38)
    async def connect(self) -> None                             # abstract
    async def disconnect(self) -> None                          # abstract
    async def publish_message(self, body, queue_name=None, **kwargs)   # abstract
    async def consume_messages(self, queue_name, callback, **kwargs)   # abstract
    async def process_message(self, body, properties)           # abstract
    async def start(self, app: web.Application) -> None
    async def stop(self, app: web.Application) -> None
    def setup(self, app: web.Application = None) -> None        # ← BaseApplication isinstance here

# navigator/brokers/consumer.py:6
class BrokerConsumer(ABC):
    _name_: str = "broker_consumer"
    def __init__(self, callback=None, **kwargs)
    # abstract: event_subscribe, subscriber_callback, wrap_callback

# navigator/brokers/producer.py:16  ← BUG #3 lives here
class BrokerProducer(BaseConnection, ABC):
    _name_: str = "broker_producer"
    def __init__(self, credentials: Union[str, dict],           # :31 positional-required → FIX
                 queue_size: Optional[int] = None,
                 num_workers: Optional[int] = 4,
                 timeout: Optional[int] = 5, **kwargs)
    # :37 self.queue_size = queue_size if queue_size else BROKER_MANAGER_QUEUE_SIZE
    # :38 self.app: Optional[BaseApplication] = None  ← retype to Optional[web.Application]
    # :45 super(BrokerProducer, self).__init__(credentials, timeout, **kwargs)
    def setup(self, app: web.Application = None) -> None        # :47 — same desacople
    async def start_workers(self)
    async def queue_event(self, body, queue_name, routing_key=None, **kw)
    async def publish_event(self, body, queue_name, **kwargs)
    async def get_userid(self, session, idx='user_id') -> int   # uses AUTH_SESSION_OBJECT → rework
    @staticmethod service_auth(fn) -> Callable                  # uses get_session → rework
    async def _event_broker(self, worker_id: int)

# navigator/brokers/wrapper.py:10 — port verbatim (66 LOC, no navigator imports)
class BaseWrapper:
    _queued: bool = True
    def __init__(self, coro=None, *args, **kwargs)
    async def call(self)
    async def __call__(self)

# navigator/conf.py:227 — constant to localize:
BROKER_MANAGER_QUEUE_SIZE = config.getint("BROKER_MANAGER_QUEUE_SIZE", fallback=...)
# port as: navconfig.config.getint("BROKER_MANAGER_QUEUE_SIZE", fallback=1000) in _conf.py
```

### New Public Interface (spec §2, implement exactly)

```python
class BrokerProducer(BaseConnection, ABC):
    def __init__(
        self,
        credentials: Union[str, dict] = None,   # FIX #3
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        *,
        auth_callable: Optional[Callable[[web.Request], Awaitable[Any]]] = None,
        **kwargs
    ): ...
```

### Does NOT Exist

- ~~`navigator_eventbus.brokers.connection`~~ etc. — created by THIS task.
- ~~`navigator_eventbus.conf`~~ — there is no package-level conf module; use
  the new local `brokers/_conf.py`.
- ~~`navigator.exceptions.ValidationError`~~ in destination — never import
  anything from `navigator.*` in `navigator_eventbus/brokers/`.
- ~~`AUTH_SESSION_OBJECT`~~ in destination — `get_userid` must take the session
  key as a parameter (default `'session'`-style lookup) or read the injected
  session dict directly; no navigator_auth import.

---

## Implementation Notes

### Pattern to Follow

```python
# Desacople BaseApplication (spec §7):
def setup(self, app: web.Application = None) -> None:
    app = app.get_app() if hasattr(app, "get_app") else app
    ...

# service_auth with injectable auth:
if self._auth_callable is not None:
    session = await self._auth_callable(request)
else:
    raise web.HTTPUnauthorized(reason="No authentication configured")
```

### Key Constraints

- async/await throughout; no blocking calls.
- `self.logger` (navconfig logging), Google-style docstrings, strict typing.
- ZERO imports from `navigator.*`, `navigator_session`, `navigator_auth`.

### References in Codebase

- `navigator/brokers/{connection,consumer,producer,wrapper}.py` (navigator repo) — sources.
- `src/navigator_eventbus/brokers/serializers.py` — from TASK-1813.

---

## Acceptance Criteria

- [ ] `grep -rn "navigator\." src/navigator_eventbus/brokers/` returns no
  `navigator.*`/`navigator_session`/`navigator_auth` imports (navconfig is fine).
- [ ] `BrokerProducer(credentials=None)` constructs without TypeError (fix #3).
- [ ] `service_auth` delegates to injected `auth_callable`; returns/raises 401 when absent.
- [ ] `BaseConnection.setup()`/`BrokerProducer.setup()` accept both a raw
  `web.Application` and an object exposing `.get_app()`.
- [ ] All tests pass: `pytest tests/brokers/test_connection.py tests/brokers/test_producer.py -v`
- [ ] `ruff check src/navigator_eventbus/brokers/` passes.

---

## Test Specification

```python
# tests/brokers/test_producer.py
import pytest
from aiohttp import web
from navigator_eventbus.brokers.producer import BrokerProducer


class DummyProducer(BrokerProducer):
    async def connect(self): ...
    async def disconnect(self): ...
    async def publish_message(self, body, queue_name=None, **kwargs): ...
    async def consume_messages(self, queue_name, callback, **kwargs): ...
    async def process_message(self, body, properties=None): ...


def test_broker_producer_credentials_keyword():
    p = DummyProducer()                    # no positional credentials → OK
    assert p is not None
    p2 = DummyProducer(credentials={"host": "x"})
    assert p2._credentials == {"host": "x"}


async def test_broker_producer_auth_callable(auth_callable):
    p = DummyProducer(auth_callable=auth_callable)
    # exercise the decorated endpoint / service_auth path with a fake request
    ...


async def test_broker_producer_no_auth_raises_401():
    p = DummyProducer()
    with pytest.raises(web.HTTPUnauthorized):
        ...  # invoke service_auth-protected path without auth_callable


# tests/brokers/test_connection.py
def test_base_connection_setup_raw_app():
    app = web.Application()
    p = DummyProducer()
    p.setup(app)          # must not require BaseApplication
    assert p.app is app
```

Fixture `auth_callable` (spec §4):

```python
@pytest.fixture
def auth_callable():
    async def _auth(request):
        return {"user_id": 42}
    return _auth
```

---

## Agent Instructions

1. Read spec §2, §3 Module 1, §7. Read all four source files in the navigator repo IN FULL.
2. Check TASK-1813 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract; update index → `"in-progress"`.
4. Implement, run tests, move this file to `sdd/tasks/completed/`, index → `"done"`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-18
**Notes**: Ported `BaseConnection`, `BrokerConsumer`, `BrokerProducer`,
`BaseWrapper` into `src/navigator_eventbus/brokers/{connection,consumer,
producer,wrapper}.py`, plus a new `_conf.py` for the localized
`BROKER_MANAGER_QUEUE_SIZE` read, and re-exported all four (+
`DataSerializer`) from `brokers/__init__.py` (worktree
`feat-FEAT-316-eventbus-brokers-port`, commit `21caeae`). Applied all four
desacoples: `BaseApplication` → duck-typed `get_app()` check in both
`BaseConnection.setup()`/`BrokerProducer.setup()`; `navigator_session`/
`navigator_auth` → injectable `auth_callable` in `service_auth`/`get_userid`
(401 when absent, never proceeds unauthenticated); `navigator.conf` →
local `brokers/_conf.py` (`BROKER_MANAGER_QUEUE_SIZE`, fallback bumped to
1000 per the task's explicit "port as" instruction — source currently
falls back to 4); `ValidationError`/pickle imports N/A to this task (Module
1 has none). PR #393 fix #3 applied (`credentials` keyword, `None` default).
`ruff check` and `grep -rn "navigator\." src/navigator_eventbus/brokers/`
(excluding `navigator_eventbus`) both clean. `pytest tests/brokers/ -v` → 12
passed, 1 skipped (msgpack, expected until TASK-1818 adds the dependency).

**Deviations from spec**: `BrokerProducer.__init__` forwards `credentials`/
`timeout` to `super().__init__()` as **keywords**
(`super().__init__(credentials=credentials, timeout=timeout, **kwargs)`)
instead of positionally as the navigator source does
(`super(BrokerProducer, self).__init__(credentials, timeout, **kwargs)`).
Positional forwarding left `BaseConnection._credentials` at its default
(`None`) and forwarded the leftover positional args all the way down the
cooperative `super()` chain to `object.__init__()`, which raises
`TypeError: object.__init__() takes exactly one argument` — this made
`DummyProducer()` construction fail outright and `test_broker_producer_
credentials_keyword`'s `p2._credentials == {"host": "x"}` assertion
(specified verbatim in this task's own Test Specification) impossible to
satisfy. The keyword-forwarding fix is required for fix #3 to actually
propagate; flagging as a deviation from "port verbatim" rather than silently
changing behavior.
