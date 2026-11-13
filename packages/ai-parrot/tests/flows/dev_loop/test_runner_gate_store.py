"""Generic gate-store wiring for the dev-loop runner."""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.core.gates import GateError, GateErrorCode, GateHost, GateRecord
from parrot.flows.dev_loop.commands import resolve_gate_handler
from parrot.flows.dev_loop.runner import DevLoopRunner
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer


class FakeGateStore:
    """Small in-memory GateStore used to observe runner interactions."""

    def __init__(self) -> None:
        """Initialize an empty record mapping."""
        self.records: dict[str, GateRecord] = {}

    async def put(self, record: GateRecord) -> None:
        """Persist one record."""
        self.records[record.gate_id] = record

    async def get(self, gate_id: str) -> Optional[GateRecord]:
        """Return one record when present."""
        return self.records.get(gate_id)

    async def pending(self, owner: Optional[str] = None) -> list[GateRecord]:
        """Return pending records, optionally restricted to one owner."""
        return [
            record
            for record in self.records.values()
            if record.status == "pending" and (owner is None or record.owner == owner)
        ]


@pytest.mark.asyncio
async def test_resolve_gate_uses_generic_host_before_session_host() -> None:
    """The durable generic record and legacy session action resolve together."""
    runner = DevLoopRunner(MagicMock(), redis_url="redis://unused")
    store = FakeGateStore()
    runner._gate_host = GateHost(store)
    runner._xadd_envelope = AsyncMock(return_value=None)
    host = runner._register_host("run-store-resolve")
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="Review")

    envelope = await runner.resolve_gate(
        "run-store-resolve",
        gate_id,
        "approved",
        resolved_by="human:alice",
        comment="Looks good",
    )
    await runner._flush_actions_queue("run-store-resolve")

    assert store.records[gate_id].status == "approved"
    assert store.records[gate_id].resolved_by == "human:alice"
    assert envelope.action.type == "gate/resolved"
    assert host.state.gates[gate_id].status == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected_status", "expected_error"),
    [
        (GateErrorCode.NOT_FOUND, 404, "unknown_gate"),
        (GateErrorCode.NOT_PENDING, 409, "already_resolved"),
    ],
)
async def test_command_maps_generic_gate_errors(
    code: GateErrorCode,
    expected_status: int,
    expected_error: str,
) -> None:
    """The REST adapter maps stable generic gate error codes."""

    class FailingRunner:
        """Runner double that returns one configured generic failure."""

        async def resolve_gate(self, *args: object, **kwargs: object) -> None:
            """Raise the configured generic gate failure."""
            raise GateError(code, "gate failure")

        def get_host(self, run_id: str) -> None:
            """Return no live session host for the synthetic failure."""
            return None

    request = MagicMock()
    request.app = {"dev_loop_runner": FailingRunner()}
    request.match_info = {"run_id": "run-errors", "gate_id": "gate-errors"}
    request.json = AsyncMock(
        return_value={"resolution": "approved", "resolved_by": "human:alice"}
    )

    response = await resolve_gate_handler(request)

    assert response.status == expected_status
    assert f'"error": "{expected_error}"'.encode() in response.body


@pytest.mark.asyncio
async def test_attach_recovers_elapsed_gate() -> None:
    """Elapsed durable gates and their attached session state recover together."""
    runner = DevLoopRunner(MagicMock())
    store = FakeGateStore()
    runner._gate_host = GateHost(store)
    host = runner._register_host("run-store-recover")
    gate_id, _ = host.open_gate(
        kind="deployment_approval",
        node_id="deployment_handoff",
        title="Deploy",
        ttl_seconds=10,
        on_expiry="fail",
    )
    record = host._gate_store.records[gate_id]
    await store.put(record)
    recovery_time = (record.expires_at or 0) + 1

    await runner._attach_gate_host(host, now=recovery_time)

    assert store.records[gate_id].status == "expired"
    assert host.state.gates[gate_id].status == "expired"


@pytest.mark.asyncio
async def test_opened_gate_is_persisted_by_ordered_writer() -> None:
    """The actions writer mirrors gate-open state into the durable store."""
    runner = DevLoopRunner(MagicMock(), redis_url="redis://unused")
    store = FakeGateStore()
    runner._gate_host = GateHost(store)
    runner._xadd_envelope = AsyncMock(return_value=None)
    host = runner._register_host("run-store-open")
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="Review")

    await runner._flush_actions_queue("run-store-open")

    assert store.records[gate_id].status == "pending"


def test_streaming_exposes_owned_redis_client() -> None:
    """Store wiring can reuse the multiplexer client without format changes."""
    redis_client = object()
    multiplexer = FlowStreamMultiplexer(redis_client, run_id="run-stream")

    assert multiplexer.redis_client is redis_client
