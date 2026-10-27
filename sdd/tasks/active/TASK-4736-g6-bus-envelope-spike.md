# TASK-4736: G6 — Call/Result envelope on navigator-eventbus Streams spike (reply_to, correlation, dedup, DLQ)

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4741, TASK-4737
**Assigned-to**: unassigned

---

## Context

Spec §3 gate **G6 — S6 envelope on the bus**, a **hard v0 gate** (U4, §8 Q2). The bus carrier (M11) must run on navigator-eventbus 0.4.0 Streams with a Squawk-owned `reply_to` topic convention and core's `BusPayloadSerializer` (TASK-4741). G6 proves: a `CallMessage` published on `squawk:<server>:calls` is consumed by the serving loop, its `ResultMessage` lands on `reply_to`, a duplicate `idempotency_key` is dropped, an undeliverable result reaches the DLQ, and the payload survives JSON (bytes fields intact). The report also attaches the written navigator-eventbus change request (`reply_to` helper + bytes payload). A FAIL amends M11's convention; it never blocks on upstream.

---

## Scope

- `spike.py`: two `EventBus(transport="streams")` instances (caller, server) against a Redis given by `SQUAWK_SPIKE_REDIS_URL` (fallback: the in-memory backend for the dedup/round-trip part, clearly labelled); publish 3 calls (two with the same `idempotency_key`), serve them with a dummy dispatcher, publish results to `reply_to`, consume on the caller side; force one undeliverable result and show it in the DLQ.
- `report.md`: per-criterion PASS/FAIL, Redis/eventbus versions, measured overhead of base64 on a 1 MB frame, and the navigator-eventbus change request text.
- `packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py`: opt-in `PARROT_SPIKE=1`; memory backend; asserts round-trip + dedup.

**NOT in scope**: `SquawkBusCarrier` (M11, gated on this spike), the `CapabilityDispatcher` (M8), any change to navigator-eventbus.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-746/spikes/G6-bus-envelope/spike.py` | CREATE | Streams round-trip, dedup, DLQ |
| `sdd/state/FEAT-746/spikes/G6-bus-envelope/report.md` | CREATE | Gate report + change request |
| `packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py` | CREATE | Opt-in regression (memory backend) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_eventbus import EventBus   # navigator-eventbus 0.4.0; usage verified: packages/ai-parrot/src/parrot/observability/fanout.py:24 (EventBus(redis_url=..., transport="streams", publish_only=True, channel_prefix=..., outbox=...))
from parrot.interagent import BusPayloadSerializer, CallMessage, ResultMessage, Budget, CallCost   # TASK-4741 / TASK-4740 (parrot/interagent/bus_codec.py, messages.py, ledger.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/fanout.py:24 — setup_event_fanout(): the FEAT-710 idiom for a dedicated streams EventBus; copy its constructor kwargs
# navigator_eventbus.envelope.EventEnvelope (site-packages/navigator_eventbus/envelope.py:164 to_dict) — fields: topic, payload, event_id, timestamp, source, severity, priority, correlation_id, trace_context, metadata
# docs/events/eventbus-v2.md — Streams: consumer groups, XACK, XAUTOCLAIM, event_id TTL dedup; DLQ table navigator.evb_dlq with replay()
```
Read `site-packages/navigator_eventbus/evb.py` and `backends/redis_streams.py` for the subscribe/consume API (publish_only=False) and record the exact calls in the report.

