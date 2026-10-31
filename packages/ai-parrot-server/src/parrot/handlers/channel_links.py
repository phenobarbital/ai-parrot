"""Channel-link preview and explicit confirm (FEAT-777 M2, D2)."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

from parrot.auth.oauth2.models import ChannelLinkPreview
from parrot.services.identity_mapping import IdentityMappingService

logger = logging.getLogger(__name__)


@is_authenticated()
@user_session()
class ChannelLinksHandler(BaseView):
    """``GET /api/v1/channel-links/{nonce}`` preview; ``POST …/{nonce}/confirm`` claim."""

    async def _get_user_id(self) -> str | None:
        """Extract the authenticated user's Navigator identifier from the session."""
        user_id: str | None = self.request.get("user_id")
        if not user_id:
            try:
                session = self.request.session if hasattr(self.request, "session") else None
                if session is None:
                    session = await get_session(self.request)
                if session is not None:
                    user_id = session.get("user_id") or session.get("id")
            except Exception:  # noqa: BLE001
                pass
        return str(user_id) if user_id else None

    def _issuer(self) -> Any:
        """Return the configured channel-link issuer, if any."""
        return self.request.app.get("channel_link_issuer")

    async def get(self) -> web.Response:
        """Read-only preview; ``Cache-Control: no-store``; 410 when the claim is absent."""
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)
        issuer = self._issuer()
        if issuer is None:
            return web.json_response({"error": "account linking is not configured"}, status=503)
        claim = await issuer.peek(self.request.match_info.get("nonce", ""))
        if claim is None:
            return web.json_response({"error": "link expired"}, status=410, headers={"Cache-Control": "no-store"})

        team_id = claim.extra.get("team_id") or claim.channel_user_id.split(":", 1)[0]
        preview = ChannelLinkPreview(
            channel=claim.channel,
            channel_user_id=claim.channel_user_id,
            team_id=team_id,
            nav_user_id=user_id,
        )
        return web.json_response(preview.model_dump(mode="json"), headers={"Cache-Control": "no-store"})

    async def post(self) -> web.Response:
        """Explicit confirm; order: session, numeric id, body, consume, and exclusive claim."""
        if not self.request.path.rstrip("/").endswith("/confirm"):
            return web.json_response({"error": "method not allowed"}, status=405)

        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)
        if not user_id.isdigit():
            return web.json_response({"error": "invalid session user"}, status=403)

        try:
            body = await self.request.json()
        except Exception:  # noqa: BLE001
            body = None
        if not (
            isinstance(body, dict)
            and set(body) == {"confirm"}
            and type(body.get("confirm")) is bool
            and body["confirm"] is True
        ):
            return web.json_response({"error": "confirmation required"}, status=400)

        issuer = self._issuer()
        authdb = self.request.app.get("authdb")
        if issuer is None or authdb is None:
            return web.json_response({"error": "account linking is not configured"}, status=503)

        claim = await issuer.consume(self.request.match_info.get("nonce", ""))
        if claim is None:
            return web.json_response({"error": "link expired"}, status=410)
        if not self._valid_slack_claim(claim):
            return web.json_response({"error": "invalid channel link"}, status=400)

        team_id, slack_user_id = claim.channel_user_id.split(":", 1)
        try:
            result = await IdentityMappingService(authdb).claim_channel_identity(
                nav_user_id=user_id,
                auth_provider="slack",
                provider_user_id=claim.channel_user_id,
                auth_data={"team_id": team_id, "slack_user_id": slack_user_id},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error claiming channel identity")
            return web.json_response({"error": "internal_error"}, status=500)

        if result.status == "conflict":
            return web.json_response({"error": "already_linked"}, status=409)
        if result.status in {"claimed", "already_owned"}:
            return web.json_response({"channel": "slack", "linked": True})
        return web.json_response({"error": "internal_error"}, status=500)

    @staticmethod
    def _valid_slack_claim(claim: Any) -> bool:
        """Return whether a claim has a team-qualified Slack identity consistent with its metadata."""
        if claim.channel != "slack":
            return False
        parts = claim.channel_user_id.split(":")
        if len(parts) != 2 or not all(parts):
            return False
        team_id, slack_user_id = parts
        return claim.extra.get("team_id") == team_id and claim.extra.get("slack_user_id") == slack_user_id
