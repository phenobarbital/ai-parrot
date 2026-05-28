"""HTTP handler for the OAuth2 integrations endpoints.

Exposes four routes under ``/api/v1/agents/integrations/{agent_id}``:

- ``GET    /api/v1/agents/integrations/{agent_id}``
  → list integrations for the current user.
- ``POST   /api/v1/agents/integrations/{agent_id}/{provider}/connect``
  → initiate the OAuth2 popup flow; returns auth_url + state nonce.
- ``POST   /api/v1/agents/integrations/{agent_id}/{provider}/enable``
  → confirm-enable after the popup completes; writes user_agent_toolkits.
- ``DELETE /api/v1/agents/integrations/{agent_id}/{provider}``
  → disconnect; deletes both persistence rows.

The handler delegates all business logic to
:class:`~parrot.integrations.oauth2.service.IntegrationsService`.
"""
from __future__ import annotations

import logging

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS
from parrot.auth.oauth2.service import IntegrationsService

logger = logging.getLogger(__name__)


@is_authenticated()
@user_session()
class IntegrationsHandler(BaseView):
    """Aiohttp class-based view for the OAuth2 integrations API.

    URL dispatch is performed by URL suffix inspection:
    - ``POST .../{provider}/connect`` → start OAuth2 flow.
    - ``POST .../{provider}/enable``  → confirm-enable after popup.
    - ``DELETE .../{provider}``       → disconnect.
    """

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
                    user_id = (
                        session.get("user_id")
                        or session.get("id")
                        or session.get("username")
                    )
            except Exception:  # noqa: BLE001
                pass
        return user_id

    async def get(self) -> web.Response:
        """``GET /api/v1/agents/integrations/{agent_id}`` — list integrations.

        Returns:
            JSON array of :class:`~parrot.integrations.oauth2.models.IntegrationDescriptor`
            objects for the authenticated user on the given agent.
        """
        agent_id: str = self.request.match_info["agent_id"]
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response(
                {"error": "Authenticated user not identified."}, status=401
            )

        svc = IntegrationsService()
        try:
            descriptors = await svc.list_for_user(
                user_id, agent_id, request=self.request
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error listing integrations for user=%s agent=%s", user_id, agent_id)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response([d.model_dump(mode="json") for d in descriptors])

    async def post(self) -> web.Response:
        """``POST`` dispatcher — routes to connect-init or confirm-enable.

        Dispatches by the last path segment:
        - ``…/{provider}/connect`` → :meth:`_post_connect`
        - ``…/{provider}/enable``  → :meth:`_post_enable`

        Returns:
            JSON response from the appropriate sub-handler.
        """
        path = self.request.path
        if path.endswith("/connect"):
            return await self._post_connect()
        if path.endswith("/enable"):
            return await self._post_enable()
        return web.json_response(
            {"error": "Unknown POST endpoint.  Use /connect or /enable."}, status=404
        )

    async def _post_connect(self) -> web.Response:
        """Handle ``POST .../integrations/{agent_id}/{provider}/connect``.

        Body (optional):
            ``{"return_origin": "https://app.example.com"}``

        Falls back to ``request.headers["Origin"]`` when ``return_origin`` is
        absent from the body.  Returns HTTP 400 if neither is present.

        Returns:
            ``ConnectInitResponse`` JSON on success.
        """
        agent_id: str = self.request.match_info["agent_id"]
        provider: str = self.request.match_info["provider"]
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        # Parse optional body
        return_origin: str | None = None
        try:
            body = await self.request.json()
            return_origin = body.get("return_origin")
        except Exception:  # noqa: BLE001
            pass

        # Fallback to Origin header
        if not return_origin:
            return_origin = self.request.headers.get("Origin")

        if not return_origin:
            return web.json_response(
                {"error": "return_origin not provided in body or Origin header."},
                status=400,
            )

        # Validate origin server-side before hitting the service
        if return_origin not in WEB_OAUTH_ALLOWED_ORIGINS:
            return web.json_response(
                {"error": f"Origin {return_origin!r} is not in the allowed origins list."},
                status=400,
            )

        svc = IntegrationsService()
        try:
            resp = await svc.start_connect(user_id, agent_id, provider, return_origin)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error starting connect for user=%s provider=%s", user_id, provider)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(resp.model_dump(mode="json"))

    async def _post_enable(self) -> web.Response:
        """Handle ``POST .../integrations/{agent_id}/{provider}/enable``.

        Returns:
            ``EnableResponse`` JSON on success.  HTTP 409 when no credential
            exists for the user+provider.
        """
        agent_id: str = self.request.match_info["agent_id"]
        provider: str = self.request.match_info["provider"]
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        svc = IntegrationsService()
        try:
            descriptor = await svc.confirm_enable(user_id, agent_id, provider)
        except LookupError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error enabling integration for user=%s provider=%s", user_id, provider)
            return web.json_response({"error": str(exc)}, status=500)

        from parrot.auth.oauth2.models import EnableResponse

        return web.json_response(
            EnableResponse(integration=descriptor).model_dump(mode="json")
        )

    async def delete(self) -> web.Response:
        """Handle ``DELETE .../integrations/{agent_id}/{provider}``.

        Disconnects the provider: deletes both the ``users_integrations`` row
        and all ``user_agent_toolkits`` rows for the user+provider.

        Returns:
            ``DisconnectResponse`` JSON on success.
        """
        agent_id: str = self.request.match_info["agent_id"]
        provider: str = self.request.match_info["provider"]
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)

        svc = IntegrationsService()
        try:
            resp = await svc.disconnect(user_id, agent_id, provider)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error disconnecting provider=%s for user=%s", provider, user_id)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(resp.model_dump(mode="json"))
