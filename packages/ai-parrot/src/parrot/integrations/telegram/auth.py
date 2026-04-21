"""Telegram user authentication — strategies and session management.

Provides an abstract auth strategy interface with concrete implementations
for Navigator Basic Auth, Azure AD SSO, OAuth2 (Authorization Code + PKCE),
and a Composite multi-method router (CompositeAuthStrategy) introduced by
FEAT-109 for mixed-identity deployments.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64
import hashlib
import json
import secrets
import time

import aiohttp
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
)
from navconfig import config as navconfig_settings
from navconfig.logging import logging

from .oauth2_providers import get_provider, OAuth2ProviderConfig


logger = logging.getLogger("parrot.Telegram.Auth")


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------

@dataclass
class TelegramUserSession:
    """Cached identity for a Telegram user within a chat session."""

    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_first_name: Optional[str] = None
    telegram_last_name: Optional[str] = None
    # Populated after Navigator login:
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_display_name: Optional[str] = None
    nav_email: Optional[str] = None
    authenticated: bool = False
    authenticated_at: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)
    # OAuth2-specific fields:
    oauth2_access_token: Optional[str] = None
    oauth2_id_token: Optional[str] = None
    oauth2_provider: Optional[str] = None
    # Office365 delegated connection derived from agent OAuth2 credentials.
    o365_access_token: Optional[str] = None
    o365_id_token: Optional[str] = None
    o365_provider: Optional[str] = None
    o365_authenticated_at: Optional[datetime] = None
    # Jira OAuth2 3LO connection (populated by /connect_jira callback).
    # These identify the user on Atlassian independently of the primary
    # Navigator login, so a corporate /login and a personal Jira account
    # can coexist without the LLM/tooling confusing identities.
    jira_account_id: Optional[str] = None
    jira_email: Optional[str] = None
    jira_display_name: Optional[str] = None
    jira_cloud_id: Optional[str] = None
    jira_authenticated_at: Optional[datetime] = None

    @property
    def user_id(self) -> str:
        """Return nav_user_id if authenticated, else telegram identifier."""
        if self.authenticated and self.nav_user_id:
            return self.nav_user_id
        return f"tg:{self.telegram_id}"

    @property
    def session_id(self) -> str:
        """Stable session key for conversation memory."""
        return f"tg_chat:{self.telegram_id}"

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        if self.nav_display_name:
            return self.nav_display_name
        parts = []
        if self.telegram_first_name:
            parts.append(self.telegram_first_name)
        if self.telegram_last_name:
            parts.append(self.telegram_last_name)
        if parts:
            return " ".join(parts)
        if self.telegram_username:
            return f"@{self.telegram_username}"
        return f"User {self.telegram_id}"

    def set_authenticated(
        self,
        nav_user_id: str,
        session_token: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        **extra_meta,
    ) -> None:
        """Mark session as authenticated with Navigator credentials."""
        self.nav_user_id = nav_user_id
        self.nav_session_token = session_token
        self.nav_display_name = display_name
        self.nav_email = email
        self.authenticated = True
        self.authenticated_at = datetime.now()
        if extra_meta:
            self.metadata.update(extra_meta)

    def set_jira_authenticated(
        self,
        account_id: str,
        email: Optional[str],
        display_name: Optional[str],
        cloud_id: Optional[str] = None,
    ) -> None:
        """Record successful Jira OAuth2 3LO connection on this session.

        Called by ``JiraPostAuthProvider.handle_result`` after the combined
        auth callback succeeds so downstream code (prompt enrichment, tool
        context) can surface the connected Jira identity instead of the
        primary Navigator login identity.

        Args:
            account_id: Atlassian ``accountId`` (ARI) of the connected user.
            email: Atlassian account email (may be ``None`` when the user
                hides it).
            display_name: Atlassian display name.
            cloud_id: Optional Atlassian cloud_id for the selected site.
        """
        self.jira_account_id = account_id
        self.jira_email = email
        self.jira_display_name = display_name
        self.jira_cloud_id = cloud_id
        self.jira_authenticated_at = datetime.now()

    def clear_jira_auth(self) -> None:
        """Clear the Jira OAuth2 connection fields (disconnect)."""
        self.jira_account_id = None
        self.jira_email = None
        self.jira_display_name = None
        self.jira_cloud_id = None
        self.jira_authenticated_at = None

    def set_o365_authenticated(
        self,
        access_token: str,
        id_token: Optional[str],
        provider: Optional[str],
    ) -> None:
        """Record a delegated Office365 connection for this Telegram session."""
        self.o365_access_token = access_token
        self.o365_id_token = id_token
        self.o365_provider = provider
        self.o365_authenticated_at = datetime.now()

    def clear_o365_auth(self) -> None:
        """Clear Office365 delegated auth fields (disconnect)."""
        self.o365_access_token = None
        self.o365_id_token = None
        self.o365_provider = None
        self.o365_authenticated_at = None

    def clear_auth(self) -> None:
        """Clear authentication state (logout)."""
        self.nav_user_id = None
        self.nav_session_token = None
        self.nav_display_name = None
        self.nav_email = None
        self.authenticated = False
        self.authenticated_at = None
        self.metadata.clear()
        # Clear OAuth2 fields
        self.oauth2_access_token = None
        self.oauth2_id_token = None
        self.oauth2_provider = None
        # Jira connection is tied to the user identity — drop it on logout
        self.clear_jira_auth()
        # Office365 delegated connection is tied to session identity too.
        self.clear_o365_auth()


# ---------------------------------------------------------------------------
# Navigator Basic-Auth client (unchanged, used internally by BasicAuthStrategy)
# ---------------------------------------------------------------------------

class NavigatorAuthClient:
    """Authenticate Telegram users against Navigator API.

    SSL verification is enabled by default.  Set the ``NAVIGATOR_SSL_VERIFY``
    environment variable to ``false`` (or ``0`` / ``no``) to disable
    verification in environments that use self-signed certificates.  Disabling
    verification in production is a security risk — prefer installing the CA
    certificate instead.
    """

    def __init__(self, auth_url: str, timeout: int = 15) -> None:
        self.auth_url = auth_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        # Respect NAVIGATOR_SSL_VERIFY env var; default to verifying certs.
        raw = navconfig_settings.get("NAVIGATOR_SSL_VERIFY", fallback="true")
        if isinstance(raw, bool):
            ssl_verify = raw
        else:
            ssl_verify = str(raw).lower() not in ("false", "0", "no")
        # None → aiohttp default (verify); False → skip verification.
        self._ssl: Optional[bool] = None if ssl_verify else False

    async def login(
        self, username: str, password: str
    ) -> Optional[Dict]:
        """Authenticate against Navigator API.

        Returns dict with user info on success, None on failure.
        Expected response: {"user_id": ..., "display_name": ..., "token": ...}
        """
        payload = {"username": username, "password": password}
        headers = {
            "Content-Type": "application/json",
            "x-auth-method": "BasicAuth",
        }
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.auth_url,
                    json=payload,
                    headers=headers,
                    ssl=self._ssl,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(
                            "Navigator login successful for '%s'", username
                        )
                        return data
                    logger.warning(
                        "Navigator login failed for '%s': HTTP %s",
                        username,
                        resp.status,
                    )
                    return None
        except aiohttp.ClientError as e:
            logger.error("Navigator auth request failed: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error during Navigator auth: %s", e)
            return None

    async def validate_token(self, token: str) -> bool:
        """Validate an existing session token (optional future use)."""
        # Placeholder for token validation endpoint
        return bool(token)


# ---------------------------------------------------------------------------
# Auth strategy abstraction
# ---------------------------------------------------------------------------

class AbstractAuthStrategy(ABC):
    """Base class for Telegram authentication strategies.

    Each strategy knows how to:
    - Build a login keyboard (WebApp button) for the Telegram user.
    - Handle the callback data returned from the WebApp.
    - Validate an existing session token.

    Class Attributes:
        name: Canonical short name used in callback payloads and YAML config.
            Subclasses must override this.
        supports_post_auth_chain: Whether this strategy can carry a post-auth
            redirect chain (e.g., for Jira OAuth2 after BasicAuth). Subclasses
            that support the chain must set this to True.
    """

    name: str = "abstract"
    supports_post_auth_chain: bool = False

    @abstractmethod
    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup:
        """Return the keyboard markup with the login button/WebApp.

        Args:
            config: TelegramAgentConfig instance.
            state: CSRF state token for the auth flow.
            next_auth_url: Optional URL of a secondary authentication step
                (e.g., Jira OAuth2 authorization URL). Strategies that do not
                support the post-auth chain may ignore this kwarg.
            next_auth_required: If True, secondary auth is mandatory.
                Strategies that do not support the post-auth chain may ignore.

        Returns:
            aiogram ReplyKeyboardMarkup with the login button.
        """
        ...

    @abstractmethod
    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Process auth callback data returned from the WebApp.

        Args:
            data: Parsed JSON data from ``message.web_app_data``.
            session: The user's Telegram session to populate.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        ...

    @abstractmethod
    async def validate_token(self, token: str) -> bool:
        """Validate an existing session token.

        Args:
            token: The session or access token to validate.

        Returns:
            True if the token is still valid.
        """
        ...


# ---------------------------------------------------------------------------
# Basic-Auth strategy (wraps NavigatorAuthClient)
# ---------------------------------------------------------------------------

class BasicAuthStrategy(AbstractAuthStrategy):
    """Navigator Basic Auth strategy.

    Wraps the existing ``NavigatorAuthClient`` and produces the same WebApp
    keyboard / callback handling that the wrapper used before the strategy
    refactor.

    Args:
        auth_url: Navigator authentication endpoint URL.
        login_page_url: URL of the static login HTML page served to the
            Telegram WebApp.
    """

    name = "basic"
    supports_post_auth_chain = True

    def __init__(
        self,
        auth_url: str,
        login_page_url: Optional[str] = None,
    ):
        self.auth_url = auth_url
        self.login_page_url = login_page_url
        self._client = NavigatorAuthClient(auth_url)
        self.logger = logging.getLogger("parrot.Telegram.Auth.Basic")

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup:
        """Build the Navigator login WebApp keyboard.

        Args:
            config: TelegramAgentConfig (used for login_page_url fallback).
            state: CSRF state token (unused for basic auth, kept for interface
                   consistency).
            next_auth_url: Optional URL of a secondary authentication step
                (e.g., Jira OAuth2 authorization URL) that the login page
                should redirect to after BasicAuth succeeds. When set, the
                login page participates in the FEAT-108 combined auth flow.
            next_auth_required: If True, secondary auth is mandatory; the
                login page reports an error on redirect failure instead of
                silently falling back to BasicAuth-only ``sendData``.

        Returns:
            ReplyKeyboardMarkup with a WebApp button pointing to the login page.

        Raises:
            ValueError: If no login_page_url is configured.
        """
        page_url = self.login_page_url or getattr(config, "login_page_url", None)
        if not page_url:
            raise ValueError(
                "login_page_url is required for BasicAuthStrategy"
            )

        params: Dict[str, Any] = {"auth_url": self.auth_url}
        if next_auth_url:
            params["next_auth_url"] = next_auth_url
            params["next_auth_required"] = (
                "true" if next_auth_required else "false"
            )
        full_url = f"{page_url}?{urlencode(params)}"

        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="\U0001f510 Sign in to Navigator",
                    web_app=WebAppInfo(url=full_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Handle Navigator login callback data.

        Expects ``data`` to contain ``user_id``, ``token``, and optionally
        ``display_name`` and ``email``.  Tolerates both legacy payloads (no
        ``auth_method`` key) and FEAT-109 payloads that include
        ``auth_method: "basic"``.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
            session: User session to populate on success.

        Returns:
            True if the callback contained valid user info.
        """
        # Accept payloads with or without auth_method (backward compatibility).
        method = data.get("auth_method")
        if method is not None and method != self.name:
            self.logger.warning(
                "BasicAuth callback invoked with auth_method=%r; "
                "ignoring mismatch and proceeding with basic.",
                method,
            )

        nav_user_id = data.get("user_id")
        if not nav_user_id:
            self.logger.warning("Basic auth callback missing user_id")
            return False

        token = data.get("token", "")
        display_name = data.get("display_name", "")
        email = data.get("email", "")

        session.set_authenticated(
            nav_user_id=str(nav_user_id),
            session_token=token,
            display_name=display_name,
            email=email,
        )

        self.logger.info(
            "User tg:%s authenticated as nav:%s (%s)",
            session.telegram_id,
            nav_user_id,
            display_name,
        )
        return True

    async def validate_token(self, token: str) -> bool:
        """Validate a Navigator session token.

        Args:
            token: The session token to validate.

        Returns:
            True if the token is valid.
        """
        return await self._client.validate_token(token)


