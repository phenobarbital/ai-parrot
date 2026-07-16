"""Tests for WS/gRPC ingress adapters (FEAT-310, TASK-1791)."""
import asyncio
import json
import time

import pytest
from aiohttp import web

from parrot.core.events import Event, EventBus
from parrot.core.events.bus import Severity
from parrot.core.events.bus.ingress import WebSocketIngress
from parrot.core.hooks.base import BaseHook

TOKEN = "sekret-token"


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


@pytest.fixture
async def bus():
    b = EventBus()
    yield b
    await b.close()


@pytest.fixture
def ingress(bus):
    return WebSocketIngress(bus, auth_token=TOKEN)


@pytest.fixture
def app(ingress):
    application = web.Application()
    ingress.setup_routes(application)
    return application


# ---------------------------------------------------------------------------
# WebSocket ingress
# ---------------------------------------------------------------------------


def test_ws_ingress_is_a_base_hook(ingress):
    assert isinstance(ingress, BaseHook)


async def test_ws_ingress_valid_event_reaches_bus(aiohttp_client, bus, app):
    received: list[Event] = []

    async def observer(event):
        received.append(event)

    bus.subscribe("orders.*", observer)

    client = await aiohttp_client(app)
    ws = await client.ws_connect(f"/api/v1/events/ws?token={TOKEN}")
    await ws.send_json(
        {
            "topic": "orders.created",
            "payload": {"order_id": 7},
            "severity": Severity.WARNING.value,
            "source": "external-erp",
        }
    )
    ack = await ws.receive_json()
    assert ack["status"] == "accepted"
    assert ack["event_id"]

    await wait_until(lambda: len(received) == 1)
    event = received[0]
    assert event.event_type == "orders.created"
    assert event.payload == {"order_id": 7}
    assert event.source == "external-erp"
    assert event.timestamp.tzinfo is not None
    await ws.close()


async def test_ws_ingress_malformed_payload_rejected(aiohttp_client, bus, app):
    received: list[Event] = []
    bus.subscribe("*", lambda e: received.append(e))

    client = await aiohttp_client(app)
    ws = await client.ws_connect(f"/api/v1/events/ws?token={TOKEN}")

    # Not JSON at all.
    await ws.send_str("this is not json{{{")
    err = await ws.receive_json()
    assert err["status"] == "rejected"

    # Extra field — forbidden by IngressEnvelope (extra="forbid").
    await ws.send_json({"topic": "a.b", "nope": True})
    err = await ws.receive_json()
    assert err["status"] == "rejected"
    assert "nope" in err["error"]

    # Missing topic.
    await ws.send_json({"payload": {}})
    err = await ws.receive_json()
    assert err["status"] == "rejected"

    # The connection SURVIVES — a valid event still goes through.
    await ws.send_json({"topic": "a.b", "payload": {"ok": 1}})
    ack = await ws.receive_json()
    assert ack["status"] == "accepted"
    await wait_until(lambda: any(e.event_type == "a.b" for e in received))
    assert len([e for e in received if e.event_type == "a.b"]) == 1
    await ws.close()


