"""SSE stream of the session principal's connection events (FEAT-777 M1)."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 25
_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@is_authenticated()
@user_session()
class ConnectionEventsHandler(BaseView):
    """``GET /api/v1/connections/events`` stream for the authenticated principal."""

    async def _get_user_id(self) -> str | None:
        """Extract the Navigator user id from request-managed session state only."""
        user_id: str | None = self.request.get("user_id")
        if not user_id:
            try:
                session = self.request.session if hasattr(self.request, "session") else None
                if session is None:
                    session = await get_session(self.request)
                if session is not None:
                    # Principal ids are Navigator user ids; a username/e-mail is never a principal key.
                    user_id = session.get("user_id") or session.get("id")
            except Exception:  # noqa: BLE001
                pass
        return str(user_id) if user_id else None

    async def get(self) -> web.StreamResponse:
        """Stream connection events and keep-alives until the client disconnects."""
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        push = self.request.app.get("connection_push")
        if push is None:
            return web.json_response({"error": "connection events unavailable"}, status=503)

        response = web.StreamResponse(status=200, headers=_SSE_HEADERS)
        await response.prepare(self.request)
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def _produce() -> None:
            async for event in push.subscribe(user_id):
                await queue.put(event.model_dump_json())

        producer = asyncio.create_task(_produce(), name="connection-events-sse")
        try:
            while True:
                if producer.done() and queue.empty():
                    try:
                        producer.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:  # noqa: BLE001
                        logger.warning("Connection event subscription ended unexpectedly", exc_info=True)
                    break

                try:
                    data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    if producer.done():
                        continue
                    await response.write(b": keep-alive\n\n")
                else:
                    frame = f"event: connection\ndata: {data}\n\n".encode()
                    await response.write(frame)
        except ConnectionResetError:
            logger.debug("Connection event stream client disconnected")
        finally:
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.debug("Connection event subscription cleanup failed", exc_info=True)
        return response
