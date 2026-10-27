# TASK-4722: Envelope codec (JSON fallback) and navigator-eventbus carrier (M9)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4720
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 9**. Resolved Q2: a sync `EnvelopeCodec` protocol declared in Roost with
`JsonEnvelopeCodec` in core (the satellite's Cap'n Proto codec implements the same protocol and is picked by
TASK-4724's bridge). The carrier is the default same-network transport on a **dedicated** navigator-eventbus
instance (FEAT-710 idiom: Streams, outbox, `event_id` dedup) with `reply_to`, correlation, idempotency and a DLQ.
Resolved Q3: serialized `permission_context` and `auth_token` both travel.

---

## Scope

- Create `parrot/roost/codec.py`: `UnencodableContent`, `EnvelopeCodec`, `JsonEnvelopeCodec`.
- Create `parrot/roost/carriers/bus.py`: `EventBusCarrier`, `build_roost_bus`.
- Write `tests/roost/test_codec_bus.py` with an in-memory bus (`EventBus(transport='memory')`).

**NOT in scope**: the Cap'n Proto codec (FEAT-746 satellite, wrapped by TASK-4724); Redis integration tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/codec.py` | CREATE | Codec protocol + JSON codec |
| `packages/ai-parrot/src/parrot/roost/carriers/bus.py` | CREATE | EventBusCarrier + build_roost_bus |
| `packages/ai-parrot/tests/roost/test_codec_bus.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from navigator_eventbus import EventBus                   # verified: parrot/observability/fanout.py:15 (navigator-eventbus 0.4.0)
from navigator_eventbus.evb import Event                  # verified: installed 0.4.0
from parrot.roost.messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage   # TASK-4711
from parrot.roost.carriers.base import Carrier, Inbound, Undeliverable                     # TASK-4720
from parrot.core.events.lifecycle import TraceContext     # verified: core/events/lifecycle/__init__.py:18
```

### Existing Signatures to Use
```python
# navigator_eventbus 0.4.0
class EventBus:
    def __init__(self, redis_url=None, use_redis=False, *, channel_prefix=None, backend=None,
                 transport: Literal['memory','pubsub','streams'] | None = None, publish_only=False, outbox=None, **bus_options)
    async def publish(self, event: Event, *, severity=None) -> int
    def subscribe(self, pattern: str, handler: Callable[[Event], Any], *, priority=0, filter_fn=None, min_severity=None) -> str
    def unsubscribe(self, subscriber_id: str) -> bool        # SYNC (verified with inspect, 0.4.0); subscribe is SYNC too
    async def close(self)
class Event:  # navigator_eventbus.evb
    def __init__(self, event_type: str, payload: Dict[str, Any], event_id=<factory>, timestamp=<factory>, source=None,
                 priority=EventPriority.NORMAL, correlation_id: Optional[str] = None, metadata: Dict[str, Any] = <factory>)
# parrot/observability/fanout.py
def _config_value(name: str, fallback: Optional[str] = None) -> Optional[str]   # line 51 — navconfig + env fallback (copy the idea)
def _validate_bus(bus: Any) -> None                                              # line 74 — reads bus.transport / bus._core._backend
```

### Does NOT Exist
- ~~`Event.reply_to` — absent; carry it in `metadata['reply_to']`~~
- ~~`EventBus.request()` / `.reply()` — absent~~
- ~~`navigator_eventbus.models.EventEnvelope` — not importable~~
- ~~`parrot.squawk` imports here — forbidden (only TASK-4724 may name the satellite)~~
- ~~reusing the FEAT-710 telemetry bus or its `PARROT_EVENT_FANOUT_*` keys — use `PARROT_ROOST_BUS_URL` / `PARROT_ROOST_BUS_PREFIX`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/codec.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/roost/carriers/bus.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_codec_bus.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/fanout.py#_validate_bus"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `JsonEnvelopeCodec.encode`: JSON object with the `LocalEnvelope` fields read off any `EnvelopeLike` (trace as `{trace_id, span_id}`), every `RoostMessage` field except `envelope`, and `content` encoded as `{"model": <dotted class>, "data": model_dump(mode='json')}` for Pydantic models, raw for JSON-able values, else raise `UnencodableContent` — frames must be a handle by now. `permission_context` is encoded via `vars()`-free `to_dict()` if present else `str()`; document the lossy fallback with a logger warning.
- `decode` rebuilds a `LocalEnvelope`; Pydantic content is re-validated only when the class is importable (`importlib`), else left as the dict.
- Topics: `{prefix}.{agent}` addressed, `{prefix}.cap.{category}` broadcast (category = cap filter with the last segment/`*` dropped), `dlq_topic` for undeliverable/undecodable.
- `Event.payload = {'codec': codec.content_type, 'data': base64(bytes)}`; `metadata` carries reply_to, idempotency_key (envelope's or message_id), trace_id, performative, conversation_id, auth_token.
- Dedup: an LRU (`collections.OrderedDict`) of `dedup_size` idempotency keys; duplicates are dropped silently (Streams is at-least-once).
- Constructor validation: reject `publish_only=True` (Roost must subscribe; probe `bus.publish_only` then `bus._core._publish_only` like `_validate_bus`); reject a detected non-streams Redis backend in production via `build_roost_bus` only — an `EventBus(transport='memory')` reports `transport=None` (verified) and must be accepted for tests.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/observability/fanout.py:51-120` — config + bus validation idiom

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `codec.py` — *why*: the carrier and the bridge both depend on it.
2. Write `bus.py` with static `to_event`/`from_event` first (pure, easy to test), then send/subscribe.
3. Tests with `EventBus(transport='memory')`.

### `packages/ai-parrot/src/parrot/roost/codec.py` (CREATE)
```python
"""Envelope codecs (FEAT-747 M9, resolved Q2). Sync, bytes-safe."""
from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from .messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage

logger = logging.getLogger(__name__)


class UnencodableContent(ValueError):
    """Content is neither a Pydantic model, a JSON value nor a handle id — move it to a handle first."""


@runtime_checkable
class EnvelopeCodec(Protocol):
    content_type: str

    def encode(self, msg: RoostMessage) -> bytes: ...

    def decode(self, data: bytes) -> RoostMessage: ...


class JsonEnvelopeCodec:
    """Roost's fallback codec (dev, tests, satellite-less deployments)."""

    content_type = "application/json"

    def encode(self, msg: RoostMessage) -> bytes:
        raise NotImplementedError  # FILL IN — Key Constraints bullet 1

    def decode(self, data: bytes) -> RoostMessage:
        raise NotImplementedError  # FILL IN — bullet 2
```
**Why**: Names are fixed by spec §2/M9 and by TASK-4724, which wraps the satellite codec in the same Protocol.

### `packages/ai-parrot/src/parrot/roost/carriers/bus.py` (CREATE)
```python
"""navigator-eventbus carrier on a dedicated instance (FEAT-747 M9)."""
from __future__ import annotations

import base64
import logging
import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

from ..codec import EnvelopeCodec, JsonEnvelopeCodec
from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind
from .base import Carrier, Inbound, Undeliverable

if TYPE_CHECKING:
    from navigator_eventbus import EventBus
    from navigator_eventbus.evb import Event


class EventBusCarrier(Carrier):
    kind = CarrierKind.NETWORK

    def __init__(self, bus: "EventBus", *, topic_prefix: str = "roost", dlq_topic: str = "roost.dlq",
                 codec: Optional[EnvelopeCodec] = None, dedup_size: int = 10_000) -> None:
        self.logger = logging.getLogger(__name__)
        # FILL IN: validate bus (Key Constraints bullet 6)
        self._bus, self._prefix, self._dlq = bus, topic_prefix, dlq_topic
        self._codec = codec or JsonEnvelopeCodec()
        self._codecs: dict[str, EnvelopeCodec] = {self._codec.content_type: self._codec}
        self._seen: "OrderedDict[str, None]" = OrderedDict()
        self._dedup_size = dedup_size

    async def send(self, msg: RoostMessage) -> None:
        raise NotImplementedError  # FILL IN — topic per receiver / broadcast category, publish to_event(...)

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        raise NotImplementedError  # FILL IN — one bus.subscribe per topic; handler: dedup → from_event → inbound

    async def unsubscribe(self, subscription_id: str) -> bool:
        raise NotImplementedError  # FILL IN

    async def close(self) -> None:
        raise NotImplementedError  # FILL IN — unsubscribe all; do NOT close a bus you did not build

    @staticmethod
    def to_event(msg: RoostMessage, *, codec: EnvelopeCodec, prefix: str) -> "Event":
        raise NotImplementedError  # FILL IN — bullets 3-4

    @staticmethod
    def from_event(event: "Event", *, codecs: Mapping[str, EnvelopeCodec]) -> RoostMessage:
        """Unknown codec ⇒ raise LookupError (the subscriber routes it to the DLQ, never into the handler)."""
        raise NotImplementedError  # FILL IN


def build_roost_bus() -> "EventBus":
    """Dedicated publish+subscribe Streams bus from PARROT_ROOST_BUS_* (navconfig with env fallback), outbox enabled."""
    raise NotImplementedError  # FILL IN — copy fanout._config_value's resolution; never reuse telemetry keys
```
**Why**: Static `to_event`/`from_event` keep the mapping testable without a bus; `navigator_eventbus` is imported under TYPE_CHECKING and inside functions so `parrot.roost` stays importable cheaply.

### FILL IN checklist
- [ ] `JsonEnvelopeCodec.encode/decode`
- [ ] `EventBusCarrier` methods + `build_roost_bus`
- [ ] tests

---

## Acceptance Criteria

- [ ] Codec round trip preserves every Roost field and the envelope fields
- [ ] Unencodable content raises
- [ ] `Event.correlation_id` set; `metadata.reply_to`, `idempotency_key`, `auth_token` present (AC-19, AC-35)
- [ ] A replayed event with the same idempotency key is delivered once
- [ ] An event with an unknown codec lands on the DLQ topic
- [ ] A publish-only bus is rejected
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/codec.py packages/ai-parrot/src/parrot/roost/carriers/bus.py packages/ai-parrot/tests/roost/test_codec_bus.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_codec_bus.py -q`

---

## Test Specification

```python
import pytest

from parrot.roost.codec import JsonEnvelopeCodec, UnencodableContent
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P


def _msg(envelope, content=None):
    return RoostMessage(performative=P.REQUEST, protocol=IP.REQUEST, conversation_id="c", envelope=envelope,
                        sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], content=content,
                        auth_token="tok")


def test_json_roundtrip(envelope):
    out = JsonEnvelopeCodec().decode(JsonEnvelopeCodec().encode(_msg(envelope, {"x": 1})))
    assert out.content == {"x": 1} and out.envelope.correlation_id == "corr-1" and out.auth_token == "tok"


def test_unencodable(envelope):
    with pytest.raises(UnencodableContent):
        JsonEnvelopeCodec().encode(_msg(envelope, object()))
# FILL IN: to_event metadata/correlation, dedup, DLQ, publish_only rejected — with EventBus(transport="memory")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4722 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

