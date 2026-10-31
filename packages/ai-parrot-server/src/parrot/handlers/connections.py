"""Principal-level connections API (FEAT-773 M6): /api/v1/connections*."""

from __future__ import annotations

import logging

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

from parrot.auth.oauth2.models import NotConnected
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal

logger = logging.getLogger(__name__)


@is_authenticated()
@user_session()
class ConnectionsHandler(BaseView):
    """Serve a principal's OAuth connections using only session identity."""

    async def _get_user_id(self) -> str | None:
        """Extract the authenticated user's identifier from the request session.

        Returns:
            The user ID string, or ``None`` if not available.
        """
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

    def _route_suffix(self) -> str:
        """Return the path tail after ``/{provider}/``, or an empty string."""
        provider = self.request.match_info.get("provider")
        if not provider:
            return ""
        marker = f"/{provider}/"
        path = self.request.path.rstrip("/")
        return path.split(marker, 1)[1] if marker in path else ""

    def _is_me_route(self) -> bool:
        """Return whether this request targets ``GET /api/v1/connections/me``."""
        return not self.request.match_info.get("provider") and self.request.path.rstrip("/").endswith("/connections/me")

    def _is_start_route(self) -> bool:
        """True for ``/connections/{provider}/start`` (POST-only)."""
        provider = self.request.match_info.get("provider")
        return bool(provider) and self.request.path.rstrip("/").endswith(f"/{provider}/start")

    async def get(self) -> web.Response:
        """List all connections, or return one provider's connection status.

        Returns:
            A JSON response containing serialized integration descriptors.
        """
        if self._is_start_route():
            return web.json_response({"error": "method not allowed"}, status=405)
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        if self._is_me_route():
            try:
                who = await IntegrationsService().whoami(user_id, request=self.request)
            except Exception:  # noqa: BLE001
                logger.exception("Error resolving whoami for user=%s", user_id)
                return web.json_response({"error": "internal_error"}, status=500)
            return web.json_response(who.model_dump(mode="json"))

        provider = self.request.match_info.get("provider")
        service = IntegrationsService()
        try:
            if provider:
                descriptor = await service.status(user_id, provider, request=self.request)
                return web.json_response(descriptor.model_dump(mode="json"))
            descriptors = await service.list_for_principal(user_id, request=self.request)
            return web.json_response([descriptor.model_dump(mode="json") for descriptor in descriptors])
        except PermissionError:
            return web.json_response({"error": "forbidden"}, status=403)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:  # noqa: BLE001
            logger.exception("Error listing connections for user=%s", user_id)
            return web.json_response({"error": "internal_error"}, status=500)

    async def post(self) -> web.Response:
        """Start an OAuth connection flow for the requested provider.

        Returns:
            A JSON response containing the connection initialization payload.
        """
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        body: dict = {}
        try:
            parsed_body = await self.request.json()
            if isinstance(parsed_body, dict):
                body = parsed_body
        except Exception:  # noqa: BLE001
            pass

        provider = self.request.match_info["provider"]
        suffix = self._route_suffix()
        service = IntegrationsService()
        try:
            if suffix == "token":
                pulled = await service.pull_access_token(user_id, provider, request=self.request)
                return web.json_response(pulled.model_dump(mode="json"))
            if suffix == "complete":
                code = body.get("code")
                state = body.get("state")
                if not isinstance(code, str) or not isinstance(state, str):
                    return web.json_response({"error": "code and state are required"}, status=400)
                response = await service.complete_connect(
                    user_id,
                    provider,
                    code=code,
                    state=state,
                    channel="cli",
                    request=self.request,
                )
                return web.json_response(response.model_dump(mode="json"))
            if suffix == "device/start":
                principal = Principal(user_id=user_id, channel="cli", channel_user_id=user_id)
                started = await service.device_start(
                    user_id,
                    provider,
                    principal=principal,
                    request=self.request,
                    scopes=body.get("scopes"),
                )
                return web.json_response(started)
            if suffix == "device/poll":
                handle = body.get("handle")
                if not isinstance(handle, str) or not handle:
                    return web.json_response({"error": "handle is required"}, status=400)
                return web.json_response(
                    await service.device_poll(user_id, provider, handle=handle, request=self.request)
                )

            channel = body.get("channel", "web")
            if channel not in {"web", "cli"}:
                return web.json_response({"error": "unsupported channel"}, status=400)
            if channel == "cli":
                principal = Principal(user_id=user_id, channel="cli", channel_user_id=user_id)
                response = await service.start_connect(
                    user_id,
                    provider,
                    None,
                    channel="cli",
                    principal=principal,
                    scopes=body.get("scopes"),
                    request=self.request,
                )
            else:
                response = await service.start_connect(
                    user_id,
                    provider,
                    body.get("return_origin"),
                    scopes=body.get("scopes"),
                    request=self.request,
                )
        except NotConnected as exc:
            return web.json_response(exc.payload.model_dump(mode="json", exclude_none=True), status=409)
        except PermissionError:
            return web.json_response({"error": "forbidden"}, status=403)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:  # noqa: BLE001
            logger.exception("Error starting connection for user=%s provider=%s", user_id, provider)
            return web.json_response({"error": "internal_error"}, status=500)

        return web.json_response(response.model_dump(mode="json"))

    async def delete(self) -> web.Response:
        """Disconnect the authenticated principal from the requested provider.

        Returns:
            A JSON response containing the disconnect result.
        """
        if self._is_start_route():
            return web.json_response({"error": "method not allowed"}, status=405)
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        provider = self.request.match_info["provider"]
        service = IntegrationsService()
        try:
            response = await service.disconnect(user_id, provider, request=self.request)
        except PermissionError:
            return web.json_response({"error": "forbidden"}, status=403)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:  # noqa: BLE001
            logger.exception("Error disconnecting provider=%s for user=%s", provider, user_id)
            return web.json_response({"error": "internal_error"}, status=500)

        return web.json_response(response.model_dump(mode="json"))