# ---------------------------------------------------------------------------
# Azure SSO strategy (delegates to Navigator's /api/v1/auth/azure/ endpoint)
# ---------------------------------------------------------------------------

# Azure session TTL — 4 days per spec.
_AZURE_TOKEN_TTL = timedelta(days=4)


class AzureAuthStrategy(AbstractAuthStrategy):
    """Navigator Azure AD SSO strategy.

    Delegates the full OAuth2 flow to Navigator's /api/v1/auth/azure/ endpoint.
    The bot only captures the JWT token returned via redirect. No signature
    verification is performed; Navigator is the trusted issuer.

    Args:
        auth_url: Navigator base authentication endpoint URL (used for token
            validation via NavigatorAuthClient).
        azure_auth_url: Navigator's Azure SSO endpoint URL.
            E.g. ``https://nav.example.com/api/v1/auth/azure/``.
        login_page_url: URL of the static ``azure_login.html`` page served
            to the Telegram WebApp.
        post_auth_registry: Optional ``PostAuthRegistry`` injected at
            construction time (Approach A). When provided and non-empty,
            ``handle_callback`` invokes the chain providers after the JWT
            is successfully validated. When ``None`` (default) or empty, the
            strategy behaves as before FEAT-109.
    """

    name = "azure"
    supports_post_auth_chain = True

    def __init__(
        self,
        auth_url: str,
        azure_auth_url: str,
        login_page_url: Optional[str] = None,
        post_auth_registry: Optional[Any] = None,
    ) -> None:
        self.auth_url = auth_url
        self.azure_auth_url = azure_auth_url
        self.login_page_url = login_page_url
        self._post_auth_registry = post_auth_registry
        self._client = NavigatorAuthClient(auth_url)
        self.logger = logging.getLogger("parrot.Telegram.Auth.Azure")

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup:
        """Build the Azure SSO WebApp keyboard.

        Args:
            config: TelegramAgentConfig (used for login_page_url fallback).
            state: CSRF state token (kept for interface consistency; Azure flow
                uses Navigator-managed state internally).
            next_auth_url: Optional URL of a secondary authentication step.
                When set, the value is embedded in the WebApp URL so that
                ``azure_login.html`` can redirect to it after the JWT is
                captured (FEAT-109 post-auth chain).
            next_auth_required: If True, the secondary auth redirect is
                mandatory. Passed through to ``azure_login.html``.

        Returns:
            ReplyKeyboardMarkup with a WebApp button pointing to
            ``azure_login.html?azure_auth_url=...``.

        Raises:
            ValueError: If no login_page_url is configured.
        """
        page_url = self.login_page_url or getattr(config, "login_page_url", None)
        if not page_url:
            raise ValueError(
                "login_page_url is required for AzureAuthStrategy"
            )

        params: Dict[str, Any] = {"azure_auth_url": self.azure_auth_url}
        if next_auth_url:
            params["next_auth_url"] = next_auth_url
            params["next_auth_required"] = "true" if next_auth_required else "false"
        full_url = f"{page_url}?{urlencode(params)}"

        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="\U0001f510 Sign in with Azure",
                    web_app=WebAppInfo(url=full_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Process Azure SSO callback: decode JWT and populate session.

        Expects ``data`` to contain ``token`` (the Navigator JWT returned
        after Azure SSO redirect).  Decodes the payload to extract user
        identity fields and calls ``session.set_authenticated()``.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
                Must contain ``{"auth_method": "azure", "token": "<jwt>"}``.
            session: User session to populate on success.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        if data.get("auth_method") != "azure":
            self.logger.warning(
                "AzureAuthStrategy received unexpected auth_method=%r; ignoring",
                data.get("auth_method"),
            )
            return False

        token = data.get("token")
        if not token:
            self.logger.warning("Azure auth callback missing token")
            return False

        try:
            claims = self._decode_jwt_payload(token)
        except (ValueError, json.JSONDecodeError) as exc:
            self.logger.warning("Failed to decode Azure JWT: %s", exc)
            return False

        # Extract user identity — handle both user_id and sub claims
        user_id = claims.get("user_id") or claims.get("sub") or ""
        if not user_id:
            self.logger.warning("Azure JWT missing user_id/sub claim")
            return False

        email = claims.get("email", "")
        # Handle both name and first_name/last_name claims
        display_name = claims.get("name") or claims.get("first_name", "")
        if claims.get("last_name"):
            display_name = f"{display_name} {claims['last_name']}".strip()

        session.set_authenticated(
            nav_user_id=str(user_id),
            session_token=token,
            display_name=display_name or None,
            email=email or None,
        )

        self.logger.info(
            "User tg:%s authenticated via Azure as %s (%s)",
            session.telegram_id,
            user_id,
            display_name,
        )

        # FEAT-109: invoke post-auth chain if a registry was injected.
        # Each registered provider's handle_result is called with the
        # provider-specific sub-payload from data (e.g. data["jira"]).
        if self._post_auth_registry and len(self._post_auth_registry) > 0:
            await self._run_post_auth_chain(data, session)

        return True

    async def _run_post_auth_chain(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> None:
        """Invoke registered post-auth providers after successful Azure login.

        Each provider's ``handle_result`` is called with the provider-specific
        sub-dict from ``data`` (keyed by ``provider_name``). Failures are
        logged but do not roll back the primary Azure authentication.

        Args:
            data: The full callback payload (may include secondary auth keys).
            session: The newly authenticated user session.
        """
        primary_data: Dict[str, Any] = {
            "auth_method": "azure",
            "nav_user_id": session.nav_user_id,
        }
        for name in self._post_auth_registry.providers:
            provider = self._post_auth_registry.get(name)
            if provider is None:
                continue
            provider_data = data.get(name) or {}
            try:
                ok = await provider.handle_result(
                    data=provider_data,
                    session=session,
                    primary_auth_data=primary_data,
                )
                if not ok:
                    self.logger.warning(
                        "Post-auth provider '%s' returned failure for tg:%s",
                        name,
                        session.telegram_id,
                    )
            except Exception:  # noqa: BLE001
                self.logger.exception(
                    "Post-auth provider '%s' raised an exception for tg:%s",
                    name,
                    session.telegram_id,
                )

    async def validate_token(
        self,
        token: str,
        session: Optional["TelegramUserSession"] = None,
    ) -> bool:
        """Validate a Navigator JWT token, enforcing the 4-day session TTL.

        Args:
            token: The JWT session token to validate.
            session: Optional authenticated session. When provided, the
                4-day TTL is checked via ``authenticated_at``.

        Returns:
            True if the token is non-empty and the session (when given)
            has not exceeded the 4-day TTL.
        """
        if not token:
            return False
        if session is not None:
            if not session.authenticated or not session.authenticated_at:
                return False
            age = datetime.now() - session.authenticated_at
            if age > _AZURE_TOKEN_TTL:
                self.logger.info(
                    "Azure session expired for tg:%s (age=%s, ttl=%s)",
                    session.telegram_id,
                    age,
                    _AZURE_TOKEN_TTL,
                )
                return False
        return await self._client.validate_token(token)

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]:
        """Decode the payload segment of a JWT without signature verification.

        Navigator is the trusted issuer; we only need the claims.

        Args:
            token: A three-part JWT string ``header.payload.signature``.

        Returns:
            Decoded payload as a dictionary.

        Raises:
            ValueError: If the token does not have exactly three parts.
            json.JSONDecodeError: If the payload is not valid JSON.
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid JWT format: expected 3 parts, got {len(parts)}"
            )
        payload_b64 = parts[1]
        # Add base64 padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)


# ---------------------------------------------------------------------------
# OAuth2 strategy (Authorization Code + PKCE)
# ---------------------------------------------------------------------------

# Default token TTL — sessions expire after this duration.
_TOKEN_TTL = timedelta(days=7)

# Pending OAuth2 states expire after this many seconds.
_STATE_TTL_SECONDS = 600  # 10 minutes


class OAuth2AuthStrategy(AbstractAuthStrategy):
    """OAuth2 Authorization Code strategy with PKCE.

    Handles the full OAuth2 flow:
    1. Build an authorization URL (with PKCE code_challenge).
    2. After the user authenticates, exchange the code for tokens.
    3. Fetch user profile from the provider's userinfo endpoint.

    Args:
        config: TelegramAgentConfig with OAuth2 settings populated.
    """

    name = "oauth2"
    supports_post_auth_chain = False

    def __init__(self, config: Any) -> None:
        self._provider: OAuth2ProviderConfig = get_provider(
            getattr(config, "oauth2_provider", "google")
        )
        self._client_id: str = getattr(config, "oauth2_client_id", None) or ""
        self._client_secret: str = getattr(config, "oauth2_client_secret", None) or ""
        self._redirect_uri: str = getattr(config, "oauth2_redirect_uri", None) or ""

        # Validate required fields early
        missing = []
        if not self._client_id:
            missing.append("oauth2_client_id")
        if not self._client_secret:
            missing.append("oauth2_client_secret")
        if not self._redirect_uri:
            missing.append("oauth2_redirect_uri")
        if missing:
            raise ValueError(
                f"OAuth2AuthStrategy requires config fields: {', '.join(missing)}"
            )

        self._scopes: list[str] = (
            config.oauth2_scopes
            if config.oauth2_scopes
            else list(self._provider.default_scopes)
        )
        # Maps state → (code_verifier, created_timestamp)
        self._pending_states: Dict[str, Tuple[str, float]] = {}
        self._http_timeout = aiohttp.ClientTimeout(total=15)
        self.logger = logging.getLogger("parrot.Telegram.Auth.OAuth2")

    # -- PKCE helpers -------------------------------------------------------

    @staticmethod
    def _generate_pkce() -> Tuple[str, str]:
        """Generate a PKCE code_verifier and code_challenge (S256).

        Returns:
            Tuple of (code_verifier, code_challenge).
        """
        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = (
            base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )
        return code_verifier, code_challenge

    # -- State management ---------------------------------------------------

    def _store_state(self, state: str, code_verifier: str) -> None:
        """Store a pending OAuth2 state with its PKCE verifier."""
        self._cleanup_expired_states()
        self._pending_states[state] = (code_verifier, time.monotonic())

    def _consume_state(self, state: str) -> Optional[str]:
        """Consume a pending state and return the code_verifier.

        Returns None if the state is unknown or expired.
        """
        self._cleanup_expired_states()
        entry = self._pending_states.pop(state, None)
        if entry is None:
            return None
        code_verifier, _ = entry
        return code_verifier

    def _cleanup_expired_states(self) -> None:
        """Remove states older than ``_STATE_TTL_SECONDS``."""
        now = time.monotonic()
        expired = [
            s for s, (_, ts) in self._pending_states.items()
            if (now - ts) > _STATE_TTL_SECONDS
        ]
        for s in expired:
            del self._pending_states[s]

    # -- AbstractAuthStrategy implementation --------------------------------

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup:
        """Build the OAuth2 authorization keyboard.

        Generates PKCE challenge, stores the state, and returns a
        ``ReplyKeyboardMarkup`` with a WebApp button pointing to the
        provider's authorization URL.

        Args:
            config: TelegramAgentConfig instance.
            state: CSRF state token for the auth flow.
            next_auth_url: Accepted for interface uniformity; ignored by
                this strategy (supports_post_auth_chain is False).
            next_auth_required: Accepted for interface uniformity; ignored.

        Returns:
            aiogram ReplyKeyboardMarkup.
        """
        code_verifier, code_challenge = self._generate_pkce()
        self._store_state(state, code_verifier)

        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
        }
        authorize_url = (
            f"{self._provider.authorization_url}?{urlencode(params)}"
        )

        provider_label = self._provider.name.capitalize()
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text=f"\U0001f510 Sign in with {provider_label}",
                    web_app=WebAppInfo(url=authorize_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Handle the OAuth2 callback from Telegram WebApp.

        Expects ``data`` to contain ``code`` and ``state``.  Exchanges
        the code for tokens, fetches userinfo, and populates the session.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
            session: User session to populate on success.

        Returns:
            True if authentication succeeded.
        """
        code = data.get("code")
        state = data.get("state")

        if not code or not state:
            self.logger.warning("OAuth2 callback missing code or state")
            return False

        # Validate and consume the state
        code_verifier = self._consume_state(state)
        if code_verifier is None:
            self.logger.warning(
                "OAuth2 callback with unknown or expired state"
            )
            return False

        # Exchange code for tokens
        token_data = await self.exchange_code(code, code_verifier)
        if token_data is None:
            return False

        access_token = token_data.get("access_token", "")
        id_token = token_data.get("id_token", "")

        if not access_token:
            self.logger.warning("Token exchange returned no access_token")
            return False

        # Fetch user profile
        userinfo = await self.fetch_userinfo(access_token)
        if userinfo is None:
            return False

        # Populate session
        user_id = userinfo.get("sub", "")
        display_name = userinfo.get("name", "")
        email = userinfo.get("email", "")

        session.set_authenticated(
            nav_user_id=str(user_id),
            session_token=access_token,
            display_name=display_name,
            email=email,
        )
        session.oauth2_access_token = access_token
        session.oauth2_id_token = id_token
        session.oauth2_provider = self._provider.name

        self.logger.info(
            "User tg:%s authenticated via %s as %s (%s)",
            session.telegram_id,
            self._provider.name,
            user_id,
            display_name,
        )
        return True

    async def validate_token(
        self, token: str, session: Optional[TelegramUserSession] = None,
    ) -> bool:
        """Check that the token is non-empty and the session hasn't exceeded the 7-day TTL.

        Args:
            token: The OAuth2 access token to validate.
            session: Optional user session; when provided, the 7-day TTL
                is enforced via ``authenticated_at``.

        Returns:
            True if the token is valid and (if session given) not expired.
        """
        if not token:
            return False
        if session is not None and self.is_session_expired(session):
            return False
        return True

    def is_session_expired(self, session: TelegramUserSession) -> bool:
        """Check if a session's authentication has exceeded the 7-day TTL.

        Args:
            session: The user session to check.

        Returns:
            True if the session is expired or not authenticated.
        """
        if not session.authenticated or not session.authenticated_at:
            return True
        return (datetime.now() - session.authenticated_at) > _TOKEN_TTL

    # -- HTTP helpers -------------------------------------------------------

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
    ) -> Optional[Dict[str, Any]]:
        """Exchange an authorization code for tokens.

        Args:
            code: The authorization code from the provider redirect.
            code_verifier: PKCE code verifier for this flow.

        Returns:
            Token response dict on success, None on failure.
        """
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code_verifier": code_verifier,
        }
        try:
            async with aiohttp.ClientSession(
                timeout=self._http_timeout
            ) as http:
                async with http.post(
                    self._provider.token_url,
                    data=payload,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    body = await resp.text()
                    self.logger.warning(
                        "Token exchange failed: HTTP %s — %s",
                        resp.status,
                        body[:200],
                    )
                    return None
        except aiohttp.ClientError as exc:
            self.logger.error("Token exchange HTTP error: %s", exc)
            return None
        except Exception as exc:
            self.logger.error("Unexpected token exchange error: %s", exc)
            return None

    async def fetch_userinfo(
        self,
        access_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch user profile from the provider's userinfo endpoint.

        Args:
            access_token: Bearer token for the userinfo request.

        Returns:
            Userinfo dict on success, None on failure.
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with aiohttp.ClientSession(
                timeout=self._http_timeout
            ) as http:
                async with http.get(
                    self._provider.userinfo_url,
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    self.logger.warning(
                        "Userinfo fetch failed: HTTP %s",
                        resp.status,
                    )
                    return None
        except aiohttp.ClientError as exc:
            self.logger.error("Userinfo HTTP error: %s", exc)
            return None
        except Exception as exc:
            self.logger.error("Unexpected userinfo error: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Composite strategy (multi-method router — FEAT-109, Module 3)
# ---------------------------------------------------------------------------


class CompositeAuthStrategy(AbstractAuthStrategy):
    """Multi-method auth router.

    Owns a dict of per-method strategies keyed by their canonical ``.name``
    (``"basic"``, ``"azure"``). At callback time, it reads
    ``data["auth_method"]`` and dispatches to the matching member. A single
    WebApp button points to ``login_multi.html`` which shows all available
    sign-in methods to the user.

    Note: ``oauth2`` cannot be combined with other methods — ``login_multi.html``
    does not implement an OAuth2 flow.  The config validator (TASK-784 /
    TASK-I2) enforces this constraint at startup.

    Class Attributes:
        name: ``"composite"`` — used in logs and config validation.
        supports_post_auth_chain: Instance-level property (not a plain class
            attribute). Returns ``True`` only when **every** member strategy
            supports the post-auth chain (AND semantics).  Always access this
            on an *instance*; ``CompositeAuthStrategy.supports_post_auth_chain``
            at class level returns the property descriptor object itself.

    Args:
        strategies: Mapping of strategy name → strategy instance. Must
            contain at least one entry.
        login_page_url: URL of ``login_multi.html`` served as the WebApp
            page. Must be non-empty.

    Raises:
        ValueError: If ``strategies`` is empty or ``login_page_url`` is unset.
    """

    name: str = "composite"

    def __init__(
        self,
        strategies: Dict[str, "AbstractAuthStrategy"],
        login_page_url: str,
    ) -> None:
        if not strategies:
            raise ValueError(
                "CompositeAuthStrategy requires at least one member strategy."
            )
        if not login_page_url:
            raise ValueError(
                "CompositeAuthStrategy requires a non-empty login_page_url. "
                "Set login_page_url in your bot configuration and ensure it "
                "points to login_multi.html."
            )
        self.strategies = strategies
        self.login_page_url = login_page_url
        self.logger = logging.getLogger("parrot.Telegram.Auth.Composite")

    # Override the class-level bool with a property that inspects members.
    @property  # type: ignore[override]
    def supports_post_auth_chain(self) -> bool:  # type: ignore[override]
        """Return True only when all member strategies support the chain."""
        return all(
            getattr(s, "supports_post_auth_chain", False)
            for s in self.strategies.values()
        )

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup:
        """Build a WebApp keyboard pointing at ``login_multi.html``.

        Collects per-method auth URLs from the member strategies and
        assembles a merged query string so the multi-method login page has
        everything it needs to present each sign-in option.

        Args:
            config: TelegramAgentConfig instance.
            state: CSRF state token (forwarded to members for signing).
            next_auth_url: Optional post-auth chain URL; forwarded to all
                members that ``supports_post_auth_chain``.
            next_auth_required: Whether secondary auth is mandatory.

        Returns:
            ReplyKeyboardMarkup with a single WebApp button.
        """
        params: Dict[str, str] = {}

        # Harvest per-method endpoint URLs from member strategies.
        if basic := self.strategies.get("basic"):
            auth_url = getattr(basic, "auth_url", None)
            if auth_url:
                params["auth_url"] = auth_url
        if azure := self.strategies.get("azure"):
            azure_url = getattr(azure, "azure_auth_url", None)
            if azure_url:
                params["azure_auth_url"] = azure_url

        # Embed post-auth chain params for the multi-method page to use.
        if next_auth_url:
            params["next_auth_url"] = next_auth_url
            params["next_auth_required"] = "true" if next_auth_required else "false"

        full_url = f"{self.login_page_url}?{urlencode(params)}"

        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="\U0001f510 Sign in",
                    web_app=WebAppInfo(url=full_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Dispatch the WebApp callback to the matching member strategy.

        Reads ``data["auth_method"]`` and delegates to the strategy whose
        ``.name`` matches. On success, records the originating method in
        ``session.metadata["auth_method"]`` so that ``validate_token`` can
        dispatch to the same strategy without guessing. Unknown methods are
        logged and return ``False``.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
            session: User session to populate on success.

        Returns:
            True if the delegated strategy authenticated the user.
        """
        method = data.get("auth_method")
        strat = self.strategies.get(method) if method else None
        if strat is None:
            self.logger.warning(
                "CompositeAuthStrategy: callback with unknown auth_method=%r "
                "(known methods: %s)",
                method,
                list(self.strategies),
            )
            return False
        success = await strat.handle_callback(data, session)
        if success:
            # Record which strategy authenticated this session so that
            # validate_token can dispatch to it directly instead of relying
            # on an ordering heuristic (which would cross-validate tokens of
            # the wrong type — e.g. an Azure JWT against BasicAuth).
            session.metadata["auth_method"] = method
        return success

    async def validate_token(  # type: ignore[override]
        self,
        token: str,
        session: Optional["TelegramUserSession"] = None,
    ) -> bool:
        """Validate a session token against the correct member strategy.

        When ``session`` is provided and ``session.metadata["auth_method"]``
        is set (written by ``handle_callback``), the token is validated
        exclusively by the originating strategy. This prevents cross-type
        validation (e.g. an Azure JWT being accepted by the BasicAuth stub
        because ``NavigatorAuthClient.validate_token`` returns ``True`` for
        any non-empty string).

        Falls back to the insertion-order heuristic (``"basic"`` first) only
        when the session is absent or the method is not recorded — e.g. for
        sessions created before FEAT-109 was deployed.

        Args:
            token: The session or access token to validate.
            session: Optional user session. When provided, the originating
                auth method is read from ``session.metadata``.

        Returns:
            True if the responsible member strategy considers the token valid.
        """
        # Prefer exact dispatch using the recorded auth method.
        method = (
            session.metadata.get("auth_method")
            if session and session.metadata
            else None
        )
        if method and method in self.strategies:
            return await self.strategies[method].validate_token(token)

        # Fallback heuristic for legacy sessions without metadata.
        self.logger.debug(
            "validate_token: no auth_method in session metadata; "
            "falling back to insertion-order heuristic."
        )
        ordered: list = []
        if "basic" in self.strategies:
            ordered.append(self.strategies["basic"])
        for name, strat in self.strategies.items():
            if name != "basic":
                ordered.append(strat)

        for strat in ordered:
            if await strat.validate_token(token):
                return True
        return False
