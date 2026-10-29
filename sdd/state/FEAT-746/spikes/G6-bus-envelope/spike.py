"""G6 — Squawk Call/Result envelope over navigator-eventbus (FEAT-746)."""

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
_LOCAL_REPLY_BUSES: dict[str, EventBus] = {}
_DLQ: list[dict[str, Any]] = []


def _record_dlq(envelope: Any, **details: Any) -> None:
    """Capture retry-exhausted envelopes for the spike's DLQ evidence."""
    _DLQ.append({"topic": envelope.topic, "attempts": details["attempts"]})


def make_bus(url: str | None) -> EventBus:
    """Create a dedicated Streams bus, or an in-memory fallback for the spike.

    Args:
        url: Redis URL for the Streams backend. ``None`` selects memory.

    Returns:
        An EventBus isolated under Squawk's channel prefix.
    """
    return EventBus(
        redis_url=url,
        transport="streams" if url else "memory",
        publish_only=False,
        channel_prefix=PREFIX,
        retry_attempts=1,
        on_dlq=_record_dlq,
    )


def new_call(idem: str, payload: bytes) -> CallMessage:
    """Build one deterministic-shape capability call for the spike."""
    correlation_id = uuid.uuid4().hex
    return CallMessage(
        envelope_id=uuid.uuid4().hex,
        cap_id="hr.reports.manager_of",
        contract_hash="sha256:" + "0" * 64,
        args=payload,
        out_hints={},
        budget=Budget(tokens=None, ms=5000, rows=None),
        trace_id=uuid.uuid4().hex,
        correlation_id=correlation_id,
        idempotency_key=idem,
        reply_to=f"{PREFIX}caller:replies:{correlation_id}",
    )


async def _emit(
    bus: EventBus,
    topic: str,
    payload: dict[str, Any],
    *,
    correlation_id: str,
    metadata: dict[str, str],
) -> None:
    """Publish a JSON-safe envelope through EventBus's verified ``emit`` API."""
    await bus.emit(topic, payload, correlation_id=correlation_id, metadata=metadata)


async def serve(bus: EventBus, executed: list[str], seen: set[str]) -> str:
    """Subscribe a miniature server that deduplicates and publishes results.

    Args:
        bus: Serving EventBus instance.
        executed: Correlations executed by the dummy dispatcher.
        seen: Consumer-owned idempotency keys.

    Returns:
        EventBus subscription ID for the server handler.
    """

    async def handle(event: Any) -> None:
        """Decode a call, apply consumer deduplication, and issue its result."""
        call = SER.from_payload(event.payload)
        if not isinstance(call, CallMessage):
            raise TypeError("calls topic must contain CallMessage payloads")
        if call.idempotency_key in seen:
            return
        seen.add(call.idempotency_key)
        executed.append(call.correlation_id)
        result = ResultMessage(
            status="OK",
            inline=call.args,
            handle=None,
            transfer="none",
            provenance=None,
            cost=CallCost(duration_ms=1),
            trace_id=call.trace_id,
            correlation_id=call.correlation_id,
            detail=None,
            current_category=None,
        )
        reply_bus = _LOCAL_REPLY_BUSES.get(call.reply_to or "", bus)
        await _emit(
            reply_bus,
            call.reply_to or "",
            SER.to_payload(result),
            correlation_id=call.correlation_id,
            metadata={
                "reply_to": call.reply_to or "",
                "idempotency_key": call.idempotency_key,
                "trace_id": call.trace_id,
            },
        )

    await bus.connect()
    return bus.subscribe(f"{PREFIX}server:calls", handle)


async def _wait_for(queue: asyncio.Queue[ResultMessage], count: int) -> list[ResultMessage]:
    """Collect a bounded number of asynchronous results from the caller bus."""
    return [await asyncio.wait_for(queue.get(), timeout=2) for _ in range(count)]


async def _wait_for_dlq() -> None:
    """Wait until EventBus records the deliberately failed result delivery."""
    for _ in range(40):
        if _DLQ:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("retry-exhausted reply was not sent to the DLQ callback")


async def run(url: str | None) -> dict[str, Any]:
    """Run the call/result, consumer-deduplication, and DLQ spike.

    Args:
        url: Redis URL for a real Streams run, or ``None`` for in-memory.

    Returns:
        Measured and asserted gate evidence.
    """
    _DLQ.clear()
    _LOCAL_REPLY_BUSES.clear()
    caller_bus = make_bus(url)
    server_bus = make_bus(url)
    big = secrets.token_bytes(1024 * 1024)
    calls = [new_call("idem-A", big), new_call("idem-A", big), new_call("idem-B", b"\x00\xff" * 8)]
    executed: list[str] = []
    results: asyncio.Queue[ResultMessage] = asyncio.Queue()

    async def receive(event: Any) -> None:
        """Decode caller-side replies and preserve their bytes for assertions."""
        result = SER.from_payload(event.payload)
        if not isinstance(result, ResultMessage):
            raise TypeError("reply topic must contain ResultMessage payloads")
        await results.put(result)

    async def reject_result(_event: Any) -> None:
        """Force an undeliverable result through EventBus retry/DLQ handling."""
        raise RuntimeError("deliberate undeliverable reply")

    try:
        await caller_bus.connect()
        for call in calls:
            _LOCAL_REPLY_BUSES[call.reply_to or ""] = caller_bus
            caller_bus.subscribe(call.reply_to or "", receive)
        bad_topic = f"{PREFIX}caller:replies:undeliverable"
        caller_bus.subscribe(bad_topic, reject_result)
        await serve(server_bus, executed, set())

        for call in calls:
            # MemoryBackend is per EventBus, so the no-Redis fallback injects
            # calls into the server's local dispatcher while preserving the
            # same envelope, metadata, and consumer code used by Streams.
            publisher = caller_bus if url else server_bus
            await _emit(
                publisher,
                f"{PREFIX}server:calls",
                SER.to_payload(call),
                correlation_id=call.correlation_id,
                metadata={
                    "reply_to": call.reply_to or "",
                    "idempotency_key": call.idempotency_key,
                    "trace_id": call.trace_id,
                },
            )

        received = await _wait_for(results, 2)
        assert len(executed) == 2
        assert {result.correlation_id for result in received} == set(executed)
        assert {result.inline for result in received} == {big, b"\x00\xff" * 8}

        bad_result = ResultMessage(
            status="OK",
            inline=b"undeliverable",
            handle=None,
            transfer="none",
            provenance=None,
            cost=CallCost(duration_ms=1),
            trace_id=uuid.uuid4().hex,
            correlation_id=uuid.uuid4().hex,
            detail=None,
            current_category=None,
        )
        await _emit(
            caller_bus,
            bad_topic,
            SER.to_payload(bad_result),
            correlation_id=bad_result.correlation_id,
            metadata={"reply_to": bad_topic, "idempotency_key": "dlq", "trace_id": bad_result.trace_id},
        )
        await _wait_for_dlq()
        return {
            "backend": "streams" if url else "memory",
            "executed": len(executed),
            "dlq": list(_DLQ),
            "base64_overhead_pct": round((len(json.dumps(SER.to_payload(calls[0]))) / len(big) - 1) * 100, 1),
        }
    finally:
        await server_bus.close()
        await caller_bus.close()
        _LOCAL_REPLY_BUSES.clear()


def main() -> int:
    """Run the spike using the optional Redis Streams URL."""
    print(json.dumps(asyncio.run(run(os.environ.get("SQUAWK_SPIKE_REDIS_URL"))), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
