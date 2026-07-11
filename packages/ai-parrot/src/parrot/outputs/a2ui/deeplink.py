"""Deep-link token service (Module 8, goal G6).

`requires_actions` components on static (baked) surfaces cannot dispatch actions in v1
(no ActionRouter — FEAT-B). Each action degrades to a **single-use, TTL-bound deep
link**: clicking it resumes the originating channel/session and injects the action as a
structured user message.

Token strategy (spec §8): navigator_auth exposes a JWT `create_token` mint, but binding
core to it would violate the one-way import rule (G8). This service therefore uses the
**pre-approved Redis opaque one-shot token** — an opaque `secrets.token_urlsafe(32)` id
whose server-side payload (session/user/agent/channel/action) is stored in Redis with a
TTL and deleted on first consume. The URL embeds ONLY the opaque id — never the payload
(spec §7). The Redis consume record is exactly the single-use/replay guard the spec
mandates regardless of mint source.

Copies the one-shot nonce machinery of ``parrot.auth.oauth2_base`` (key template,
``token_urlsafe(32)``, TTL ``set``, ``get`` → ``delete`` one-shot consume).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.outputs.a2ui.artifacts import DeepLink

__all__ = [
    "DeepLinkError",
    "DeepLinkExpiredError",
    "DeepLinkService",
    "ResumePayload",
]

logger = logging.getLogger(__name__)

_KEY_TEMPLATE = "a2ui:deeplink:{token_id}"
_DEFAULT_TTL_SECONDS = 15 * 60


class DeepLinkError(Exception):
    """Base class for deep-link errors."""


class DeepLinkExpiredError(DeepLinkError):
    """Raised when a token is missing, expired, or already consumed (single-use)."""


class ResumePayload(BaseModel):
    """Server-side payload restored when a deep link is consumed.

    Never serialized into the token URL — it lives only in Redis (spec §7).
    """

    session_id: str
    user_id: str
    agent_id: str
    channel: str
    action_payload: dict[str, Any] = Field(default_factory=dict)


class DeepLinkService:
    """Mints and consumes single-use, TTL-bound deep-link tokens.

    Args:
        redis: An async Redis client exposing ``set(key, value, ex=...)``, ``get(key)``,
            and ``delete(key)`` coroutines (injected — mirrors ``oauth2_base``).
        base_url: Base URL for building resume links (e.g. ``https://app.example``).
        default_ttl: Default token lifetime in seconds.
        key_template: Redis key template with a ``{token_id}`` placeholder.
    """

    def __init__(
        self,
        redis: Any,
        *,
        base_url: str = "",
        default_ttl: int = _DEFAULT_TTL_SECONDS,
        key_template: str = _KEY_TEMPLATE,
    ) -> None:
        self.redis = redis
        self.base_url = base_url.rstrip("/")
        self.default_ttl = default_ttl
        self.key_template = key_template
        self.logger = logging.getLogger(__name__)

    def _key(self, token_id: str) -> str:
        return self.key_template.format(token_id=token_id)

    def _resume_url(self, channel: str, token_id: str) -> str:
        return f"{self.base_url}/api/v1/a2ui/resume/{channel}?token={token_id}"

    async def mint(
        self,
        *,
        session_id: str,
        user_id: str,
        agent_id: str,
        channel: str,
        action_payload: dict[str, Any],
        ttl: Optional[int] = None,
    ) -> DeepLink:
        """Mint a single-use deep link for a degraded action.

        Args:
            session_id: Originating session id.
            user_id: Originating user id.
            agent_id: Originating agent id.
            channel: Channel to resume (e.g. ``"web"``, ``"telegram"``, ``"msteams"``).
            action_payload: The action to inject on resume (server-side only).
            ttl: Optional TTL override (seconds).

        Returns:
            A :class:`DeepLink` whose URL embeds only the opaque token id.
        """
        ttl = ttl or self.default_ttl
        token_id = secrets.token_urlsafe(32)
        payload = ResumePayload(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            channel=channel,
            action_payload=action_payload,
        )
        await self.redis.set(self._key(token_id), payload.model_dump_json(), ex=ttl)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        self.logger.debug("Minted A2UI deep link %s for session %s", token_id, session_id)
        return DeepLink(
            action_label=str(action_payload.get("label", "Open")),
            url=self._resume_url(channel, token_id),
            token_id=token_id,
            expires_at=expires_at,
        )

    async def consume(self, token: str) -> ResumePayload:
        """Consume a token exactly once, returning its server-side payload.

        Args:
            token: The opaque token id from the deep-link URL.

        Returns:
            The :class:`ResumePayload` stored at mint time.

        Raises:
            DeepLinkExpiredError: If the token is missing, expired, or already used.
        """
        key = self._key(token)
        # Prefer an ATOMIC read-and-delete (Redis >= 6.2 GETDEL) so two concurrent
        # consumes cannot both observe the token before it is deleted (single-use /
        # replay protection is TOCTOU-safe). Fall back to get-then-delete for clients
        # without GETDEL.
        getdel = getattr(self.redis, "getdel", None)
        if callable(getdel):
            raw = await getdel(key)
        else:
            raw = await self.redis.get(key)
            if raw is not None:
                await self.redis.delete(key)
        if not raw:
            # Expiry and replay are indistinguishable here by design (no oracle).
            raise DeepLinkExpiredError("This link has expired or was already used.")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ResumePayload(**json.loads(raw))
