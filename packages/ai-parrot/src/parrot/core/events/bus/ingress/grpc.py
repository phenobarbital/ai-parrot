"""GrpcIngress — gRPC ingress adapter on the BaseHook contract.

FEAT-310 Module 9 (goal G5). Serves ``parrot.events.v1.EventBusIngress``
(see ``proto/events.proto`` — the message shape mirrors the A2UI
versioned-message envelope: explicit ``version`` field + typed payload).

``grpcio`` is an OPTIONAL dependency: install with
``pip install ai-parrot[grpc]``. Importing this module without it raises a
helpful ImportError; ``parrot.core.events.bus.ingress`` exposes
``GrpcIngress`` lazily so the core package never requires grpc.

Every request is validated at the
:class:`~parrot.core.events.bus.ingress_models.IngressEnvelope` Pydantic
boundary before reaching the bus; auth failures abort with UNAUTHENTICATED,
validation failures return a structured ``status="rejected"`` response.
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime
from typing import Any, Optional

from navconfig import config as nav_config

from parrot.core.events import EventBus
from parrot.core.events.bus.ingress_models import IngressEnvelope
from parrot.core.hooks.base import BaseHook

_GRPC_INSTALL_HINT = (
    "GrpcIngress requires the optional gRPC extra. "
    "Install it with: pip install ai-parrot[grpc]"
)

try:
    import grpc
    from grpc import aio as grpc_aio
except ImportError as _exc:  # pragma: no cover - depends on environment
    raise ImportError(_GRPC_INSTALL_HINT) from _exc

try:
    from parrot.core.events.bus.ingress.proto import (
        events_pb2,
        events_pb2_grpc,
    )
except ImportError as _exc:  # pragma: no cover - regen instructions
    raise ImportError(
        "parrot.events.v1 generated modules are missing. Regenerate them "
        "with grpcio-tools (see parrot/core/events/bus/ingress/proto/"
        "README.md) or reinstall ai-parrot[grpc]."
    ) from _exc

PROTOCOL_VERSION = "1.0"


def validate_publish_request(data: dict[str, Any]) -> IngressEnvelope:
    """Validate a PublishRequest-shaped dict at the Pydantic boundary.

    Args:
        data: Mapping with the proto fields (``topic``, ``payload_json``,
            optional ``event_id``/``timestamp``/``source``/``severity``/
            ``priority``/``correlation_id``/``metadata_json``/
            ``trace_context_json``).

    Returns:
        The validated :class:`IngressEnvelope`.

    Raises:
        ValueError: On malformed JSON fields or failed validation
            (message carries the reason).
    """
    def _json_field(key: str) -> Optional[dict[str, Any]]:
        raw = data.get(key)
        if not raw:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{key} must be a JSON object")
        return parsed

    try:
        payload = _json_field("payload_json") or {}
        metadata = _json_field("metadata_json") or {}
        trace_context = _json_field("trace_context_json")
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON field: {exc}") from exc

    envelope_kwargs: dict[str, Any] = {
        "topic": data.get("topic", ""),
        "payload": payload,
        "metadata": metadata,
    }
    if trace_context is not None:
        envelope_kwargs["trace_context"] = trace_context
    if data.get("event_id"):
        envelope_kwargs["event_id"] = data["event_id"]
    if data.get("timestamp"):
        try:
            envelope_kwargs["timestamp"] = datetime.fromisoformat(
                data["timestamp"]
            )
        except ValueError as exc:
            raise ValueError(f"invalid timestamp: {exc}") from exc
    if data.get("source"):
        envelope_kwargs["source"] = data["source"]
    # `is not None` (NOT truthiness): priority=0 is a valid explicit LOW.
    if data.get("severity") is not None:
        envelope_kwargs["severity"] = data["severity"]
    if data.get("priority") is not None:
        envelope_kwargs["priority"] = data["priority"]
    if data.get("correlation_id"):
        envelope_kwargs["correlation_id"] = data["correlation_id"]

    try:
        return IngressEnvelope.model_validate(envelope_kwargs)
    except Exception as exc:  # pydantic.ValidationError and friends
        raise ValueError(str(exc)) from exc


class _EventBusIngressServicer(events_pb2_grpc.EventBusIngressServicer):
    """gRPC servicer delegating to the owning :class:`GrpcIngress`."""

    def __init__(self, ingress: "GrpcIngress") -> None:
        self._ingress = ingress

    async def Publish(self, request: Any, context: Any) -> Any:
        """Handle one PublishRequest (auth → validate → bus publish)."""
        if not self._ingress._authorized(context):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED, "invalid or missing token"
            )
        data = {
            "topic": request.topic,
            "payload_json": request.payload_json,
            "event_id": request.event_id,
            "timestamp": request.timestamp,
            "source": request.source,
            # optional proto3 fields: explicit presence check so that
            # priority=0 (LOW) survives and "unset" maps to None.
            "severity": (
                request.severity if request.HasField("severity") else None
            ),
            "priority": (
                request.priority if request.HasField("priority") else None
            ),
            "correlation_id": request.correlation_id,
            "metadata_json": request.metadata_json,
            "trace_context_json": request.trace_context_json,
        }
        try:
            ingress_envelope = validate_publish_request(data)
        except ValueError as exc:
            # Application-level rejection: OK transport status so the
            # client always receives the structured PublishResponse.
            return events_pb2.PublishResponse(
                version=PROTOCOL_VERSION, status="rejected", error=str(exc)
            )
        await self._ingress._publish(ingress_envelope)
        return events_pb2.PublishResponse(
            version=PROTOCOL_VERSION,
            status="accepted",
            event_id=ingress_envelope.event_id,
        )


class GrpcIngress(BaseHook):
    """gRPC ingress adapter publishing validated events to the bus.

    Args:
        bus: The :class:`EventBus` facade to publish through.
        address: Bind address for the grpc.aio server.
        auth_token: Shared token required in the ``authorization`` metadata
            (``Bearer <token>``) or ``x-api-key``. Falls back to navconfig
            ``BUS_INGRESS_TOKEN``; with NO token configured, every call is
            refused (auth required by default).
        server_credentials: Optional ``grpc.ServerCredentials`` — when
            provided the port is bound with ``add_secure_port`` (TLS).

            ⚠️ Without credentials the port is INSECURE (cleartext): the
            bearer token travels unencrypted, so you MUST terminate TLS in
            front of this port (sidecar/LB) in any non-local deployment.
        name: Hook name (BaseHook).
        **kwargs: Forwarded to :class:`BaseHook`.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        address: str = "0.0.0.0:50061",
        auth_token: Optional[str] = None,
        server_credentials: Optional[Any] = None,
        name: str = "grpc_ingress",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self._bus = bus
        self.address = address
        self._auth_token = (
            auth_token
            if auth_token is not None
            else nav_config.get("BUS_INGRESS_TOKEN", fallback=None)
        )
        self._server_credentials = server_credentials
        self._server: Optional[grpc_aio.Server] = None

    async def start(self) -> None:
        """Start the grpc.aio server and bind the servicer."""
        if not self._auth_token:
            self.logger.warning(
                "GrpcIngress '%s' has NO auth token configured "
                "(BUS_INGRESS_TOKEN) — all calls will be refused.", self.name,
            )
        self._server = grpc_aio.server()
        events_pb2_grpc.add_EventBusIngressServicer_to_server(
            _EventBusIngressServicer(self), self._server
        )
        if self._server_credentials is not None:
            self._server.add_secure_port(self.address, self._server_credentials)
        else:
            self.logger.warning(
                "GrpcIngress '%s' binding INSECURE port %s — the bearer "
                "token travels in cleartext; terminate TLS in front of it "
                "or pass server_credentials.", self.name, self.address,
            )
            self._server.add_insecure_port(self.address)
        await self._server.start()
        self.logger.info("GrpcIngress '%s' listening on %s", self.name, self.address)

    async def stop(self) -> None:
        """Gracefully stop the grpc.aio server."""
        if self._server is not None:
            await self._server.stop(grace=2.0)
            self._server = None
        self.logger.info("GrpcIngress '%s' stopped", self.name)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _token_matches(self, candidate: Optional[str]) -> bool:
        """Constant-time comparison against the configured token."""
        if candidate is None:
            return False
        return hmac.compare_digest(
            candidate.encode("utf-8"), self._auth_token.encode("utf-8")
        )

    def _authorized(self, context: Any) -> bool:
        """Check the shared token in the invocation metadata."""
        if not self._auth_token:
            return False  # auth required by default
        metadata = dict(context.invocation_metadata() or ())
        auth = metadata.get("authorization", "")
        if auth.startswith("Bearer ") and self._token_matches(auth[7:]):
            return True
        return self._token_matches(metadata.get("x-api-key"))

    async def _publish(self, ingress: IngressEnvelope) -> None:
        """Publish a validated envelope through the facade."""
        await self._bus.emit(
            ingress.topic,
            ingress.payload,
            event_id=ingress.event_id,
            timestamp=ingress.timestamp,
            source=ingress.source or f"grpc:{self.hook_id}",
            priority=ingress.priority,
            correlation_id=ingress.correlation_id,
            metadata=ingress.metadata,
            severity=ingress.severity,
        )
