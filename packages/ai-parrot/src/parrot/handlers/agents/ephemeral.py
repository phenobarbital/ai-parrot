"""HTTP handler for ephemeral user agent lifecycle (FEAT-149 TASK-1040).

Exposes four routes for the ephemeral agent workflow:

    POST   /api/v1/agents/user/                   — create (fire-and-forget warm-up)
    GET    /api/v1/agents/user/{chatbot_id}/status — warm-up polling
    PUT    /api/v1/agents/user/{chatbot_id}        — promote to persistent
    DELETE /api/v1/agents/user/{chatbot_id}        — discard / delete

All routes enforce per-user ownership via session-based ``user_id``.
Routes are wired in TASK-1041 (route registration).
"""
from __future__ import annotations

import contextlib
import json as _json
import os
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import web
from navconfig.logging import logging
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
from navigator_session import get_session


_logger = logging.getLogger("Parrot.EphemeralUserAgentHandler")


@is_authenticated()
@user_session()
class EphemeralUserAgentHandler(BaseView):
    """Handler for the ephemeral user agent lifecycle.

    Delegates all state mutations to ``BotManager``, which is accessed via
    ``self.request.app['bot_manager']``.
    """

    _logger_name: str = "Parrot.EphemeralUserAgentHandler"

    def post_init(self, *args, **kwargs) -> None:
        """Initialise the instance logger."""
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # Session / auth helpers
    # ------------------------------------------------------------------

    async def _get_session(self) -> Any:
        """Return the current aiohttp session.

        Returns:
            The session object, or ``None`` if unavailable.
        """
        with contextlib.suppress(AttributeError):
            return self.request.session or await get_session(self.request)
        return await get_session(self.request)

    async def _resolve_user_id(self) -> Optional[int]:
        """Return the authenticated user_id from the session.

        Returns:
            ``int`` user_id on success, ``None`` if unauthenticated.
        """
        session = await self._get_session()
        if session is None:
            return None
        return session.get("user_id")

    # ------------------------------------------------------------------
    # Request parsing (inline — mirrors UserAgentHandler helpers)
    # ------------------------------------------------------------------

    async def _parse_request(self) -> Tuple[Dict[str, Any], List[Tuple[str, str, str]]]:
        """Parse JSON or multipart/form-data request body.

        Returns:
            Tuple of ``(config_dict, uploads)`` where *uploads* is a list of
            ``(field_name, original_filename, tmp_path)`` tuples.
        """
        content_type = (self.request.content_type or "").lower()
        if content_type.startswith("multipart/"):
            return await self._parse_multipart()
        try:
            data = await self.request.json()
        except Exception:  # noqa: BLE001
            data = {}
        return data, []

    async def _parse_multipart(
        self,
    ) -> Tuple[Dict[str, Any], List[Tuple[str, str, str]]]:
        """Stream multipart/form-data parts.

        Expects a ``config`` JSON part plus optional ``files[]`` file parts.

        Returns:
            ``(config_dict, list_of_(field, filename, tmp_path))``
        """
        import tempfile as _tempfile  # noqa: PLC0415

        config: Dict[str, Any] = {}
        uploads: List[Tuple[str, str, str]] = []

        def _cleanup() -> None:
            for _, _, tp in uploads:
                with contextlib.suppress(OSError):
                    if os.path.exists(tp):
                        os.unlink(tp)

        try:
            reader = await self.request.multipart()
            async for part in reader:
                if part is None:
                    break
                field_name = part.name
                filename = part.filename
                if filename:
                    suffix = os.path.splitext(filename)[1]
                    fd, tmp_path = _tempfile.mkstemp(suffix=suffix)
                    try:
                        with os.fdopen(fd, "wb") as out:
                            while True:
                                chunk = await part.read_chunk()
                                if not chunk:
                                    break
                                out.write(chunk)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            if os.path.exists(tmp_path):
                                os.unlink(tmp_path)
                        raise
                    uploads.append((field_name or "files", filename, tmp_path))
                else:
                    value = await part.text()
                    if field_name == "config":
                        try:
                            config = _json.loads(value)
                        except Exception:
                            _cleanup()
                            return {}, []
                    else:
                        config[field_name] = value
        except BaseException:
            _cleanup()
            raise
        return config, uploads

    # ------------------------------------------------------------------
    # BotManager accessor
    # ------------------------------------------------------------------

    def _bot_manager(self):
        """Return the BotManager instance from the aiohttp Application.

        Returns:
            The ``BotManager`` instance, or ``None`` if not configured.
        """
        return self.request.app.get("bot_manager")

    # ------------------------------------------------------------------
    # POST — create ephemeral agent
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Create an ephemeral user agent (fire-and-forget warm-up).

        Accepts ``application/json`` or ``multipart/form-data`` (config JSON
        part + optional ``files[]`` parts).

        Returns:
            HTTP 201 with ``{chatbot_id, status: "creating"}`` on success.
            HTTP 401 if unauthenticated.
            HTTP 500 on unexpected error.
        """
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        try:
            config, uploads = await self._parse_request()
            manager = self._bot_manager()
            if manager is None:
                return self.error("BotManager unavailable.", status=503)

            # Fire-and-forget: create_ephemeral_user_bot schedules _warm_up
            # as an asyncio background task and returns immediately.
            status = await manager.create_ephemeral_user_bot(
                user_id=user_id,
                config=config,
                uploaded_paths=[
                    {"field": field, "name": name, "path": path}
                    for field, name, path in uploads
                ],
            )
            return self.json_response(
                {
                    "chatbot_id": status.chatbot_id,
                    "status": status.phase,
                },
                status=201,
            )
        except ValueError as exc:
            # FIX-11: client config errors return 400, not 500
            return self.error(f"Invalid agent configuration: {exc}", status=400)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("POST ephemeral: unexpected error: %s", exc, exc_info=True)
            return self.error("Internal server error.", status=500)

    # ------------------------------------------------------------------
    # GET — warm-up status polling
    # ------------------------------------------------------------------

    async def get(self) -> web.Response:
        """Return the warm-up status for an ephemeral agent.

        URL param: ``{chatbot_id}``

        Returns:
            HTTP 200 with ``{chatbot_id, phase, progress, error}``.
            HTTP 401 if unauthenticated.
            HTTP 404 if not found or not owned by the requesting user.
        """
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        chatbot_id = self.request.match_info.get("chatbot_id")
        if not chatbot_id:
            return self.error("Missing chatbot_id.", status=400)

        manager = self._bot_manager()
        if manager is None:
            return self.error("BotManager unavailable.", status=503)

        ep_status = manager.get_ephemeral_status(chatbot_id, user_id)
        if ep_status is None:
            return self.error("Ephemeral agent not found.", status=404)

        return self.json_response(
            {
                "chatbot_id": ep_status.chatbot_id,
                "phase": ep_status.phase,
                "progress": ep_status.progress,
                "error": ep_status.error,
            }
        )

    # ------------------------------------------------------------------
    # PUT — promote ephemeral agent to persistent
    # ------------------------------------------------------------------

    async def put(self) -> web.Response:
        """Promote an ephemeral agent to a persistent DB row.

        The agent must be in ``phase == "ready"`` before promotion is allowed.

        URL param: ``{chatbot_id}``

        Returns:
            HTTP 200 with the persisted ``UserBotModel`` payload.
            HTTP 401 if unauthenticated.
            HTTP 404 if not found.
            HTTP 409 if the agent is not in ``"ready"`` phase.
            HTTP 500 on unexpected error.
        """
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        chatbot_id = self.request.match_info.get("chatbot_id")
        if not chatbot_id:
            return self.error("Missing chatbot_id.", status=400)

        manager = self._bot_manager()
        if manager is None:
            return self.error("BotManager unavailable.", status=503)

        # Check that the agent exists and is ready before handing off to BotManager.
        ep_status = manager.get_ephemeral_status(chatbot_id, user_id)
        if ep_status is None:
            return self.error("Ephemeral agent not found.", status=404)
        if ep_status.phase != "ready":
            return self.error(
                f"Agent is not ready for promotion (phase={ep_status.phase!r}).",
                status=409,
            )

        try:
            user_bot = await manager.promote_user_bot(chatbot_id, user_id)
        except ValueError as exc:
            # promote_user_bot raises ValueError if phase != "ready"
            return self.error(str(exc), status=409)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("PUT promote: %s", exc, exc_info=True)
            return self.error(f"Failed to promote agent: {exc}", status=500)

        # Serialise the UserBotModel to a plain dict for the response.
        try:
            payload = user_bot.to_dict() if hasattr(user_bot, "to_dict") else dict(user_bot)
        except Exception:  # noqa: BLE001
            payload = {"chatbot_id": str(getattr(user_bot, "chatbot_id", chatbot_id))}

        return self.json_response(payload)

    # ------------------------------------------------------------------
    # DELETE — discard ephemeral or delete persistent
    # ------------------------------------------------------------------

    async def delete(self) -> web.Response:
        """Discard an ephemeral agent or delete a persisted one.

        Ephemeral: removed from in-memory registry and ``BotManager._bots``.
        Persistent: currently returns 404 (persistent delete remains with
        ``UserAgentHandler``).

        URL param: ``{chatbot_id}``

        Returns:
            HTTP 204 on success.
            HTTP 401 if unauthenticated.
            HTTP 404 if not found.
        """
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        chatbot_id = self.request.match_info.get("chatbot_id")
        if not chatbot_id:
            return self.error("Missing chatbot_id.", status=400)

        manager = self._bot_manager()
        if manager is None:
            return self.error("BotManager unavailable.", status=503)

        # Try ephemeral discard first
        discarded = await manager.discard_ephemeral_user_bot(chatbot_id, user_id)
        if discarded:
            return web.Response(status=204)

        # Not in the ephemeral registry — agent may have been promoted already
        # (persistent agents are managed by UserAgentHandler).
        return self.error(
            "Ephemeral agent not found. Use UserAgentHandler to delete persisted agents.",
            status=404,
        )
