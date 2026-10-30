"""Principal-level connections API (FEAT-773 M6): /api/v1/connections*."""

from __future__ import annotations

import logging

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

from parrot.auth.oauth2.service import IntegrationsService

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
        service = IntegrationsService()
        try:
            response = await service.start_connect(
                user_id,
                provider,
                body.get("return_origin"),
                scopes=body.get("scopes"),
                request=self.request,
            )
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
