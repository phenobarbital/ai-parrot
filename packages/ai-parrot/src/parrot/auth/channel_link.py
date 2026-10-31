"""Single-use channel-link nonces (FEAT-777 M2, D2).

A nonce binds *which* channel user is being linked; the Navigator principal always comes from the
authenticated web session that confirms it.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_KEY_PREFIX = "channel_link:"
_SECRET_KEYS = frozenset({"access_token", "refresh_token", "id_token", "token", "client_secret"})


class ChannelLinkClaim(BaseModel):
    """The channel identity a link nonce stands for."""

    channel: str
    channel_user_id: str
    extra: Dict[str, str] = Field(default_factory=dict)
    issued_at: float


class ChannelLinkIssuer:
    """Redis key ``channel_link:{nonce}``, TTL ``ttl_seconds``, ``GETDEL`` on consume."""

    def __init__(self, redis_client: Any, *, base_url: str, ttl_seconds: int = 600) -> None:
        self._redis = redis_client
        self._base_url = (base_url or "").rstrip("/")
        self._ttl = int(ttl_seconds)
        self.logger = logger

    async def issue(self, channel: str, channel_user_id: str, extra: Optional[Dict[str, str]] = None) -> str:
        """Store a claim and return ``{base_url}/account/link?token={nonce}``.

        Raises:
            ValueError: Empty channel, channel user ID, or base URL, or a secret-looking key in ``extra``.
        """
        if not channel:
            raise ValueError("channel must not be empty")
        if not channel_user_id:
            raise ValueError("channel_user_id must not be empty")
        if not self._base_url:
            raise ValueError("base_url must not be empty")

        claim_extra = extra or {}
        forbidden_keys = _SECRET_KEYS.intersection(claim_extra)
        if forbidden_keys:
            raise ValueError("extra must not contain secret keys")

        claim = ChannelLinkClaim(
            channel=channel,
            channel_user_id=channel_user_id,
            extra=claim_extra,
            issued_at=time.time(),
        )
        while True:
            nonce = secrets.token_urlsafe(32)
            stored = await self._redis.set(
                f"{_KEY_PREFIX}{nonce}",
                claim.model_dump_json(),
                ex=self._ttl,
                nx=True,
            )
            if stored:
                return f"{self._base_url}/account/link?token={nonce}"

    async def peek(self, nonce: str) -> Optional[ChannelLinkClaim]:
        """Read without deletion or TTL extension; ``None`` when missing or expired."""
        if not nonce:
            return None
        raw = await self._redis.get(f"{_KEY_PREFIX}{nonce}")
        return self._parse(raw)

    async def consume(self, nonce: str) -> Optional[ChannelLinkClaim]:
        """Single use: ``None`` when missing, expired or already consumed."""
        if not nonce:
            return None
        raw = await self._redis.getdel(f"{_KEY_PREFIX}{nonce}")
        return self._parse(raw)

    def _parse(self, raw: Any) -> Optional[ChannelLinkClaim]:
        """Decode bytes/str JSON into a claim; malformed values are logged and ignored."""
        if raw is None:
            return None
        try:
            payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return ChannelLinkClaim.model_validate_json(payload)
        except (TypeError, ValueError, UnicodeDecodeError):
            self.logger.warning("Ignoring malformed channel-link claim")
            return None
