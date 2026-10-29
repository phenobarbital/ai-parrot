# G6 — Bus Call/Result envelope spike (FEAT-746)

## Environment

- Python: 3.12.7
- navigator-eventbus: 0.4.0
- Core payload codec: `parrot.interagent.BusPayloadSerializer` (TASK-4741)
- Redis URL: optional `SQUAWK_SPIKE_REDIS_URL`; no URL was supplied for this recorded run, so the in-process `MemoryBackend` fallback was used.

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

| Criterion | Result | Evidence |
|---|---|---|
| Call reaches server and result returns to its correlation-specific reply topic | PASS (memory fallback) | Two replies were decoded as `ResultMessage`; their `correlation_id`s matched the two executed calls. |
| Bytes survive JSON transport | PASS (memory fallback) | The 1 MiB random payload and the `b"\\x00\\xff" * 8` payload were equal after `BusPayloadSerializer` encode/decode. |
| Consumer idempotency deduplication | PASS (memory fallback) | Three calls containing two identical `idempotency_key` values executed exactly twice. |
| Undeliverable result reaches DLQ handling | PASS (memory fallback) | A deliberately failing reply subscriber exhausted one retry and invoked the configured EventBus `on_dlq` callback with `squawk:caller:replies:undeliverable`. |
| Redis Streams distributed request/reply and durable DLQ table | FAIL / not run | No `SQUAWK_SPIKE_REDIS_URL` was provided. This must be rerun against operator Redis before declaring the Streams gate passed. |

For the 1 MiB frame, the measured full JSON-wrapper overhead was **33.4%**.
Base64 itself expands bytes by approximately 33.3%; the small difference is
the serializer envelope.

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