async def test_ws_ingress_requires_auth(aiohttp_client, app):
    client = await aiohttp_client(app)
    # No token → 401 before the upgrade.
    resp = await client.get("/api/v1/events/ws")
    assert resp.status == 401
    # Wrong token → 401.
    resp = await client.get("/api/v1/events/ws?token=wrong")
    assert resp.status == 401
    # Bearer header works.
    ws = await client.ws_connect(
        "/api/v1/events/ws",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    await ws.close()


async def test_ws_ingress_no_token_configured_refuses_all(aiohttp_client, bus):
    ingress = WebSocketIngress(bus, auth_token="")
    application = web.Application()
    ingress.setup_routes(application)
    client = await aiohttp_client(application)
    resp = await client.get(f"{ingress.url}?token=anything")
    assert resp.status == 401  # auth required by default


async def test_ws_ingress_stop_closes_connections(aiohttp_client, bus, ingress, app):
    client = await aiohttp_client(app)
    ws = await client.ws_connect(f"/api/v1/events/ws?token={TOKEN}")
    await wait_until(lambda: len(ingress._websockets) == 1)
    await ingress.stop()
    assert ingress._websockets == set()
    msg = await ws.receive()
    assert msg.type.name in ("CLOSE", "CLOSING", "CLOSED")


# ---------------------------------------------------------------------------
# gRPC ingress (skips when grpc / generated modules are unavailable)
# ---------------------------------------------------------------------------

grpc = pytest.importorskip("grpc")


def _import_grpc_ingress():
    from parrot.core.events.bus.ingress.grpc import (
        GrpcIngress,
        validate_publish_request,
    )
    return GrpcIngress, validate_publish_request


def test_grpc_ingress_lazy_export():
    from parrot.core.events.bus import ingress as ingress_pkg
    GrpcIngress, _ = _import_grpc_ingress()
    assert ingress_pkg.GrpcIngress is GrpcIngress
    assert issubclass(GrpcIngress, BaseHook)


def test_grpc_validate_publish_request_boundary():
    _, validate_publish_request = _import_grpc_ingress()

    envelope = validate_publish_request(
        {
            "topic": "orders.created",
            "payload_json": json.dumps({"order_id": 7}),
            "severity": Severity.ERROR.value,
            "source": "grpc-client",
        }
    )
    assert envelope.topic == "orders.created"
    assert envelope.payload == {"order_id": 7}
    assert envelope.severity == Severity.ERROR

    with pytest.raises(ValueError):  # malformed JSON payload
        validate_publish_request({"topic": "a.b", "payload_json": "{{{"})
    with pytest.raises(ValueError):  # payload not an object
        validate_publish_request({"topic": "a.b", "payload_json": "[1,2]"})
    with pytest.raises(ValueError):  # missing topic
        validate_publish_request({"payload_json": "{}"})
    with pytest.raises(ValueError):  # bogus severity value
        validate_publish_request({"topic": "a.b", "severity": 999})


def test_grpc_priority_zero_is_low_not_default():
    """Explicit priority=0 (LOW) must survive; absent → NORMAL."""
    from parrot.core.events.evb import EventPriority
    _, validate_publish_request = _import_grpc_ingress()

    low = validate_publish_request({"topic": "a.b", "priority": 0})
    assert low.priority == EventPriority.LOW

    unset = validate_publish_request({"topic": "a.b", "priority": None})
    assert unset.priority == EventPriority.NORMAL

    # Proto-level presence: unset optional field maps to None server-side.
    from parrot.core.events.bus.ingress.proto import events_pb2
    explicit = events_pb2.PublishRequest(version="1.0", topic="a.b", priority=0)
    absent = events_pb2.PublishRequest(version="1.0", topic="a.b")
    assert explicit.HasField("priority") is True
    assert absent.HasField("priority") is False


async def test_grpc_ingress_publish_end_to_end(bus):
    """In-process grpc.aio server round-trip with auth + validation."""
    GrpcIngress, _ = _import_grpc_ingress()
    from parrot.core.events.bus.ingress.proto import (
        events_pb2,
        events_pb2_grpc,
    )

    received: list[Event] = []
    bus.subscribe("grpc.*", lambda e: received.append(e))

    ingress = GrpcIngress(bus, address="127.0.0.1:50961", auth_token=TOKEN)
    await ingress.start()
    try:
        async with grpc.aio.insecure_channel("127.0.0.1:50961") as channel:
            stub = events_pb2_grpc.EventBusIngressStub(channel)

            # Unauthenticated → UNAUTHENTICATED.
            with pytest.raises(grpc.aio.AioRpcError) as excinfo:
                await stub.Publish(
                    events_pb2.PublishRequest(version="1.0", topic="grpc.x")
                )
            assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED

            metadata = (("authorization", f"Bearer {TOKEN}"),)

            # Valid publish → accepted + arrives on the bus.
            resp = await stub.Publish(
                events_pb2.PublishRequest(
                    version="1.0",
                    topic="grpc.ping",
                    payload_json=json.dumps({"n": 1}),
                ),
                metadata=metadata,
            )
            assert resp.status == "accepted"
            assert resp.event_id
            await wait_until(lambda: len(received) == 1)
            assert received[0].event_type == "grpc.ping"

            # Malformed → rejected at the IngressEnvelope boundary.
            resp = await stub.Publish(
                events_pb2.PublishRequest(
                    version="1.0", topic="", payload_json="{}"
                ),
                metadata=metadata,
            )
            assert resp.status == "rejected"
    finally:
        await ingress.stop()