### Does NOT Exist
- ~~`EventBus.request()` / a `reply_to` helper on Streams~~ — only the RabbitMQ broker connection mentions `reply_to` (navigator_eventbus/brokers/rabbitmq/connection.py:393); the convention is Squawk's own (`metadata["reply_to"]`).
- ~~a bytes-safe payload serializer in navigator-eventbus~~ — JSON only (`serialization.py`, orjson); hence `BusPayloadSerializer`.
- ~~`parrot.squawk.transport.bus.SquawkBusCarrier`~~ — M11, gated on this spike.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-746/spikes/G6-bus-envelope/spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G6-bus-envelope/report.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/observability/fanout.py#setup_event_fanout"]
}
```

---

## Implementation Notes

### Key Constraints
- Exclusive task: needs a Redis Streams instance (`SQUAWK_SPIKE_REDIS_URL`); a *dedicated* `channel_prefix="squawk:"` so the telemetry fan-out instance is never touched (FEAT-710 rule).
- Topic layout under test (spec §3 M11): calls on `squawk:<server>:calls`, replies on `squawk:<caller>:replies:<correlation_id>`, `metadata={"reply_to": ..., "idempotency_key": ..., "trace_id": ...}`, `correlation_id=call.correlation_id`.
- Dedup is the consumer's job (`idempotency_key` LRU with TTL), on top of the backend's `event_id` dedup — measure both.
- Bytes safety: put a 1 MB random `bytes` in `CallMessage.args` and assert equality after the round trip; record the base64 size overhead.

### References in Codebase
- `packages/ai-parrot/src/parrot/observability/fanout.py` — dedicated-instance construction.
- `docs/events/eventbus-v2.md` — Streams semantics and DLQ.

---

## Implementation Blueprint

### Steps (in order)
1. Write `make_bus(role, url)` copying the fanout.py kwargs with `publish_only=False` and prefix `squawk:` — *why*: dedicated instance, never the telemetry one.
2. `serve(bus, dispatcher, seen)` consumer loop: decode via `BusPayloadSerializer.from_payload`, dedup, publish result to `metadata["reply_to"]` — *why*: this is M11's `serve()` in miniature.
3. `caller(bus)` publishes three calls and awaits replies by correlation — *why*: round trip + dedup evidence.
4. Force an undeliverable reply (bad topic/closed consumer) and read the DLQ — *why*: AC08 evidence.
5. Report + change request — *why*: §8 Q2.

### `sdd/state/FEAT-746/spikes/G6-bus-envelope/spike.py` (CREATE)
```python
"""G6 — Squawk Call/Result over navigator-eventbus Streams: reply_to, correlation, dedup, DLQ (FEAT-746)."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid
from typing import Any

from navigator_eventbus import EventBus

from parrot.interagent import Budget, BusPayloadSerializer, CallCost, CallMessage, ResultMessage

SER = BusPayloadSerializer()
PREFIX = "squawk:"


def make_bus(url: str | None) -> EventBus:
    """Dedicated instance; memory backend when url is None (round-trip + dedup only)."""
    # FILL IN: mirror setup_event_fanout()'s kwargs (observability/fanout.py:24) with publish_only=False, channel_prefix=PREFIX; transport="streams" iff url — bounded by: never the telemetry instance
    raise NotImplementedError


def new_call(idem: str, payload: bytes) -> CallMessage:
    cid = uuid.uuid4().hex
    return CallMessage(envelope_id=uuid.uuid4().hex, cap_id="hr.reports.manager_of", contract_hash="sha256:" + "0" * 64, args=payload, out_hints={},
                       budget=Budget(tokens=None, ms=5000, rows=None), trace_id=uuid.uuid4().hex, correlation_id=cid, idempotency_key=idem,
                       reply_to=f"{PREFIX}caller:replies:{cid}")


async def serve(bus: EventBus, executed: list[str], seen: set[str]) -> None:
    """Consumer loop: dedup by idempotency_key, reply on reply_to."""
    async def handle(envelope) -> None:
        call = SER.from_payload(envelope.payload)
        if call.idempotency_key in seen:
            return
        seen.add(call.idempotency_key)
        executed.append(call.correlation_id)
        result = ResultMessage(status="OK", inline=call.args, handle=None, transfer="none", provenance=None,
                               cost=CallCost(duration_ms=1), trace_id=call.trace_id, correlation_id=call.correlation_id, detail=None, current_category=None)
        # FILL IN: bus.publish(topic=call.reply_to, payload=SER.to_payload(result), correlation_id=call.correlation_id) — exact publish signature from navigator_eventbus/evb.py
    # FILL IN: subscribe handle to f"{PREFIX}server:calls" — exact subscribe/consume API from the installed package
    raise NotImplementedError


async def run(url: str | None) -> dict[str, Any]:
    big = secrets.token_bytes(1024 * 1024)
    calls = [new_call("idem-A", big), new_call("idem-A", big), new_call("idem-B", b"\x00\xff" * 8)]
    executed: list[str] = []
    out: dict[str, Any] = {"backend": "streams" if url else "memory"}
    # FILL IN: start serve(); publish the 3 calls on f"{PREFIX}server:calls"; await replies on each reply_to; assert payload bytes equal; out["executed"]=len(executed) (expect 2);
    # streams only: force one undeliverable reply and read the DLQ (docs/events/eventbus-v2.md replay()) → out["dlq"] — bounded by spec G6 pass criterion
    out["base64_overhead_pct"] = round((len(json.dumps(SER.to_payload(calls[0]))) / (1024 * 1024) - 1) * 100, 1)
    return out


def main() -> int:
    print(json.dumps(asyncio.run(run(os.environ.get("SQUAWK_SPIKE_REDIS_URL"))), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: it is M11's `publish_call`/`serve`/`await_result` in one file on the real bus, using the core serializer (Q2/Q3), so a PASS validates the shipped convention and a FAIL names the missing primitive for the upstream request.

### `packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py` (CREATE)
```python
"""G6 regression — round-trip + dedup on the memory backend (opt-in)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G6-bus-envelope/spike.py"


def test_roundtrip_and_dedup_memory_backend():
    spec = importlib.util.spec_from_file_location("g6_spike", SPIKE)
    g6 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g6)
    out = asyncio.run(g6.run(None))
    assert out["executed"] == 2
```

### FILL IN checklist
- [ ] `spike.py::make_bus` — constructor kwargs; bounded by the fanout.py idiom + dedicated prefix
- [ ] `spike.py::serve` / `run` — subscribe/publish API, DLQ read; bounded by the G6 pass criterion
- [ ] `report.md` — criteria table, overhead, navigator-eventbus change request (`reply_to` helper, bytes payload)

---

## Acceptance Criteria

- [ ] Request on the bus → result consumed by the right subscriber (by `correlation_id`), bytes intact (1 MB and `\x00\xff` payloads)
- [ ] Duplicate `idempotency_key` dropped (2 executions for 3 calls); undeliverable result visible in the DLQ (Streams run)
- [ ] `report.md` records versions, base64 overhead, PASS/FAIL per criterion and the change request text (§8 Q2)
- [ ] `PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py -q`

---

## Test Specification

See blueprint test (memory backend only).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §2 Carrier semantics, §3 G6/M11, §8 Q2
3. **Check dependencies** — TASK-4741 `"done"`; a Redis URL from the operator for the Streams run
4. **Verify the Codebase Contract** — read the installed `navigator_eventbus` subscribe API first
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement** from the blueprint
7. **Verify** — Validation Commands with `PARROT_SPIKE=1`; Streams run with `SQUAWK_SPIKE_REDIS_URL`
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4736 inter-agent-protocol verified`
10. **Completion Note** — verdict + change request verbatim

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
