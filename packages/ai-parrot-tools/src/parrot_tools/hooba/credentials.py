"""Broker-backed Hooba credentials and the cookie-session login hook (FEAT-602 M2)."""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import CredentialResolver, NeedsAuth
from parrot.interfaces.http import HTTPService

from .settings import HoobaSettings

logger = logging.getLogger(__name__)

HoobaLoginHook = Callable[[HTTPService], Awaitable[Dict[str, str]]]
_BROKER_CHANNEL = "hooba"


class HoobaAuthError(RuntimeError):
    """Login rejected, credentials unavailable, or no ``sid`` cookie in the login response."""


class EnvCredentialResolver(CredentialResolver):
    """Resolve a ``{"username", "password"}`` pair from environment variables."""

    def __init__(
        self,
        username_var: str = "HOOBA_USERNAME",
        password_var: str = "HOOBA_PASSWORD",
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._username_var = username_var
        self._password_var = password_var
        self._env = env

    async def resolve(self, channel: str, user_id: str) -> Optional[Dict[str, str]]:
        """Return the pair when both variables are set, else ``None``."""
        env = os.environ if self._env is None else self._env
        username = env.get(self._username_var, "")
        password = env.get(self._password_var, "")
        if not username or not password:
            return None
        return {"username": username, "password": password}

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """No out-of-band flow: the operator sets the variables."""
        return ""


def register_hooba_provider(
    broker: CredentialBroker,
    provider: str = "hooba",
    resolver: Optional[CredentialResolver] = None,
) -> None:
    """Register ``provider`` on ``broker`` with an env-backed resolver by default."""
    broker.register(provider, resolver or EnvCredentialResolver(), auth_kind="static_key")


def make_login_hook(
    settings: HoobaSettings,
    broker: CredentialBroker,
    user_id: Optional[str] = None,
) -> HoobaLoginHook:
    """Return the async hook ``OpenAPIToolkit(auth_type="cookie")`` uses for a session cookie."""

    async def _login(http_service: HTTPService) -> Dict[str, str]:
        identity = user_id or settings.credential_user_id
        try:
            resolved = await broker.resolve(settings.credential_provider, _BROKER_CHANNEL, identity)
        except (KeyError, ValueError, TypeError) as exc:
            raise HoobaAuthError("Hooba credentials are unavailable") from exc

        if isinstance(resolved, NeedsAuth):
            raise HoobaAuthError("Hooba credentials are unavailable")

        secret: Any = getattr(resolved, "secret", None)
        if isinstance(secret, dict):
            username = secret.get("username")
            password = secret.get("password")
        elif isinstance(secret, (tuple, list)) and len(secret) == 2:
            username, password = secret
        else:
            raise HoobaAuthError("Hooba credentials have an invalid shape")
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            raise HoobaAuthError("Hooba credentials have an invalid shape")

        response, _ = await http_service._request(
            f"{settings.base_url}/auth/login",
            method="post",
            data={"username": username, "password": password},
            use_json=True,
            headers=settings.default_headers(),
            full_response=True,
            raise_for_status=False,
            use_proxy=False,
            num_retries=0,
        )
        status = getattr(response, "status_code", None)
        if status != 200:
            raise HoobaAuthError(f"login failed: HTTP {status}")

        cookies = getattr(response, "cookies", None)
        sid = cookies.get("sid") if cookies is not None else None
        if sid is None:
            for history_response in getattr(response, "history", ()):
                history_cookies = getattr(history_response, "cookies", None)
                sid = history_cookies.get("sid") if history_cookies is not None else None
                if sid is not None:
                    break
        if sid is None:
            raise HoobaAuthError("login response did not contain a sid cookie")
        return {"sid": str(sid)}

    return _login
