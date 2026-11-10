"""Concrete browser-identity verifiers for Navigator session JWTs (FEAT-854)."""

from __future__ import annotations

from typing import Any, Iterable, List, MutableMapping, Optional

import jwt
from navconfig import config as navconfig_settings
from navconfig.logging import logging

from parrot.integrations.telegram.browser_login import (
    PAGE_AUTH_METHODS,
    BrowserVerificationError,
    BrowserVerifierUnavailableError,
    VerifiedBrowserIdentity,
    get_browser_identity_verifier,
    register_browser_identity_verifier,
)

logger = logging.getLogger(__name__)

_ALLOWED_ALGORITHMS = frozenset({"HS256", "HS384", "HS512", "RS256", "ES256"})


class NavigatorJWTVerifier:
    """Verify Navigator-issued session JWTs with navigator-auth's own IdentityProvider."""

    def __init__(
        self,
        *,
        issuer: Optional[str] = None,
        tenant_id: Optional[str] = None,
        idp: Optional[Any] = None,
    ) -> None:
        self._issuer = issuer
        self._tenant_id = tenant_id
        self._idp = idp

    def _provider(self) -> Any:
        if self._idp is None:
            try:
                from navigator_auth.backends.idp import IdentityProvider

                self._idp = IdentityProvider()
            except Exception as exc:  # noqa: BLE001 - ImportError / ConfigError -> 503
                raise BrowserVerifierUnavailableError("Navigator identity provider unavailable") from exc
        return self._idp

    @staticmethod
    def _reject(message: str, *, bot_id: str, auth_method: str) -> None:
        """Log a credential rejection without exposing token or claims."""
        logger.warning("Rejected Navigator browser identity for bot %s via %s: %s", bot_id, auth_method, message)
        raise BrowserVerificationError("invalid Navigator token")

    async def verify(
        self,
        token: str,
        *,
        auth_method: str,
        bot_id: str,
        tenant_id: Optional[str],
    ) -> VerifiedBrowserIdentity:
        """Return the identity proven by a valid Navigator session JWT."""
        try:
            from navigator_auth.conf import AUTH_TOKEN_ISSUER
            from navigator_auth.exceptions import AuthException, AuthExpired, FailedAuth, InvalidAuth
        except ImportError as exc:
            raise BrowserVerifierUnavailableError("Navigator identity provider unavailable") from exc

        if not isinstance(token, str) or not token:
            self._reject("empty credential", bot_id=bot_id, auth_method=auth_method)

        jwt_token = token.split(":", 1)[1] if ":" in token else token
        try:
            algorithm = jwt.get_unverified_header(jwt_token).get("alg")
        except jwt.exceptions.PyJWTError as exc:
            raise BrowserVerificationError("invalid Navigator token") from exc
        if algorithm not in _ALLOWED_ALGORITHMS:
            self._reject("disallowed JWT algorithm", bot_id=bot_id, auth_method=auth_method)

        try:
            tenant, claims = self._provider().decode_token(token, issuer=self._issuer or AUTH_TOKEN_ISSUER)
        except (AuthExpired, FailedAuth, InvalidAuth, jwt.exceptions.PyJWTError) as exc:
            raise BrowserVerificationError("invalid Navigator token") from exc
        except AuthException as exc:
            raise BrowserVerifierUnavailableError("Navigator token verification failed") from exc

        if not isinstance(claims, dict):
            self._reject("missing claims", bot_id=bot_id, auth_method=auth_method)
        if "aud" in claims:
            self._reject("audience-bearing credential", bot_id=bot_id, auth_method=auth_method)
        if claims.get("user_id") is None:
            self._reject("missing user identity", bot_id=bot_id, auth_method=auth_method)

        bound_tenant = self._tenant_id or tenant_id
        if tenant is not None and (bound_tenant is None or tenant != bound_tenant):
            self._reject("tenant mismatch", bot_id=bot_id, auth_method=auth_method)

        claimed_method = claims.get("auth_method")
        if auth_method in {"azure", "google"} and claimed_method != auth_method:
            self._reject("authentication method mismatch", bot_id=bot_id, auth_method=auth_method)
        if auth_method == "basic" and claimed_method not in {None, "basic"}:
            self._reject("authentication method mismatch", bot_id=bot_id, auth_method=auth_method)

        identity = VerifiedBrowserIdentity(
            user_id=str(claims["user_id"]),
            display_name=claims.get("name") or None,
            email=claims.get("email") or None,
        )
        logger.debug("Verified browser identity for bot %s via %s", bot_id, auth_method)
        return identity


def navigator_key_material_configured() -> bool:
    """Return whether the bot shares the Navigator issuer's signing material."""
    if navconfig_settings.get("AUTH_SECRET_KEY"):
        return True
    try:
        from navigator_auth.conf import OAUTH_JWT_KEYS
    except ImportError:
        return False
    return bool(OAUTH_JWT_KEYS)


def ensure_navigator_browser_verifiers(
    app: MutableMapping[str, Any],
    *,
    bot_id: str,
    methods: Iterable[str],
    tenant_id: Optional[str],
) -> List[str]:
    """Wire defaults for page methods and return methods still lacking a verifier."""
    page_methods = sorted(set(methods).intersection(PAGE_AUTH_METHODS))
    missing = [
        method
        for method in page_methods
        if get_browser_identity_verifier(app, bot_id=bot_id, auth_method=method) is None
    ]
    if missing and navigator_key_material_configured():
        for method in missing:
            register_browser_identity_verifier(
                app,
                bot_id=bot_id,
                auth_method=method,
                verifier=NavigatorJWTVerifier(tenant_id=tenant_id),
            )

    return [
        method
        for method in page_methods
        if get_browser_identity_verifier(app, bot_id=bot_id, auth_method=method) is None
    ]
