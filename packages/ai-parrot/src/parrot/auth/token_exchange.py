"""Exchange an external provider token for a Navigator session."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import aiohttp
from navconfig import config as navconfig_settings

logger = logging.getLogger(__name__)

#: Returned in ExchangeResult.reason. TASK-4662 and TASK-4663 branch on these.
REASON_OK = "ok"
REASON_USER_NOT_FOUND = "user_not_found"
REASON_BACKEND_NOT_LOADED = "backend_not_loaded"
REASON_INVALID_TOKEN = "invalid_token"
REASON_EXPIRED = "expired"
REASON_TRANSPORT = "transport_error"


@dataclass
class ExchangeResult:
    """Outcome of one exchange attempt."""

    ok: bool
    reason: str = REASON_OK
    nav_user_id: Optional[str] = None
    session_token: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    provider_user_id: Optional[str] = None
    expires_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


class TokenExchangeClient:
    """POST an external token to Navigator's TokenExchangeAuth backend.

    Proven end to end in sdd/state/FEAT-729/poc/exchange_run.transcript.md.
    """

    def __init__(self, auth_url: str, timeout: int = 15, prefer_id_token: bool = True) -> None:
        """Initialize the token-exchange client.

        Args:
            auth_url: Navigator login endpoint.
            timeout: Total request timeout in seconds.
            prefer_id_token: Include an available ID token in the exchange.
        """
        self.auth_url = auth_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.prefer_id_token = prefer_id_token
        raw = navconfig_settings.get("NAVIGATOR_SSL_VERIFY", fallback="true")
        if isinstance(raw, bool):
            ssl_verify = raw
        else:
            ssl_verify = str(raw).lower() not in ("false", "0", "no")
        self._ssl: Optional[bool] = None if ssl_verify else False

    async def exchange(
        self,
        token: str,
        *,
        provider: str = "azure",
        id_token: Optional[str] = None,
        token_type: str = "Bearer",
    ) -> ExchangeResult:
        """Exchange an external token for a Navigator session.

        Transport failures do not escape. They return an unsuccessful result
        whose reason is ``transport_error``.

        Args:
            token: Provider access token.
            provider: External identity provider name.
            id_token: Optional provider ID token.
            token_type: Access-token scheme.

        Returns:
            The parsed exchange outcome.
        """
        payload: Dict[str, Any] = {
            "provider": provider,
            "token": token,
            "token_type": token_type,
        }
        if id_token and self.prefer_id_token:
            payload["id_token"] = id_token
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Method": "TokenExchangeAuth",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.auth_url,
                    json=payload,
                    headers=headers,
                    ssl=self._ssl,
                ) as response:
                    if response.status == 200:
                        result = self._result_from_body(await response.json())
                    else:
                        result = self._classify_failure(response.status, await response.text())
                    logger.info("Navigator token exchange completed: HTTP %s reason=%s", response.status, result.reason)
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            # ValueError covers a 200 whose body is not valid JSON.
            logger.error("Navigator token exchange request failed: reason=%s", REASON_TRANSPORT)
            return ExchangeResult(ok=False, reason=REASON_TRANSPORT)

    @staticmethod
    def _classify_failure(status: int, body: str) -> ExchangeResult:
        """Map an error response to a distinguishable reason.

        Args:
            status: HTTP response status.
            body: Response body text.

        Returns:
            An unsuccessful result with a stable reason.
        """
        normalized_body = body.lower()
        if "unacceptable auth method" in normalized_body:
            reason = REASON_BACKEND_NOT_LOADED
        elif "user_not_found" in normalized_body or (status in (401, 403, 404) and "not found" in normalized_body):
            reason = REASON_USER_NOT_FOUND
        elif "expired" in normalized_body:
            reason = REASON_EXPIRED
        else:
            reason = REASON_INVALID_TOKEN
        return ExchangeResult(ok=False, reason=reason)

    @staticmethod
    def _result_from_body(body: Dict[str, Any]) -> ExchangeResult:
        """Build a success result from the login response.

        Args:
            body: Parsed Navigator login response.

        Returns:
            A successful result populated from the response.
        """
        session = body.get("session")
        session_data = session if isinstance(session, dict) else {}
        nav_user_id = body.get("user_id", session_data.get("user_id"))
        display_name = body.get("name") or body.get("display_name")
        if not display_name:
            display_name = (
                " ".join(part for part in (session_data.get("first_name"), session_data.get("last_name")) if part)
                or None
            )

        if nav_user_id in (None, "") or not body.get("token"):
            # A 200 without an identity or session token must never authenticate anyone.
            return ExchangeResult(ok=False, reason=REASON_INVALID_TOKEN)

        return ExchangeResult(
            ok=True,
            nav_user_id=str(nav_user_id) if nav_user_id is not None else None,
            session_token=body.get("token"),
            email=body.get("email") or session_data.get("email"),
            display_name=display_name,
            provider_user_id=body.get("provider_user_id") or session_data.get("provider_user_id"),
            expires_at=body.get("external_expires_at") or session_data.get("external_expires_at"),
            raw=body,
        )
