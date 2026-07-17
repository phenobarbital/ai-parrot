---
type: feature
base_branch: dev
---

# Feature Specification: EventBus Brokers Port

**Feature ID**: FEAT-316
**Date**: 2026-07-17
**Author**: Jesus (phenobarbital) + Claude
**Status**: draft
**Target version**: navigator-eventbus 0.1.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The hooks/brokers layer in `navigator-eventbus` (delivered by FEAT-312, phase 1) still
lazy-imports `navigator.brokers.redis.RedisConnection`,
`navigator.brokers.rabbitmq.RabbitMQConnection`, and
`navigator.brokers.sqs.SQSConnection` from the **navigator framework**. This means
any consumer installing `navigator-eventbus` for broker hooks must also install the
full `navigator` framework — defeating the purpose of the extraction.

Meanwhile, `navigator.brokers` (~2,197 LOC) carries **three open bugs** documented in
PR [navigator#393](https://github.com/phenobarbital/navigator/pull/393) (author `hacu9`):

1. **RedisConsumer kwargs TypeError** — `kwargs.get()` reads `queue_name`/`group_name`/
   `consumer_name` without removing them; `super().__init__()` re-forwards the same
   kwargs, causing a `TypeError` on duplicate arguments.
2. **Pending Entries List (PEL) starvation** — no `XCLAIM`/`XAUTOCLAIM` anywhere in the
   brokers module; unacknowledged messages stay in the PEL indefinitely, causing silent
   message loss in at-least-once workloads.
3. **BrokerProducer positional credentials** — `credentials: Union[str, dict]` is
   positional-required, breaking `RedisProducer` construction when Redis credentials
   come from config (not the caller).

Additionally, `BrokerProducer` hard-imports `navigator_session.get_session` and
`navigator_auth.conf.AUTH_SESSION_OBJECT` for its HTTP endpoint auth — coupling the
entire brokers layer to the navigator auth stack.

### Goals

- Port the complete `navigator/brokers/` tree to `navigator_eventbus.brokers` as an
  internal module of the `navigator-eventbus` package.
- Apply the three PR #393 fixes with their tests during the port.
- Decouple `BrokerProducer` from `navigator_session`/`navigator_auth` via an injectable
  `auth_callable`.
- Decouple `BaseConnection`/`BrokerProducer` from `navigator.applications.base.BaseApplication`.
- Decouple credential/DSN resolution from `navigator.conf` — use `navconfig` directly.
- Replace `navigator.exceptions.ValidationError` with a local or standard exception.
- Rewire the hooks/brokers in `navigator_eventbus.hooks.brokers/{redis,rabbitmq,sqs}.py`
  (phase 1 stubs) to import from `navigator_eventbus.brokers.*` instead of
  `navigator.brokers.*`.
- Add `[brokers]`, `[rabbitmq]`, `[sqs]` extras to `pyproject.toml`.
- Use JSON (orjson via `JSONContent`) as default serialization; `cloudpickle`/`msgpack`
  optional (extras `[pickle]`/`[serializer]`).
- Publish `0.1.0rc` (editable) at close; the extra `[brokers]` no longer depends on
  the navigator framework.

### Non-Goals (explicitly out of scope)

- **Consolidating** `brokers/redis` consumer with `RedisStreamsBackend` — decided to
  port as-is; consolidation deferred to a separate spec (`eventbus-streams-consolidation`)
  post-migration (resolved in brainstorm).
- **MQTT broker** — no MQTT implementation exists in `navigator.brokers`; the mqtt hook
  uses `gmqtt` directly and is unaffected.
- **Breaking the hooks' public API** — the hooks maintain the same `BaseBrokerHook`
  start/stop contract; only the internal import source changes.
- **Migrating ai-parrot imports** — that is phase 4 (`parrot-eventbus-migration`).
- **Removing `navigator/brokers/`** — that is phase 5 (`navigator-brokers-removal`).

---

## 2. Architectural Design

### Overview

Port `navigator.brokers` verbatim into `navigator_eventbus/brokers/`, applying the
PR #393 fixes and four desacoples (auth, BaseApplication, navigator.conf, ValidationError)
during the copy. The serialization layer switches default format to JSON via the existing
`navigator_eventbus.serialization` module (orjson-backed `JSONContent`), with
`cloudpickle`/`msgpack` available as opt-in extras.

The `auth_callable` injection pattern (resolved in brainstorm): `BrokerProducer.__init__`
accepts an optional `auth_callable: Callable[[web.Request], Awaitable[Any]] | None`
parameter. When set, `service_auth` uses it instead of hard-importing `navigator_session`.
When `None`, the endpoint is unprotected (or raises 401). Navigator passes its own
`get_session` resolver when constructing the producer.

### Component Diagram

```
navigator_eventbus/
├── brokers/                       ← NEW (this spec)
│   ├── __init__.py               # re-exports
│   ├── connection.py             # BaseConnection (desacoplado de BaseApplication)
│   ├── consumer.py               # BrokerConsumer (ABC)
│   ├── producer.py               # BrokerProducer (auth_callable injectable)
│   ├── wrapper.py                # BaseWrapper
│   ├── serializers.py            # DataSerializer (JSON default, cloudpickle/msgpack opt-in)
│   ├── redis/
│   │   ├── __init__.py
│   │   ├── connection.py         # RedisConnection (navconfig creds, XAUTOCLAIM fix)
│   │   ├── consumer.py           # RedisConsumer (kwargs.pop fix)
│   │   └── producer.py           # RedisProducer (credentials keyword fix)
│   ├── rabbitmq/
│   │   ├── __init__.py
│   │   ├── connection.py         # RabbitMQConnection (navconfig DSN)
│   │   ├── consumer.py           # RabbitMQConsumer
│   │   └── producer.py           # RMQProducer
│   └── sqs/
│       ├── __init__.py
│       ├── connection.py         # SQSConnection (navconfig creds)
│       ├── consumer.py           # SQSConsumer
│       └── producer.py           # SQSProducer
├── hooks/
│   └── brokers/
│       ├── redis.py              ← REWIRE lazy-import
│       ├── rabbitmq.py           ← REWIRE lazy-import
│       └── sqs.py                ← REWIRE lazy-import
└── (existing core, evb, backends, etc. — untouched)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator_eventbus.hooks.brokers.redis` | rewires | `from navigator.brokers.redis → from navigator_eventbus.brokers.redis` |
| `navigator_eventbus.hooks.brokers.rabbitmq` | rewires | same pattern |
| `navigator_eventbus.hooks.brokers.sqs` | rewires | same pattern |
| `navigator_eventbus.serialization` | reuses | JSON default via `JSONContent`; `DataSerializer` wraps it + optional cloudpickle/msgpack |
| `navigator_eventbus.hooks.models.BrokerHookConfig` | unchanged | config model already in package (phase 1) |
| `navigator_eventbus.hooks.base.BaseBrokerHook` | unchanged | base class already in package (phase 1) |
| `navconfig` | direct dep | replaces `navigator.conf.*` for REDIS_BROKER_*, rabbitmq_dsn, BROKER_MANAGER_QUEUE_SIZE, AWS creds |
| `aiohttp.web` | direct dep | HTTP endpoint in BrokerProducer, connection start/stop |
| `redis.asyncio` | extra `[redis]` | already a dependency for the bus backends |
| `aiormq` | extra `[rabbitmq]` | RabbitMQ connection/consumer/producer |
| `aioboto3` | extra `[sqs]` | SQS connection/consumer/producer |

### Data Models

No new Pydantic models. The port preserves existing class hierarchies:

```python
# Inheritance chains (preserved)
BaseConnection (ABC)
  ├── RedisConnection
  │     ├── RedisConsumer (+ BrokerConsumer)
  │     └── RedisProducer (+ BrokerProducer)
  ├── RabbitMQConnection
  │     ├── RabbitMQConsumer (+ BrokerConsumer)
  │     └── RMQProducer (+ BrokerProducer)
  └── SQSConnection
        ├── SQSConsumer (+ BrokerConsumer)
        └── SQSProducer (+ BrokerProducer)

BrokerConsumer (ABC) — mixin for consumer interface
BrokerProducer (BaseConnection, ABC) — mixin for producer + HTTP endpoint
BaseWrapper — coroutine wrapper with retry/queued semantics
DataSerializer — encode/decode/serialize/unserialize/pack/unpack
```

### New Public Interfaces

```python
# navigator_eventbus/brokers/producer.py — key change
class BrokerProducer(BaseConnection, ABC):
    def __init__(
        self,
        credentials: Union[str, dict] = None,  # FIX #3: keyword with default
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        *,
        auth_callable: Optional[Callable[[web.Request], Awaitable[Any]]] = None,
        **kwargs
    ): ...

# navigator_eventbus/brokers/redis/connection.py — key addition
class RedisConnection(BaseConnection):
    async def reclaim_pending_messages(
        self,
        queue_name: str,
        callback: Callable,
        *,
        min_idle_time: int = 30_000,
        count: int = 10,
    ) -> int:
        """FIX #2: XAUTOCLAIM-based redelivery of stuck PEL entries."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Base Abstractions

- **Path**: `src/navigator_eventbus/brokers/{__init__,connection,consumer,producer,wrapper}.py`
- **Responsibility**: Port `BaseConnection`, `BrokerConsumer`, `BrokerProducer`,
  `BaseWrapper` with desacoples:
  - `BaseConnection.setup()`: accept `web.Application` directly; remove
    `BaseApplication` import. Use duck-typing: if the app has `get_app()`, call it.
  - `BrokerProducer.__init__`: `credentials` becomes keyword with `default=None` (fix #3);
    `auth_callable` parameter added (keyword-only).
  - `BrokerProducer.service_auth`: use `auth_callable` if provided; otherwise return 401.
    Remove hard imports of `navigator_session`/`navigator_auth.conf`.
  - `BrokerProducer.setup()`: same `BaseApplication` desacople as `BaseConnection`.
  - `BROKER_MANAGER_QUEUE_SIZE`: read via `navconfig.config.getint("BROKER_MANAGER_QUEUE_SIZE", fallback=1000)` locally.
- **Depends on**: `navconfig`, `aiohttp`

### Module 2: Serialization (DataSerializer)

- **Path**: `src/navigator_eventbus/brokers/serializers.py`
- **Responsibility**: Port `DataSerializer` from `navigator.brokers.pickle`. Default
  format changes to JSON via `navigator_eventbus.serialization` (`JSONContent` / orjson).
  `cloudpickle` and `msgpack` lazy-imported with clear error if extras not installed.
  `jsonpickle` encode/decode preserved as opt-in. `ModelHandler` registration preserved
  for `datamodel.Model`/`BaseModel` when `jsonpickle` is available.
- **Depends on**: `navigator_eventbus.serialization`, optionally `cloudpickle`, `msgpack`, `jsonpickle`

### Module 3: Redis Broker

- **Path**: `src/navigator_eventbus/brokers/redis/{__init__,connection,consumer,producer}.py`
- **Responsibility**: Port Redis broker with all three PR #393 fixes:
  - **Fix #1** (`RedisConsumer.__init__`): use `kwargs.pop()` instead of `kwargs.get()`
    for `queue_name`, `group_name`, `consumer_name` before calling `super().__init__()`.
  - **Fix #2** (`RedisConnection.reclaim_pending_messages`): add opt-in XAUTOCLAIM-based
    PEL sweep method; callers schedule the sweep externally.
  - **Fix #3** (`RedisProducer`): inherits the keyword-default `credentials` from
    `BrokerProducer`.
  - Credentials: `REDIS_BROKER_HOST/PORT/PASSWORD/DB` read via `navconfig.config.get()`
    locally, not from `navigator.conf`.
  - Replace `from navigator.exceptions import ValidationError` with local handling
    (catch `Exception`, log warning).
  - Replace `from datamodel.parsers.json import json_encoder, json_decoder` with
    `navigator_eventbus.serialization.dumps/loads`.
- **Depends on**: Module 1, Module 2, `redis.asyncio` (extra `[redis]`)

### Module 4: RabbitMQ Broker

- **Path**: `src/navigator_eventbus/brokers/rabbitmq/{__init__,connection,consumer,producer}.py`
- **Responsibility**: Port RabbitMQ broker. Desacoples:
  - DSN: `rabbitmq_dsn` read from navconfig locally
    (`RABBITMQ_HOST/PORT/USER/PASS/VHOST`) instead of `navigator.conf.rabbitmq_dsn`.
  - Replace `navigator.exceptions.ValidationError` as in Module 3.
- **Depends on**: Module 1, Module 2, `aiormq` (extra `[rabbitmq]`)

### Module 5: SQS Broker

- **Path**: `src/navigator_eventbus/brokers/sqs/{__init__,connection,consumer,producer}.py`
- **Responsibility**: Port SQS broker. Desacoples:
  - AWS credentials: read `AWS_KEY/SECRET/REGION` via `navconfig.config.get()` locally.
  - Replace `navigator.exceptions.ValidationError` as in Module 3.
- **Depends on**: Module 1, Module 2, `aioboto3` (extra `[sqs]`)

### Module 6: Hook Rewiring

- **Path**: `src/navigator_eventbus/hooks/brokers/{redis,rabbitmq,sqs}.py`
- **Responsibility**: Change lazy-imports in the three hook files from
  `from navigator.brokers.X import XConnection` to
  `from navigator_eventbus.brokers.X import XConnection`. No behavioral changes.
- **Depends on**: Modules 3, 4, 5

### Module 7: Extras & Configuration

- **Path**: `pyproject.toml`
- **Responsibility**: Add optional-dependency groups:
  - `brokers = ["navigator-eventbus[redis]"]` — base broker support (Redis is the primary)
  - `rabbitmq = ["aiormq"]`
  - `sqs = ["aioboto3"]`
  - `pickle = ["cloudpickle"]`
  - `serializer = ["cloudpickle", "msgpack", "jsonpickle"]`
  - Update `all` extra to include `brokers`, `rabbitmq`, `sqs`.
- **Depends on**: none

### Module 8: Tests

- **Path**: `tests/brokers/`
- **Responsibility**:
  - Port and adapt the PR #393 test suite (`test_redis_consumer.py` — kwargs fix,
    XAUTOCLAIM sweep, credentials keyword).
  - Unit tests for `DataSerializer` (JSON default path, cloudpickle opt-in, msgpack
    opt-in).
  - Unit tests for `BrokerProducer` auth_callable injection (with and without callable).
  - Unit tests for `BaseConnection` desacople (setup with raw `web.Application`).
  - Integration smoke test: `RedisConnection.connect()` + `publish_message()` +
    `consume_messages()` (requires Redis, marked `@pytest.mark.redis`).
- **Depends on**: Modules 1–6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_redis_consumer_kwargs_pop` | 3 | RedisConsumer with queue_name/group_name/consumer_name kwargs does not raise TypeError |
| `test_redis_consumer_default_kwargs` | 3 | RedisConsumer without explicit kwargs uses defaults |
| `test_reclaim_pending_messages` | 3 | XAUTOCLAIM sweep processes stuck entries and calls callback |
| `test_reclaim_pending_empty_pel` | 3 | XAUTOCLAIM returns 0 when PEL is empty |
| `test_broker_producer_credentials_keyword` | 1 | BrokerProducer accepts credentials as keyword (None default) |
| `test_broker_producer_auth_callable` | 1 | service_auth delegates to injected auth_callable |
| `test_broker_producer_no_auth` | 1 | service_auth returns 401 when no auth_callable |
| `test_base_connection_setup_raw_app` | 1 | setup() works with plain `web.Application` (no BaseApplication) |
| `test_data_serializer_json_default` | 2 | encode/decode use JSON (orjson) by default |
| `test_data_serializer_cloudpickle_opt_in` | 2 | serialize/unserialize use cloudpickle when installed |
| `test_data_serializer_msgpack` | 2 | pack/unpack use msgpack when installed |
| `test_rabbitmq_connection_dsn_navconfig` | 4 | RabbitMQConnection reads DSN from navconfig, not navigator.conf |
| `test_sqs_connection_creds_navconfig` | 5 | SQSConnection reads AWS creds from navconfig |
| `test_hook_rewire_redis` | 6 | RedisBrokerHook.connect() imports from navigator_eventbus.brokers.redis |
| `test_hook_rewire_rabbitmq` | 6 | RabbitMQBrokerHook.connect() imports from navigator_eventbus.brokers.rabbitmq |
| `test_hook_rewire_sqs` | 6 | SQSBrokerHook.connect() imports from navigator_eventbus.brokers.sqs |

### Integration Tests

| Test | Description |
|---|---|
| `test_redis_publish_consume_roundtrip` | Publish → consume → ACK via RedisConnection (requires live Redis, `@pytest.mark.redis`) |
| `test_redis_consumer_subscribe_events` | RedisConsumer.subscribe_to_events() starts background task, processes messages |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_redis():
    """Mock aioredis.Redis for unit tests."""
    ...

@pytest.fixture
def auth_callable():
    """Dummy auth callable returning a mock session."""
    async def _auth(request):
        return {"user_id": 42}
    return _auth

@pytest.fixture
def broker_config():
    """BrokerHookConfig for hook rewiring tests."""
    return BrokerHookConfig(
        queue_name="test_stream",
        group_name="test_group",
        consumer_name="test_consumer",
    )
```

---

## 5. Acceptance Criteria

- [x] *(Resolved in brainstorm)* Serialization default is JSON via orjson (`JSONContent`);
  cloudpickle optional via extra `[pickle]`/`[serializer]`.
- [x] *(Resolved in brainstorm)* `BrokerProducer` auth desacople via `auth_callable`
  injection — navigator passes its `get_session` resolver at construction time.
- [x] *(Resolved in brainstorm)* Streams unification (brokers/redis vs RedisStreamsBackend)
  deferred to post-migration spec `eventbus-streams-consolidation`.
- [ ] All `navigator.brokers` source files (~2,197 LOC) ported to
  `navigator_eventbus/brokers/` with src-layout.
- [ ] PR #393 fix #1: `RedisConsumer(**kwargs)` no longer raises `TypeError` on
  `queue_name`/`group_name`/`consumer_name`.
- [ ] PR #393 fix #2: `RedisConnection.reclaim_pending_messages()` exists and uses
  `XAUTOCLAIM` for PEL redelivery.
- [ ] PR #393 fix #3: `BrokerProducer(credentials=...)` accepts credentials as keyword
  with `None` default.
- [ ] `BrokerProducer` has zero imports from `navigator_session` or `navigator_auth`.
- [ ] `BaseConnection` and `BrokerProducer` have zero imports from
  `navigator.applications.base`.
- [ ] No file in `navigator_eventbus/brokers/` imports from `navigator.*`.
- [ ] Hooks `hooks/brokers/{redis,rabbitmq,sqs}.py` import from
  `navigator_eventbus.brokers.*` (no `navigator.brokers` references remain).
- [ ] `pyproject.toml` has extras: `brokers`, `rabbitmq`, `sqs`, `pickle`, `serializer`.
- [ ] `uv pip install -e ".[brokers,rabbitmq,sqs,dev]"` succeeds in navigator-eventbus venv.
- [ ] `python -c "from navigator_eventbus.brokers.redis import RedisConnection"` works
  without navigator installed.
- [ ] All unit tests pass: `pytest tests/brokers/ -v`.
- [ ] `ruff check src/navigator_eventbus/brokers/` passes clean.
- [ ] `mypy src/navigator_eventbus/brokers/` passes (or matches project baseline).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Source: navigator/brokers/ (repo navigator, verified 2026-07-17)
from aiohttp import web                              # connection.py:8, producer.py:5
from navconfig.logging import logging                 # connection.py:9, consumer.py:4, producer.py:6
from navconfig import config                          # sqs/connection.py:11
from navigator.applications.base import BaseApplication  # connection.py:10, producer.py:11 ← TO REMOVE
from navigator_session import get_session             # producer.py:7 ← TO REMOVE
from navigator_auth.conf import AUTH_SESSION_OBJECT   # producer.py:8 ← TO REMOVE
from navigator.exceptions import ValidationError      # redis/connection.py:13, rabbitmq/connection.py:12, sqs/connection.py:14 ← TO REPLACE
from navigator.conf import (REDIS_BROKER_HOST, REDIS_BROKER_PORT,  # redis/connection.py:16-22 ← TO REPLACE
    REDIS_BROKER_PASSWORD, REDIS_BROKER_DB, REDIS_BROKER_URL,
    rabbitmq_dsn, BROKER_MANAGER_QUEUE_SIZE)

# Deps that stay as-is:
from redis import asyncio as aioredis                 # redis/connection.py:9
import aiormq                                         # rabbitmq/connection.py:8
import aioboto3                                       # sqs/connection.py:9
from datamodel import Model, BaseModel                # pickle.py:9, redis/connection.py:10
from datamodel.parsers.json import json_encoder, json_decoder  # redis/connection.py:12, rabbitmq/connection.py:11 ← replace with serialization module
import jsonpickle                                     # pickle.py:3
import msgpack                                        # pickle.py:7
import cloudpickle                                    # pickle.py:8

# Destination package (navigator-eventbus, verified 2026-07-17):
from navigator_eventbus.serialization import dumps, loads       # serialization.py:17,31
from navigator_eventbus.hooks.brokers.base import BaseBrokerHook  # hooks/brokers/base.py
from navigator_eventbus.hooks.models import BrokerHookConfig, HookType  # hooks/models.py
```

### Existing Class Signatures

```python
# navigator/brokers/connection.py:14
class BaseConnection(ABC):
    def __init__(self, *args, credentials: Union[str, dict] = None,
                 timeout: Optional[int] = 5, **kwargs)                   # :19
    def get_connection(self) -> Optional[Union[Callable, Awaitable]]     # :41
    def get_serializer(self) -> DataSerializer                           # :46
    async def connect(self) -> None                                      # :57 (abstract)
    async def disconnect(self) -> None                                   # :64 (abstract)
    async def ensure_connection(self) -> None                            # :70
    async def publish_message(self, body, queue_name=None, **kwargs)     # :78 (abstract)
    async def consume_messages(self, queue_name, callback, **kwargs)     # :89 (abstract)
    async def process_message(self, body, properties)                    # :101 (abstract)
    async def start(self, app: web.Application) -> None                  # :112
    async def stop(self, app: web.Application) -> None                   # :115
    def setup(self, app: web.Application = None) -> None                 # :119

# navigator/brokers/consumer.py:6
class BrokerConsumer(ABC):
    _name_: str = "broker_consumer"                                      # :10
    def __init__(self, callback=None, **kwargs)                          # :12
    async def event_subscribe(self, queue_name, callback) -> None        # :22 (abstract)
    async def subscriber_callback(self, message, body) -> None           # :32 (abstract)
    def wrap_callback(self, callback, requeue_on_fail=False, max_retries=3) # :44 (abstract)

# navigator/brokers/producer.py:16
class BrokerProducer(BaseConnection, ABC):
    _name_: str = "broker_producer"                                      # :27
    def __init__(self, credentials: Union[str, dict],                    # :29 ← BUG #3
                 queue_size=None, num_workers=4, timeout=5, **kwargs)
    def setup(self, app: web.Application = None) -> None                 # :47
    async def start_workers(self)                                        # :72
    async def start(self, app: web.Application) -> None                  # :82
    async def stop(self, app: web.Application) -> None                   # :91
    async def queue_event(self, body, queue_name, routing_key=None, **kw)# :108
    async def publish_event(self, body, queue_name, **kwargs)            # :134
    async def get_userid(self, session, idx='user_id') -> int            # :151
    @staticmethod service_auth(fn) -> Callable                           # :162
    @service_auth event_publisher(self, request) -> web.Response         # :186
    async def _event_broker(self, worker_id: int)                        # :231

# navigator/brokers/redis/connection.py:24
class RedisConnection(BaseConnection):
    def __init__(self, credentials=None, timeout=5, **kwargs)            # :28
    async def connect(self)                                              # :48
    async def disconnect(self)                                           # :75
    async def ensure_group_exists(self)                                  # :88
    async def publish_message(self, body, queue_name=None, **kwargs)     # :127
    async def process_message(self, message_data)                        # :179
    async def consume_messages(self, queue_name, callback, count=1,
                               block=1000, **kwargs)                     # :212
    async def cleanup_old_messages(self, stream)                         # :269

# navigator/brokers/redis/consumer.py:15 ← BUG #1
class RedisConsumer(RedisConnection, BrokerConsumer):
    _name_: str = "redis_consumer"                                       # :21
    def __init__(self, credentials=None, timeout=5, callback=None, **kwargs) # :23
    # BUG: kwargs.get() at :30-32 → must be kwargs.pop()
    async def subscriber_callback(self, message_id, body)                # :46
    def wrap_callback(self, callback)                                    # :62
    async def event_subscribe(self, queue_name, callback, **kwargs)      # :79
    async def subscribe_to_events(self, queue_name, callback, **kwargs)  # :92
    async def stop_consumer(self)                                        # :116
    async def start(self, app: web.Application)                          # :129
    async def stop(self, app: web.Application)                           # :140

# navigator/brokers/wrapper.py:10
class BaseWrapper:
    _queued: bool = True                                                 # :11
    _debug: bool = False                                                 # :12
    def __init__(self, coro=None, *args, **kwargs)                       # :14
    async def call(self)                                                 # :29
    async def __call__(self)                                             # :33
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `brokers.redis.RedisConnection` | `navigator_eventbus.serialization` | `dumps()`/`loads()` replacing `json_encoder`/`json_decoder` | `serialization.py:17,31` |
| `brokers.serializers.DataSerializer` | `navigator_eventbus.serialization` | `dumps()`/`loads()` as JSON default | `serialization.py:17,31` |
| `hooks.brokers.redis.RedisBrokerHook` | `brokers.redis.RedisConnection` | lazy-import in `connect()` | `hooks/brokers/redis.py:30` |
| `hooks.brokers.rabbitmq.RabbitMQBrokerHook` | `brokers.rabbitmq.RabbitMQConnection` | lazy-import in `connect()` | `hooks/brokers/rabbitmq.py:31` |
| `hooks.brokers.sqs.SQSBrokerHook` | `brokers.sqs.SQSConnection` | lazy-import in `connect()` | `hooks/brokers/sqs.py:29` |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator_eventbus.brokers`~~ — does NOT exist yet; this spec creates it.
- ~~MQTT broker in `navigator.brokers`~~ — no MQTT subpackage exists in navigator; the
  mqtt hook uses `gmqtt` directly (unaffected by this port).
- ~~`XCLAIM`/`XAUTOCLAIM` in `navigator.brokers`~~ — does NOT exist in navigator master
  (bug #2); the only XAUTOCLAIM in the ecosystem is in `RedisStreamsBackend`
  (`navigator_eventbus/backends/redis_streams.py`).
- ~~`navigator_eventbus.brokers.pickle`~~ — will NOT exist; serialization uses
  `brokers/serializers.py` (new name, to avoid confusion with stdlib `pickle`).
- ~~`navigator.brokers.mqtt`~~ — does not exist.
- ~~`BrokerProducer(credentials=None)` working in navigator~~ — currently crashes because
  `credentials` is positional-required (bug #3).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Desacople pattern for `BaseApplication`**: use duck-typing —
  `app = app.get_app() if hasattr(app, 'get_app') else app` instead of
  `isinstance(app, BaseApplication)`.
- **Desacople pattern for config**: read broker-related env vars via
  `navconfig.config.get("VAR_NAME", fallback=default)` in a local `_conf.py` module
  inside `brokers/`, instead of importing from `navigator.conf`.
- **Lazy-import pattern for optional deps**: match the existing pattern in
  `navigator_eventbus/dlq.py` — try/except ImportError with actionable message.
- **PR #393 fix #1 pattern**: `kwargs.pop('key', default)` before `super().__init__()`.
- **PR #393 fix #2 pattern**: new method `reclaim_pending_messages()` on
  `RedisConnection` using `self._connection.xautoclaim()` — opt-in, callers schedule.
- **Serialization**: `DataSerializer` in `brokers/serializers.py` uses
  `navigator_eventbus.serialization.dumps/loads` for JSON; `cloudpickle`/`msgpack`
  lazy-imported in their respective methods.

### Known Risks / Gotchas

- **MRO complexity**: `RedisConsumer(RedisConnection, BrokerConsumer)` and
  `RedisProducer(RedisConnection, BrokerProducer)` use cooperative multiple inheritance.
  The kwargs.pop fix (bug #1) is critical to avoid `TypeError` in the MRO chain.
- **`navigator.conf` constants**: the source of truth for `REDIS_BROKER_HOST` etc. moves
  from navigator's `conf.py` to navconfig env vars read locally. Existing deployments
  already set these env vars (navconfig reads from env/toml) — no behavior change.
- **`BaseApplication` typing**: removing the isinstance check means `setup()` no longer
  validates the app type. This is acceptable — the method signature already accepts
  `web.Application`, and `BaseApplication.get_app()` returns one.
- **`service_auth` without auth_callable**: when `auth_callable is None`, the decorator
  must raise `web.HTTPUnauthorized` — never silently proceed without auth.
- **Redis XAUTOCLAIM availability**: requires Redis >= 6.2. The `reclaim_pending_messages`
  method should handle `ResponseError` gracefully if the server is older.
- **Coexistence during migration window**: until phase 5, navigator still ships its own
  `brokers/` (frozen). No import conflicts because the packages use different names
  (`navigator.brokers` vs `navigator_eventbus.brokers`).

### External Dependencies

| Package | Version | Reason | Extra |
|---|---|---|---|
| `navconfig` | `>=2.2.2` | config + logging (already dep) | core |
| `aiohttp` | `>=3.9` | web.Application, HTTP endpoint | core |
| `datamodel` | `>=0.6` | Model/BaseModel for serialization | core |
| `redis` | `>=5` | Redis Streams consumer/producer | `[redis]` (already exists) |
| `aiormq` | `>=6.7` | RabbitMQ connection | `[rabbitmq]` (new) |
| `aioboto3` | `>=12` | AWS SQS connection | `[sqs]` (new) |
| `cloudpickle` | `>=3` | Binary serialization (opt-in) | `[pickle]` (new) |
| `msgpack` | `>=1` | Binary packing (opt-in) | `[serializer]` (new) |
| `jsonpickle` | `>=3` | Legacy JSON serialization (opt-in) | `[serializer]` (new) |

---

## 8. Open Questions

- [x] ¿Diseño del desacople de `BrokerProducer`? — *Resolved in brainstorm*:
  auth-callable inyectable — `BrokerProducer.__init__` acepta un `auth_callable`
  opcional; navigator le pasa su resolver de `navigator_session`/`navigator_auth.conf`
  al construirlo. El paquete no depende de navigator para autenticación.
- [x] ¿`datamodel`/`msgpack`/`cloudpickle` (serialización): deps directas o extras? —
  *Resolved in brainstorm*: serialización en JSON usando `JSONContent` (orjson) como
  formato por defecto; cloudpickle como serialización opcional (extra `[pickle]` o
  `[serializer]`). `msgpack` también opcional. El fallback siempre es JSON vía orjson.
- [x] ¿Unificar el consumer de streams de `brokers/redis` con `RedisStreamsBackend` del
  bus? — *Resolved in brainstorm*: se porta tal cual en esta fase (no bloquea la
  migración); la consolidación se hace post-migración como spec propio
  (`eventbus-streams-consolidation`).
- [x] ¿Coordinación de la fase 5? — *Resolved in brainstorm*: Jesus es owner de todos
  los paquetes y realiza la migración de cada uno (Flowtask, FieldSync, navigator).
  Se le comunica a `hacu9` que el fix aterriza en el paquete nuevo.
- [x] ¿Cómo aterrizan los fixes del PR navigator#393? — *Resolved in brainstorm*:
  directamente en el port dentro de navigator-eventbus (con los tests del PR); el PR
  se cierra referenciando la migración o se mergea después sin urgencia.
- [x] ¿Shim de compatibilidad en navigator? — *Resolved in brainstorm*: no — borrar
  `navigator/brokers/` y migrar consumidores (migración dura, release coordinado).

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree of the
  `navigator-eventbus` repo.
- **Parallelism**: this spec (phase 3) is **parallelizable with FEAT-313** (phase 2,
  lifecycle extraction) — it only depends on the phase 1 scaffold (FEAT-312), not on
  lifecycle.
- **Cross-feature dependencies**: FEAT-312 (`eventbus-core-extraction`) must be merged
  first — it provides the package scaffold, `serialization.py`, hooks/brokers stubs,
  and the `BaseBrokerHook` base class.
- **Repo**: work happens in `/home/jesuslara/proyectos/navigator-eventbus` (worktree
  branched from its `main`). The spec file lives in ai-parrot's SDD tree for tracking.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-17 | Jesus + Claude | Initial draft from navigator-eventbus-extraction brainstorm |
