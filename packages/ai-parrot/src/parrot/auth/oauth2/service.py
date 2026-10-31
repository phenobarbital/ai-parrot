"""IntegrationsService — orchestration layer for the OAuth2 integration flows.

Provides principal-scoped listing and status, channel-neutral connect and
credential persistence, and disconnect orchestration.

All origin validation is performed here (not in the handler) so that it is
covered by service-level unit tests.

PBAC convention
---------------
When the ``abac`` PDP is absent from the request (or when this service is called
without a request), the service fails **closed** for the integrations surface
(overrides the general fail-open convention in ``AgentTalk._check_pbac_agent_access``).
This was resolved as the correct behaviour for FEAT-144 Q-B.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from navconfig.logging import logging  # noqa: F811

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2 import _WEB_CHANNEL
from parrot.auth.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
    pass
from parrot.auth.oauth2.models import (
    ConnectInitResponse,
    DisconnectResponse,
    IntegrationDescriptor,
    NotConnected,
    PulledToken,
    UsersIntegrationRow,
    WhoAmI,
)
from parrot.auth.oauth2.persistence import (
    delete_users_integration,
    get_users_integration,
    list_users_integrations,
    upsert_users_integration,
)
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

logger = logging.getLogger(__name__)


def _get_allowed_origins() -> List[str]:
    """Return the configured list of allowed OAuth2 return origins.

    Reads ``WEB_OAUTH_ALLOWED_ORIGINS`` from :mod:`parrot.conf`, which
    normalises the raw env-var into a ``list[str]`` at import time.

    Returns:
        List of origin strings, e.g. ``["https://app.example.com"]``.
    """
    from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS  # type: ignore[attr-defined]

    if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, list):
        return list(WEB_OAUTH_ALLOWED_ORIGINS)
    if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, str) and WEB_OAUTH_ALLOWED_ORIGINS:
        return [o.strip() for o in WEB_OAUTH_ALLOWED_ORIGINS.split(",") if o.strip()]
    return []


class IntegrationsService:
    """Orchestrates OAuth2 provider registry, persistence, and PBAC checks.

    All public methods are coroutines. Instantiate once per request: the
    service memoizes the ``VaultTokenSync`` used to probe stored tokens, so one
    listing loads each user's vault only once.

    Args:
        vault_token_sync: Optional pre-built token reader (tests / callers that
            already hold one).
    """

    def __init__(self, vault_token_sync: Any = None) -> None:
        self._vault_token_sync = vault_token_sync
        self._identity_store_instance: Any = None

    async def list_for_principal(
        self,
        user_id: str,
        request: Any = None,
    ) -> List[IntegrationDescriptor]:
        """Return one PBAC-filtered descriptor per registered provider.

        Args:
            user_id: Navigator user identifier.
            request: Optional aiohttp request used for PBAC evaluation. When
                ``None`` or when ``abac`` is absent, the service fails closed
                and returns an empty list.

        Returns:
            List of :class:`~parrot.integrations.oauth2.models.IntegrationDescriptor`
            instances, one per allowed provider.
        """
        registry = OAuth2ProviderRegistry()
        providers = registry.all()

        # PBAC: fail-closed for integrations surface (Q-B resolution)
        if not await self._check_pbac(request, "integration:list"):
            logger.debug(
                "PBAC denied integration:list for user_id=%s — returning empty list",
                user_id,
            )
            return []

        result: List[IntegrationDescriptor] = []
        rows = {row.provider: row for row in await list_users_integrations(user_id)}

        for provider in providers:
            if not await self._check_pbac(request, "integration:list", provider.provider_id):
                continue
            result.append(await self._descriptor(user_id, provider, rows.get(provider.provider_id), request))

        return result

    async def list_for_user(
        self,
        user_id: str,
        agent_id: str,
        request: Any = None,
    ) -> List[IntegrationDescriptor]:
        """Return principal connections for an agent-scoped compatibility route.

        Args:
            user_id: Navigator user identifier.
            agent_id: Ignored legacy agent identifier.
            request: Optional aiohttp request used for PBAC evaluation.

        Returns:
            The principal-scoped integration descriptors.
        """
        del agent_id
        return await self.list_for_principal(user_id, request=request)

    async def _descriptor(
        self,
        user_id: str,
        provider: Any,
        integration_row: Optional[UsersIntegrationRow],
        request: Any,
    ) -> IntegrationDescriptor:
        """Build the public descriptor for one registered provider."""
        status = "disconnected"
        if integration_row is not None:
            status = await self._token_status(user_id, provider.provider_id, request)
        return IntegrationDescriptor(
            provider=provider.provider_id,
            display_name=provider.display_name,
            icon=provider.icon,
            default_scopes=provider.default_scopes,
            status=status,
            account_id=integration_row.account_id if integration_row else None,
            display_account_name=integration_row.display_name if integration_row else None,
            email=integration_row.email if integration_row else None,
            connected_at=integration_row.connected_at if integration_row else None,
            channels=integration_row.channels if integration_row else [],
            scopes_granted=integration_row.scopes_granted if integration_row else [],
            expires_at=integration_row.expires_at if integration_row else None,
            updated_at=integration_row.updated_at if integration_row else None,
        )

    def _vault_sync(self, request: Any) -> Any:
        """One ``VaultTokenSync`` per request (loads each user's vault once).

        Returns:
            A ``VaultTokenSync`` bound to the app's pools, or ``None`` when the
            service/app cannot provide them.
        """
        if self._vault_token_sync is not None:
            return self._vault_token_sync
        app = getattr(request, "app", None)
        if app is None:
            return None
        try:
            from parrot.services.vault_token_sync import VaultTokenSync
        except ImportError:  # pragma: no cover - server package not installed
            return None
        db_pool = app.get("authdb")
        if db_pool is None:
            return None
        self._vault_token_sync = VaultTokenSync(db_pool=db_pool, redis=app.get("redis"))
        return self._vault_token_sync

    def _identity_store(self, request: Any) -> Any:
        """One ``IdentityStore`` per service, or ``None`` when unavailable.

        Mirrors :meth:`_vault_sync`: built lazily from the app's ``authdb``
        pool and cached, and ``None`` whenever the app, the pool or the
        optional dependency is missing — so the caller can fail open.

        Returns:
            An ``IdentityStore`` bound to the auth pool, or ``None``.
        """
        if self._identity_store_instance is not None:
            return self._identity_store_instance
        app = getattr(request, "app", None)
        if app is None:
            return None
        try:
            from navigator_auth.identity.store import IdentityStore
        except ImportError:  # pragma: no cover - navigator-auth not installed
            return None
        db_pool = app.get("authdb")
        if db_pool is None:
            return None
        self._identity_store_instance = IdentityStore(db_pool)
        return self._identity_store_instance

    async def _identity_token_status(self, user_id: str, provider_id: str, request: Any) -> str:
        """Status of a provider whose credential lives in the Identity Vault.

        Same contract as :meth:`_token_status`: ``"connected"`` or
        ``"needs_reconnect"``, failing open to ``"connected"`` whenever the
        store cannot be probed, so an outage never hides a working
        integration. Only a credential that is provably unusable — no
        identity row, or one whose sealed token will not open — reports
        ``needs_reconnect``.

        Returns:
            ``"connected"`` or ``"needs_reconnect"``.
        """
        store = self._identity_store(request)
        if store is None:
            return "connected"
        try:
            from navigator_auth.identity.store import IdentityCredentialError
        except ImportError:  # pragma: no cover - navigator-auth not installed
            return "connected"
        try:
            identity = await store.get_by_provider(user_id, provider_id)
            if identity is None:
                logger.info(
                    "Integrations: provider=%s has no identity row for user=%s",
                    provider_id,
                    user_id,
                )
                return "needs_reconnect"
            # Synchronous on purpose — IdentityStore.decrypt_credential is not
            # a coroutine. Opening the credential IS the probe.
            store.decrypt_credential(identity)
        except IdentityCredentialError:
            logger.info(
                "Integrations: provider=%s credential unreadable for user=%s",
                provider_id,
                user_id,
            )
            return "needs_reconnect"
        except Exception:  # noqa: BLE001 - probing must never break the listing
            logger.warning(
                "Integrations: identity probe failed for user=%s provider=%s",
                user_id,
                provider_id,
            )
            return "connected"
        return "connected"

    async def _token_status(self, user_id: str, provider_id: str, request: Any) -> str:
        """Status of a connected provider based on its stored vault tokens.

        The Identity Vault is the durable owner for every provider. When the
        server-side store is unavailable, fall back to the provider manager's
        principal-keyed connectivity check.

        Returns:
            ``"connected"`` or ``"needs_reconnect"``. Falls back to
            ``"connected"`` when the vault cannot be probed, so a vault outage
            never hides working integrations.
        """
        if self._identity_store(request) is not None:
            return await self._identity_token_status(user_id, provider_id, request)
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            return "connected"
        try:
            connected = await provider.manager.is_connected(_WEB_CHANNEL, user_id)
        except Exception:  # noqa: BLE001 - probing must never break the listing
            logger.warning(
                "Integrations: manager probe failed for user=%s provider=%s",
                user_id,
                provider_id,
            )
            return "connected"
        return "connected" if connected else "needs_reconnect"

    async def start_connect(
        self,
        user_id: str,
        provider_id: str,
        return_origin: Optional[str] = None,
        *,
        channel: str = _WEB_CHANNEL,
        principal: Optional[Principal] = None,
        scopes: Optional[List[str]] = None,
        request: Any = None,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> ConnectInitResponse:
        """Authorize and initialize a channel-neutral OAuth2 connection.

        Args:
            user_id: Navigator user identifier.
            provider_id: Provider identifier, e.g. ``"jira"``.
            return_origin: Web popup origin, validated only for web requests.
            channel: Originating channel.
            principal: Bound platform principal. Required outside web.
            scopes: Requested scopes for PBAC context and response.
            request: aiohttp request used for PBAC evaluation.
            extra_state: Additional signed state fields.

        Returns:
            :class:`~parrot.integrations.oauth2.models.ConnectInitResponse` with
            the authorization URL, opaque state nonce, and scopes.

        Raises:
            ValueError: If ``return_origin`` is not in the allowed origins list.
            ValueError: If ``provider_id`` is not registered.
        """
        registry = OAuth2ProviderRegistry()
        provider = registry.get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")

        requested_scopes = list(scopes or provider.default_scopes)
        if not await self._check_pbac(request, "integration:connect", provider_id, requested_scopes):
            raise PermissionError(f"Not permitted to connect provider {provider_id!r}")

        if channel == _WEB_CHANNEL:
            allowed = _get_allowed_origins()
            if return_origin not in allowed:
                raise ValueError(
                    f"Origin {return_origin!r} is not in the list of allowed OAuth2 "
                    f"return origins.  Allowed: {allowed!r}"
                )
            if principal is None:
                principal = Principal(user_id=user_id, channel=channel, channel_user_id=user_id)
        elif principal is None:
            raise ValueError(f"A principal is required for channel {channel!r}")

        state: Dict[str, Any] = {
            "channel": channel,
            "provider_id": provider_id,
            "return_origin": return_origin,
            **(extra_state or {}),
        }
        auth_url, nonce = await provider.manager.create_authorization_url(
            channel=channel,
            user_id=user_id,
            extra_state=state,
            principal=principal,
        )
        return ConnectInitResponse(
            auth_url=auth_url,
            state=nonce,
            scopes=requested_scopes,
            expires_in=600,
        )

    async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor:
        """Return the PBAC-filtered descriptor for one provider."""
        registry = OAuth2ProviderRegistry()
        provider = registry.get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:list", provider_id):
            raise PermissionError(f"Not permitted to list provider {provider_id!r}")
        row = await get_users_integration(user_id, provider_id)
        return await self._descriptor(user_id, provider, row, request)

    async def disconnect(
        self,
        user_id: str,
        provider_id: str,
        request: Any = None,
    ) -> DisconnectResponse:
        """Revoke and delete one provider connection for a principal.

        Args:
            user_id: Navigator user identifier.
            provider_id: Provider identifier, e.g. ``"jira"``.
            request: aiohttp request used for PBAC evaluation.

        Returns:
            :class:`~parrot.integrations.oauth2.models.DisconnectResponse` with
            ``disconnected=True``.
        """
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:disconnect", provider_id, list(provider.default_scopes)):
            raise PermissionError(f"Not permitted to disconnect provider {provider_id!r}")
        await provider.manager.revoke(channel=_WEB_CHANNEL, user_id=user_id)
        await delete_users_integration(user_id, provider_id)

        logger.info(
            "Disconnected provider=%s for user_id=%s (all agents)",
            provider_id,
            user_id,
        )
        return DisconnectResponse(provider=provider_id, disconnected=True)

    async def persist_credential(
        self,
        user_id: str,
        provider_id: str,
        token_set: Any,
        *,
        channel: str,
        canonical_identity: Optional[str] = None,
    ) -> UsersIntegrationRow:
        """Upsert a ``users_integrations`` row from any provider's token set.

        Called from the web-channel branch of both Jira and the generic
        OAuth2 callback after a successful authorization code exchange.

        Args:
            user_id: Navigator user identifier.
            provider_id: Provider identifier (``"jira"``, ``"o365"``, …).
            token_set: Provider-specific token set (duck-typed). Must
                expose ``account_id``, ``display_name``, ``email``,
                ``scopes``. Optional Jira-only fields (``cloud_id``,
                ``site_url``) are read with ``getattr`` and forwarded
                when present.
            channel: Channel that completed or used the connection.
            canonical_identity: Stable cross-channel identity when known.

        Returns:
            The :class:`~parrot.integrations.oauth2.models.UsersIntegrationRow`
            that was persisted.
        """
        existing = await get_users_integration(user_id, provider_id)
        now = datetime.now(tz=timezone.utc)
        account_id = getattr(token_set, "account_id", "") or ""
        same_account = existing is not None and existing.account_id == account_id
        channels = list(existing.channels) if existing is not None else []
        if channel not in channels:
            channels.append(channel)
        scopes = list(getattr(token_set, "scopes", []) or [])
        row = UsersIntegrationRow(
            user_id=user_id,
            provider=provider_id,
            canonical_identity=canonical_identity or (existing.canonical_identity if existing else None),
            channels=channels,
            status="active",
            account_id=account_id,
            display_name=getattr(token_set, "display_name", "") or "",
            email=getattr(token_set, "email", None),
            scopes=scopes,
            scopes_granted=list(getattr(token_set, "scopes_granted", None) or scopes),
            expires_at=getattr(token_set, "expires_at", None),
            cloud_id=getattr(token_set, "cloud_id", None),
            site_url=getattr(token_set, "site_url", None),
            connected_at=existing.connected_at if same_account else now,
            updated_at=now,
            last_used_at=existing.last_used_at if existing else None,
        )
        await upsert_users_integration(row)
        logger.info(
            "Persisted credential for user_id=%s provider=%s account_id=%s",
            user_id,
            provider_id,
            row.account_id,
        )
        return row

    async def whoami(self, user_id: str, request: Any = None) -> WhoAmI:
        """Return the Navigator identity of the authenticated caller (CLI `parrot whoami`, M2 resolver)."""
        session = None
        if request is not None:
            if hasattr(request, "get"):
                session = request.get("session")
            if session is None:
                session = getattr(request, "session", None)

        def session_value(name: str) -> Any:
            """Read a claim from the session or its common nested claim maps."""
            if session is None:
                return None
            value = getattr(session, name, None)
            if value is None and hasattr(session, "get"):
                value = session.get(name)
            if value is not None:
                return value
            if not hasattr(session, "get"):
                return None
            for container_name in ("userinfo", "session", "token_claims", "claims", "token_info"):
                container = session.get(container_name)
                if isinstance(container, dict) and container.get(name) is not None:
                    return container[name]
            return None

        email = session_value("email")
        roles = session_value("roles") or []
        scopes = session_value("scopes")
        if scopes is None:
            scopes = session_value("scope") or []
        if isinstance(roles, str):
            roles = roles.split()
        if isinstance(scopes, str):
            scopes = scopes.split()
        return WhoAmI(
            user_id=user_id,
            tenant_id=session_value("tenant_id"),
            canonical_identity=session_value("canonical_identity") or email,
            email=email,
            roles=list(roles),
            scopes=list(scopes),
        )

    async def pull_access_token(self, user_id: str, provider_id: str, request: Any = None) -> PulledToken:
        """Vend the provider access token for ``user_id`` (PBAC integration:use, fail closed, audited)."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:use", provider_id, list(provider.default_scopes)):
            raise PermissionError(f"Not permitted to use provider {provider_id!r}")
        principal = Principal(user_id=user_id, channel="cli", channel_user_id=user_id)
        token = await provider.manager.get_valid_token("cli", user_id)
        if token is None:
            auth_url = None
            try:
                connect = await self.start_connect(
                    user_id,
                    provider_id,
                    channel="cli",
                    principal=principal,
                    request=request,
                )
                auth_url = connect.auth_url
            except (PermissionError, ValueError):
                pass
            raise NotConnected(
                AuthRequiredPayload(
                    provider=provider_id,
                    auth_url=auth_url,
                    scopes=list(provider.default_scopes),
                    auth_kind="oauth2",
                    message="not_connected",
                )
            )
        await provider.manager._publish("connection.token_pulled", principal, token)
        return PulledToken(
            provider=provider_id,
            access_token=token.access_token,
            expires_at=float(token.expires_at),
            scopes=list(token.scopes or []),
            account_id=token.account_id or "",
        )

    async def complete_connect(
        self,
        user_id: str,
        provider_id: str,
        *,
        code: str,
        state: str,
        channel: str,
        request: Any = None,
    ) -> IntegrationDescriptor:
        """Paste fallback (S10): verify the nonce belongs to ``user_id``, then exchange + persist."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:connect", provider_id, list(provider.default_scopes)):
            raise PermissionError(f"Not permitted to connect provider {provider_id!r}")
        manager = provider.manager
        raw_state = await manager.redis.get(manager._nonce_key(state))
        if not raw_state:
            raise ValueError("Invalid or expired state nonce.")
        if isinstance(raw_state, bytes):
            raw_state = raw_state.decode("utf-8")
        try:
            state_payload = json.loads(raw_state)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid or expired state nonce.") from exc
        nonce_user_id = state_payload.get("nav_user_id") if isinstance(state_payload, dict) else None
        if nonce_user_id is None or not hmac.compare_digest(str(nonce_user_id), user_id):
            raise ValueError("Invalid or expired state nonce.")
        token_set, state_payload = await manager.handle_callback(code, state)
        await self.persist_credential(
            user_id,
            provider_id,
            token_set,
            channel=channel,
            canonical_identity=state_payload.get("canonical_identity"),
        )
        return await self.status(user_id, provider_id, request)

    async def device_start(
        self,
        user_id: str,
        provider_id: str,
        *,
        principal: Principal,
        request: Any = None,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Start a provider RFC 8628 grant while retaining the device code server-side."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(
            request, "integration:connect", provider_id, list(scopes or provider.default_scopes)
        ):
            raise PermissionError(f"Not permitted to connect provider {provider_id!r}")
        handle, authorization = await provider.manager.start_device_authorization(principal, scopes=scopes)
        return {
            "handle": handle,
            "user_code": authorization.user_code,
            "verification_uri": authorization.verification_uri,
            "verification_uri_complete": authorization.verification_uri_complete,
            "expires_in": authorization.expires_in,
            "interval": authorization.interval,
        }

    async def device_poll(
        self,
        user_id: str,
        provider_id: str,
        *,
        handle: str,
        request: Any = None,
    ) -> Dict[str, Any]:
        """Poll one device grant and persist its completed credential for its owner."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:connect", provider_id, list(provider.default_scopes)):
            raise PermissionError(f"Not permitted to connect provider {provider_id!r}")
        manager = provider.manager
        raw_record = await manager.redis.get(manager._device_key(handle))
        if not raw_record:
            return {"status": "expired"}
        try:
            if isinstance(raw_record, bytes):
                raw_record = raw_record.decode("utf-8")
            record = json.loads(raw_record)
        except (UnicodeDecodeError, TypeError, json.JSONDecodeError):
            logger.warning("Undecodable device authorization record for provider=%s", provider_id)
            return {"status": "failed", "reason": "invalid device authorization record"}
        record_principal = record.get("principal", {}) if isinstance(record, dict) else {}
        owner_user_id = record_principal.get("user_id") if isinstance(record_principal, dict) else None
        if owner_user_id is None or not hmac.compare_digest(str(owner_user_id), user_id):
            raise PermissionError("Device authorization handle does not belong to this user")

        result = await manager.complete_device_authorization(handle)
        if result.get("status") == "completed":
            token_set = result.pop("token_set")
            await self.persist_credential(user_id, provider_id, token_set, channel="cli")
        result.pop("token_set", None)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _check_pbac(
        self,
        request: Any,
        action: str,
        provider_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> bool:
        """Evaluate a PBAC policy for the given action.

        Fails **closed** when the PDP is unavailable (FEAT-144 Q-B resolution).

        Args:
            request: The aiohttp request (may be ``None`` in tests).
            action: PBAC action string, e.g. ``"integration:list"``.
            provider_id: Optional provider identifier used as a context attribute
                on the EvalContext (not baked into the action string).
            scopes: Optional requested scopes included in the PBAC context.

        Returns:
            ``True`` if the action is permitted, ``False`` otherwise.
        """
        if request is None:
            # No request context — fail-closed
            return False

        abac = getattr(request, "app", {}).get("abac") if hasattr(request, "app") else None
        if abac is None:
            # No PDP configured — fail-closed for integrations surface
            return False

        # If a full PBAC evaluator is present, use it.
        # Context: the provider_id is passed as an attribute, not baked into action.
        try:
            ctx: Dict[str, Any] = {"action": action}
            if provider_id:
                ctx["provider"] = provider_id
            if scopes is not None:
                ctx["scopes"] = scopes
            result = await abac.is_allowed(request, ctx)
            return bool(result)
        except Exception:  # noqa: BLE001
            logger.exception(
                "PBAC evaluation failed for action=%s provider=%s — denying",
                action,
                provider_id,
            )
            return False
