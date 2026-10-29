# G6 — Bus Call/Result envelope spike (FEAT-746)

## Environment

- Python: 3.12.3
- navigator-eventbus: 0.4.0; Redis 7.4.11 (Streams run) — plus the in-process `MemoryBackend` regression
- Core payload codec: `parrot.interagent.BusPayloadSerializer` (TASK-4741)
- Redis URL: `SQUAWK_SPIKE_REDIS_URL` (Streams); unset ⇒ memory fallback

## Verified API calls

The installed `EventBus` facade exposes `subscribe(pattern, handler)` and
`emit(event_type, payload, correlation_id=..., metadata=...)`; its
`publish()` method takes a legacy `Event`, not `topic=`/`payload=` keyword
arguments. The spike therefore uses `emit()` and records Squawk's routing
convention in event metadata:

```python
await bus.emit(
    topic,
    serializer.to_payload(message),
    correlation_id=message.correlation_id,
    metadata={"reply_to": reply_to, "idempotency_key": idempotency_key, "trace_id": trace_id},
)
```

## Results

Redis Streams run 2026-10-30 against Redis 7.4.11 (throwaway container), navigator-eventbus 0.4.0,
`SQUAWK_SPIKE_REDIS_URL=redis://127.0.0.1:56379/0`; 4/4 consecutive runs identical:

| Criterion | Result | Evidence |
|---|---|---|
| Call reaches server and result returns to its correlation-specific reply topic | PASS (Streams) | Calls published by the caller node, consumed by the server node's group; replies published by the server node on per-correlation streams (`evb:stream:squawk:caller:replies:<corr>`) and consumed by the caller node — both hops cross Redis. |
| Bytes survive JSON transport | PASS (Streams) | 1 MiB random payload and `b"\x00\xff" * 8` equal after `BusPayloadSerializer` encode/decode. |
| Consumer idempotency deduplication | PASS (Streams) | 3 calls, two sharing an `idempotency_key` → 2 executions. |
| Undeliverable result reaches DLQ handling | PASS (Streams) | Published by the server node so it can only arrive via Redis; the caller subscriber fails, retry exhausts (1 attempt) and `on_dlq` records the run-scoped undeliverable topic. |

Base64 overhead on the 1 MiB frame: 33.4% (base64 itself ≈ 33.3%).

### Required node configuration (findings)

The first Streams run timed out. Squawk nodes on one Redis must not share:

1. **Consumer group / consumer name.** Defaults are one group and `<hostname>-<pid>`;
   group delivery hands each entry to ONE consumer, so a call consumed by the caller node
   was dropped. Each node gets its own group.
2. **Dedup prefix.** `event_id` dedup keys are global per `dedup_prefix`; whichever node
   consumed an entry first marked it and the other skipped it. Each node gets its own prefix.
3. **Reused topics across runs.** A fresh group starts at id `0`, replaying earlier
   entries; the spike uses run-scoped call/DLQ topics (production uses stable groups, so
   this only matters for test reruns).

Also: the spike's memory fallback injects replies into the caller bus; in Streams mode
the server now publishes on its own bus, so a pass proves transport delivery.

## Reproduction

```bash
PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g6_bus_envelope.py -q
PYTHONPATH=packages/ai-parrot/src SQUAWK_SPIKE_REDIS_URL=redis://host:6379/0 \
  python sdd/state/FEAT-746/spikes/G6-bus-envelope/spike.py
```

The memory backend cannot transport between independently constructed bus
instances. Its fallback injects calls into the server dispatcher and routes
the reply to the caller dispatcher while retaining the same serialized
envelope, topic, correlation, metadata, and consumer-deduplication logic.

## navigator-eventbus change request (spec §8 Q2)

**Title:** Add an opt-in request/reply helper and bytes-safe envelope payload
codec for Streams consumers.

`EventBus` currently provides topic publish/subscribe only. Add an additive
helper that publishes a request with a generated `correlation_id`, records a
caller-provided `reply_to` topic in envelope metadata, and awaits the matching
reply with cancellation and timeout cleanup. The helper must not describe the
at-least-once Streams transport as synchronous RPC.

Add a documented codec seam for `EventEnvelope.payload` that recursively
encodes `bytes` as explicit base64-tagged JSON values and decodes only that
tagged representation. It must remain opt-in, preserve the default JSON wire
format, and bound decoded payload size. The reply helper should expose
consumer-owned `idempotency_key` handling rather than claiming exactly-once
delivery, and should provide a durable-DLQ inspection/replay API for replies
whose consumers exhaust retries.
