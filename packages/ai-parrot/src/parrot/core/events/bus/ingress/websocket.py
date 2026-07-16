"""WebSocketIngress — aiohttp WebSocket ingress on the BaseHook contract.

FEAT-310 Module 9 (goal G5). External systems push events over a WebSocket;
every inbound JSON message is validated at the
:class:`~parrot.core.events.bus.ingress_models.IngressEnvelope` Pydantic
boundary (``extra="forbid"``) before reaching the bus. Malformed input is
rejected with a structured error frame — the connection stays open.

Auth is REQUIRED by default: a token must be configured (constructor kwarg
or navconfig ``BUS_INGRESS_TOKEN``) and presented via the
``Authorization: Bearer <token>`` header, an ``X-API-Key`` header, or a
``?token=`` query parameter. Unauthenticated upgrades are refused with 401.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from aiohttp import WSMsgType, web
from navconfig import config as nav_config

from parrot.core.events import EventBus
from parrot.core.events.bus.ingress_models import IngressEnvelope
from parrot.core.hooks.base import BaseHook


class WebSocketIngress(BaseHook):
    """WebSocket ingress adapter publishing validated events to the bus.

    Registers ``GET <url>`` via :meth:`setup_routes` (the standard
    HTTP-hook contract) and can be managed by ``HookManager.register()``
    like any other hook.

    Args:
        bus: The :class:`EventBus` facade to publish through.
        url: Route path for the WebSocket endpoint.
        auth_token: Shared token required from clients. Falls back to
            navconfig ``BUS_INGRESS_TOKEN``; when NO token is configured,
            every connection is refused (auth required by default).
        name: Hook name (BaseHook).
        **kwargs: Forwarded to :class:`BaseHook`.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        url: str = "/api/v1/events/ws",
        auth_token: Optional[str] = None,
        name: str = "websocket_ingress",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self._bus = bus
        self.url = url
        self._auth_token = (
            auth_token
            if auth_token is not None
            else nav_config.get("BUS_INGRESS_TOKEN", fallback=None)
        )
        self._websockets: set[web.WebSocketResponse] = set()

    # ------------------------------------------------------------------
    # BaseHook contract
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Mark the ingress ready (routes attach via ``setup_routes``)."""
        if not self._auth_token:
            self.logger.warning(
                "WebSocketIngress '%s' has NO auth token configured "
                "(BUS_INGRESS_TOKEN) — all connections will be refused.",
                self.name,
            )
        self.logger.info(
            "WebSocketIngress '%s' ready (routes via setup_routes)", self.name
        )

    async def stop(self) -> None:
        """Close every open client connection."""
        for ws in list(self._websockets):
            try:
                await ws.close(code=1001, message=b"server shutdown")
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("WS close error: %s", exc)
        self._websockets.clear()
        self.logger.info("WebSocketIngress '%s' stopped", self.name)

    def setup_routes(self, app: Any) -> None:
        """Register the WebSocket endpoint on the aiohttp app."""
        app.router.add_get(self.url, self._handle_ws)
        self.logger.info("WebSocket ingress route registered: GET %s", self.url)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def _authorized(self, request: web.Request) -> bool:
        """Check the shared token (header bearer / X-API-Key / query)."""
        if not self._auth_token:
            return False  # auth required by default — no token, no entry
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == self._auth_token:
            return True
        if request.headers.get("X-API-Key") == self._auth_token:
            return True
        return request.query.get("token") == self._auth_token

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        """Upgrade, then validate/publish every TEXT frame."""
        if not self._authorized(request):
            return web.Response(status=401, text="Unauthorized")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._websockets.add(ws)
        self.logger.debug("WS ingress client connected")
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._process_message(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    self.logger.warning(
                        "WS ingress connection error: %s", ws.exception()
                    )
                    break
        finally:
            self._websockets.discard(ws)
            self.logger.debug("WS ingress client disconnected")
        return ws

    async def _process_message(
        self, ws: web.WebSocketResponse, raw: str
    ) -> None:
        """Validate one frame at the IngressEnvelope boundary and publish."""
        try:
            data = json.loads(raw)
            ingress = IngressEnvelope.model_validate(data)
        except Exception as exc:  # noqa: BLE001 — reject, keep connection
            await ws.send_json(
                {"status": "rejected", "error": f"{type(exc).__name__}: {exc}"}
            )
            return
        try:
            await self._bus.emit(
                ingress.topic,
                ingress.payload,
                event_id=ingress.event_id,
                timestamp=ingress.timestamp,
                source=ingress.source or f"ws:{self.hook_id}",
                priority=ingress.priority,
                correlation_id=ingress.correlation_id,
                metadata=ingress.metadata,
                severity=ingress.severity,
            )
        except Exception as exc:  # noqa: BLE001 — bus failure surfaces
            self.logger.error("WS ingress publish failed: %s", exc)
            await ws.send_json(
                {"status": "error", "error": "internal publish failure"}
            )
            return
        await ws.send_json(
            {"status": "accepted", "event_id": ingress.event_id}
        )
