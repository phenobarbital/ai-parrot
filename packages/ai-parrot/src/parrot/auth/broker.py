"""Surface-agnostic CredentialBroker and CredentialResolverFactory (FEAT-264).

The :class:`CredentialBroker` owns a ``provider_id → resolver`` registry built
once from declarative :class:`~parrot.auth.credentials.ProviderCredentialConfig`
entries (per-agent config or an in-package YAML manifest).

The :class:`CredentialResolverFactory` maps an ``auth`` kind
(``obo | oauth2 | static_key | mcp``) to a fully-constructed
:class:`~parrot.auth.credentials.CredentialResolver` strategy so that adding
a new provider on an existing auth kind requires only a config entry.

Design principles
-----------------
* **One signal, N renderers** — the broker returns
  :class:`~parrot.auth.credentials.ResolvedCredential` on success or
  :class:`~parrot.auth.credentials.NeedsAuth` on a miss.  It never renders
  UX; surfaces own card / link generation.
* **Secret hygiene** — the raw secret lives only on
  :class:`~parrot.auth.credentials.ResolvedCredential` and never enters the
  broker's logs.  Only the ``key_fingerprint`` is recorded in the audit ledger.
* **Fail-closed** — no resolver for a provider → ``KeyError``; no identity
  → caller must fail closed; ``resolver.resolve() is None`` → ``NeedsAuth``.
* **Pure construction** — :meth:`CredentialBroker.from_config` is synchronous
  and performs no I/O so it is safe to call from ``AbstractBot.configure()``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from .credentials import (
    CredentialResolver,
    NeedsAuth,
    ProviderCredentialConfig,
    ResolvedCredential,
)

if TYPE_CHECKING:  # pragma: no cover
    from parrot.security.audit_ledger import AuditLedger
    from parrot.auth.identity import CanonicalIdentityMapper

__all__ = [
    "CredentialBroker",
    "CredentialBrokerConfigError",
    "CredentialResolverFactory",
]

logger = logging.getLogger(__name__)


class CredentialBrokerConfigError(Exception):
    """Raised by :meth:`CredentialBroker.from_config` in strict mode when a
    resolver cannot be built for a declared provider.

    Inherits from ``Exception`` directly so callers can catch it without
    depending on any domain-specific base class.
    """



# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class CredentialResolverFactory:
    """Maps ``auth`` kind to a constructed :class:`CredentialResolver` strategy.

    Strategies are built lazily from a :class:`ProviderCredentialConfig` and
    injected dependencies.  The factory itself performs no I/O.

    Supported kinds
    ---------------
    ``obo``
        OBO exchange via ``WorkIQOBOCredentialResolver``
        (``O365Interface.acquire_token_on_behalf_of`` + ``VaultTokenSync``).
    ``oauth2``
        Generic OAuth2 3LO via :class:`~parrot.auth.credentials.OAuthCredentialResolver`.
    ``static_key``
        Static API-key with OOB capture via ``FirefliesCredentialResolver``
        (or any vault-backed static resolver).
    ``mcp``
        Thin MCP-backed strategy: reads a bearer token from vault and
        applies it per-call.  Integrated with TASK-1676.

    Dependency injection
    --------------------
    The deps dict carries the runtime objects the factory needs to construct
    resolvers (e.g. ``o365_interface``, ``vault``, ``oauth_manager``).
    These are never passed via the declarative config; they are provided by
    the broker builder in :meth:`CredentialBroker.from_config`.

    Args:
        deps: Runtime dependency mapping supplied by the caller
              (e.g. ``{"vault": vault_token_sync, "o365": o365_interface}``).
    """

    def __init__(self, deps: Optional[Dict[str, Any]] = None) -> None:
        self._deps: Dict[str, Any] = deps or {}

    def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver:
        """Build a :class:`CredentialResolver` for *cfg*.

        Args:
            cfg: Declarative provider credential configuration.

        Returns:
            A fully-constructed :class:`CredentialResolver`.

        Raises:
            ValueError: If ``cfg.auth`` is not a supported kind.
            KeyError: If a required dependency is missing from *deps*.
        """
        kind = cfg.auth
        opts = cfg.options

        if kind == "obo":
            return self._build_obo(cfg, opts)
        if kind == "oauth2":
            return self._build_oauth2(cfg, opts)
        if kind == "static_key":
            return self._build_static_key(cfg, opts)
        if kind == "mcp":
            return self._build_mcp(cfg, opts)
        if kind == "device_code":
            return self._build_device_code(cfg, opts)

        raise ValueError(
            f"CredentialResolverFactory: unknown auth kind {kind!r} for provider "
            f"{cfg.provider!r}. Supported: obo, oauth2, static_key, mcp, device_code."
        )

    # ------------------------------------------------------------------
    # Strategy builders
    # ------------------------------------------------------------------

    def _build_obo(
        self, cfg: ProviderCredentialConfig, opts: Dict[str, Any]
    ) -> CredentialResolver:
        """Build a WorkIQOBOCredentialResolver (or compatible OBO resolver).

        Expected deps: ``o365_interface``, ``o365_oauth_manager``, ``vault``.
        Expected opts: ``scope`` (defaults to WORKIQ_SCOPE).
        """
        try:
            from parrot.auth.oauth2.workiq_provider import (
                WorkIQOBOCredentialResolver,
                WORKIQ_SCOPE,
            )
        except ImportError as exc:
            raise ImportError(
                "parrot.auth.oauth2.workiq_provider is required for auth='obo'."
            ) from exc

        o365 = self._deps.get("o365_interface")
        o365_manager = self._deps.get("o365_oauth_manager")
        vault = self._deps.get("vault")
        scope = opts.get("scope", WORKIQ_SCOPE)

        return WorkIQOBOCredentialResolver(
            o365_interface=o365,
            o365_oauth_manager=o365_manager,
            vault_token_sync=vault,
            workiq_scope=scope,
        )

    def _build_oauth2(
        self, cfg: ProviderCredentialConfig, opts: Dict[str, Any]
    ) -> CredentialResolver:
        """Build an OAuthCredentialResolver.

        Expected deps: ``oauth_manager`` (or ``oauth_managers`` dict keyed by provider).
        """
        from .credentials import OAuthCredentialResolver

        manager = self._deps.get("oauth_manager") or self._deps.get(
            "oauth_managers", {}
        ).get(cfg.provider)
        if manager is None:
            raise KeyError(
                f"CredentialResolverFactory: 'oauth_manager' dep required for "
                f"auth='oauth2' (provider={cfg.provider!r})"
            )
        return OAuthCredentialResolver(manager)

    def _build_static_key(
        self, cfg: ProviderCredentialConfig, opts: Dict[str, Any]
    ) -> CredentialResolver:
        """Build a FirefliesCredentialResolver (or generic vault static-key resolver).

        Expected deps: ``vault``.
        Expected opts: ``capture_url``.
        """
        try:
            from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver
        except ImportError:
            # Fallback: build a minimal vault-backed static-key resolver inline.
            # This avoids a hard dependency on ai-parrot-integrations in the core.
            return _VaultStaticKeyResolver(
                vault=self._deps.get("vault"),
                vault_key=opts.get("vault_key", f"{cfg.provider}:api_key"),
                capture_url=opts.get("capture_url", ""),
            )

        vault = self._deps.get("vault")
        capture_url = opts.get("capture_url", "")
        return FirefliesCredentialResolver(
            vault_token_sync=vault,
            oob_capture_url=capture_url,
        )

    def _build_mcp(
        self, cfg: ProviderCredentialConfig, opts: Dict[str, Any]
    ) -> CredentialResolver:
        """Build a thin MCP-backed vault resolver.

        Reads a bearer token from vault keyed by ``vault_key`` option.
        Expected deps: ``vault``.
        Expected opts: ``vault_key``, ``auth_url``.
        """
        vault = self._deps.get("vault")
        vault_key = opts.get("vault_key", f"{cfg.provider}:token")
        auth_url = opts.get("auth_url", "")
        return _MCPVaultResolver(vault=vault, vault_key=vault_key, auth_url=auth_url)

    def _build_device_code(
        self, cfg: ProviderCredentialConfig, opts: Dict[str, Any]
    ) -> CredentialResolver:
        """Build an O365DeviceCodeCredentialResolver (FEAT-266).

        Expected deps: ``o365_client`` (or ``o365_interface``),
        ``o365_oauth_manager``, ``vault``.
        Expected opts: ``scopes`` (defaults to ``DEFAULT_O365_SCOPES`` inside
        the resolver when omitted/``None``).
        """
        try:
            from parrot.auth.oauth2.o365_devicecode_provider import (
                O365DeviceCodeCredentialResolver,
            )
        except ImportError as exc:
            raise ImportError(
                "parrot.auth.oauth2.o365_devicecode_provider is required for "
                "auth='device_code'."
            ) from exc

        o365 = self._deps.get("o365_client") or self._deps.get("o365_interface")
        manager = self._deps.get("o365_oauth_manager")
        vault = self._deps.get("vault")
        if o365 is None or manager is None or vault is None:
            raise KeyError(
                "CredentialResolverFactory: 'o365_client'/'o365_interface', "
                "'o365_oauth_manager', and 'vault' deps are required for "
                f"auth='device_code' (provider={cfg.provider!r})"
            )
        scopes = opts.get("scopes")

        return O365DeviceCodeCredentialResolver(
            o365_client=o365,
            o365_oauth_manager=manager,
            vault_token_sync=vault,
            scopes=scopes,
        )


# ---------------------------------------------------------------------------
# Fallback / MCP strategy implementations
# ---------------------------------------------------------------------------


class _VaultStaticKeyResolver(CredentialResolver):
    """Minimal vault-backed static-key resolver (no integrations package dep).

    Used when ``ai-parrot-integrations`` is not installed but auth=``static_key``
    is requested.
    """

    def __init__(self, vault: Any, vault_key: str, capture_url: str) -> None:
        self._vault = vault
        self._vault_key = vault_key
        self._capture_url = capture_url

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        if self._vault is None:
            return None
        tokens = await self._vault.read_tokens(user_id)
        return tokens.get(self._vault_key)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return self._capture_url

    async def store_key(self, user_id: str, api_key: str) -> None:
        """Store the user's static API key in vault."""
        if self._vault is not None:
            await self._vault.store_tokens(user_id, {self._vault_key: api_key})


class _MCPVaultResolver(CredentialResolver):
    """Thin MCP-backed vault resolver for auth=``mcp`` providers."""

    def __init__(self, vault: Any, vault_key: str, auth_url: str) -> None:
        self._vault = vault
        self._vault_key = vault_key
        self._auth_url = auth_url

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        if self._vault is None:
            return None
        tokens = await self._vault.read_tokens(user_id)
        return tokens.get(self._vault_key)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return self._auth_url


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------


class CredentialBroker:
    """Surface-agnostic per-user credential broker.

    Owns a ``provider_id → resolver`` registry and resolves per-user
    credentials at tool-invocation time.  On a successful resolution it
    appends a signed entry to the optional :class:`~parrot.security.audit_ledger.AuditLedger`;
    on a miss it returns :class:`~parrot.auth.credentials.NeedsAuth` (never
    raises on its own — the caller raises :class:`~parrot.auth.credentials.CredentialRequired`
    for surfaces to catch).

    Usage
    -----
    .. code-block:: python

        broker = CredentialBroker.from_config(
            configs=[
                ProviderCredentialConfig(provider="workiq", auth="obo",
                                         options={"scope": "..."}),
            ],
            o365_interface=o365,
            o365_oauth_manager=mgr,
            vault=vault,
            audit_ledger=ledger,
        )
        result = await broker.resolve("workiq", "a2a:copilot", "user@example.com")
        if isinstance(result, NeedsAuth):
            raise CredentialRequired(result.provider, result.auth_url, result.auth_kind)

    Args:
        audit_ledger: Optional canonical
            :class:`~parrot.security.audit_ledger.AuditLedger`.  When supplied
            a signed entry is appended on every successful resolution.
        identity_mapper: Optional :class:`~parrot.auth.identity.CanonicalIdentityMapper`
            for cross-surface identity normalization.
    """

    def __init__(
        self,
        *,
        audit_ledger: Optional["AuditLedger"] = None,
        identity_mapper: Optional["CanonicalIdentityMapper"] = None,
    ) -> None:
        # Stores (resolver, auth_kind) tuples so NeedsAuth.auth_kind is read
        # from the registry rather than sniffed from the class name.
        self._resolvers: Dict[str, Tuple[CredentialResolver, str]] = {}
        self._audit_ledger = audit_ledger
        self._identity_mapper = identity_mapper
        self.logger = logging.getLogger(__name__)

    def register(
        self,
        provider: str,
        resolver: CredentialResolver,
        auth_kind: str = "oauth2",
    ) -> None:
        """Register a resolver for *provider*.

        Args:
            provider: Provider identifier (e.g. ``"workiq"``).
            resolver: :class:`CredentialResolver` for this provider.
            auth_kind: The authentication kind for this provider
                (``"obo"``, ``"oauth2"``, ``"static_key"``, ``"mcp"``).
                Stored alongside the resolver and returned in
                :class:`~parrot.auth.credentials.NeedsAuth` on a miss.
                Defaults to ``"oauth2"`` for backward compatibility with
                callers that do not supply an explicit kind.
        """
        self._resolvers[provider] = (resolver, auth_kind)
        self.logger.info(
            "CredentialBroker: registered resolver for provider=%s auth_kind=%s",
            provider,
            auth_kind,
        )

    @classmethod
    def from_config(
        cls,
        configs: List[ProviderCredentialConfig],
        strict: bool = True,
        **deps: Any,
    ) -> "CredentialBroker":
        """Build a broker from a list of declarative provider configs.

        This is a **pure construction** call — no I/O, safe to call from
        ``AbstractBot.configure()``.

        Args:
            configs: Declarative provider credential configurations.
            strict: When ``True`` (default), a resolver build failure raises
                :class:`CredentialBrokerConfigError` immediately.  When
                ``False``, the failing provider is skipped with a warning
                and the broker is returned with the remaining providers.
            **deps: Runtime dependencies forwarded to
                :class:`CredentialResolverFactory`
                (e.g. ``vault``, ``o365_interface``, ``audit_ledger``).

        Returns:
            A fully-configured :class:`CredentialBroker`.

        Raises:
            CredentialBrokerConfigError: If ``strict=True`` and a resolver
                build fails for any provider.
        """
        audit_ledger = deps.pop("audit_ledger", None)
        identity_mapper = deps.pop("identity_mapper", None)
        factory = CredentialResolverFactory(deps=deps)
        broker = cls(audit_ledger=audit_ledger, identity_mapper=identity_mapper)
        for cfg in configs:
            try:
                resolver = factory.build(cfg)
                broker.register(cfg.provider, resolver, auth_kind=str(cfg.auth))
            except Exception as exc:
                if strict:
                    raise CredentialBrokerConfigError(
                        f"Failed to build resolver for provider {cfg.provider!r}: {exc}"
                    ) from exc
                logger.warning(
                    "CredentialBroker.from_config: could not build resolver for "
                    "provider=%s auth=%s: %s",
                    cfg.provider,
                    cfg.auth,
                    exc,
                )
        return broker

    async def resolve(
        self,
        provider: str,
        channel: str,
        user_id: str,
        **ctx: Any,
    ) -> "ResolvedCredential | NeedsAuth":
        """Resolve the per-user credential for *provider*.

        Args:
            provider: Provider identifier.
            channel: Invocation channel (e.g. ``"a2a:copilot"``); used for
                audit context only (vault keyed by canonical identity).
            user_id: Canonical per-user identity.  If an
                ``identity_mapper`` is set it is applied first; otherwise
                the raw value is used.
            **ctx: Extra context forwarded to the resolver (e.g. ``tool_name``).

        Returns:
            :class:`ResolvedCredential` on success (audit entry appended) or
            :class:`NeedsAuth` on a miss.

        Raises:
            KeyError: If no resolver is registered for *provider* (fail closed).
            ValueError: If *user_id* is empty / None (fail closed).
        """
        # Canonical identity normalization.
        # NOTE: surfaces (A2AServer, ParrotM365Agent) already call
        # identity_mapper.to_canonical() on the raw surface dict before
        # invoking the broker, so ``user_id`` is already canonical here.
        # A second call would crash because to_canonical() expects a
        # Dict[str, Any], not a str.  We use user_id as-is.
        canonical_id = user_id

        if not canonical_id:
            raise ValueError(
                f"CredentialBroker.resolve: no identity for provider={provider!r}; "
                "failing closed (no service-identity fallback)."
            )

        entry = self._resolvers.get(provider)
        if entry is None:
            raise KeyError(
                f"CredentialBroker: no resolver registered for provider={provider!r}. "
                "Failing closed."
            )

        resolver, auth_kind = entry
        secret = await resolver.resolve(channel, canonical_id)

        if secret is None:
            # Miss — resolver signals the user has not yet authorized.
            auth_url = await resolver.get_auth_url(channel, canonical_id)
            self.logger.info(
                "CredentialBroker: miss provider=%s user=%s → NeedsAuth",
                provider,
                canonical_id,
            )
            return NeedsAuth(
                provider=provider,
                auth_url=auth_url,
                auth_kind=auth_kind,
            )

        # Hit — build fingerprint (SHA-256 of secret material, never logged)
        from parrot.security.audit_ledger import derive_key_fingerprint

        fingerprint = derive_key_fingerprint(secret)
        credential = ResolvedCredential(
            provider=provider,
            secret=secret,
            key_fingerprint=fingerprint,
        )

        # Append to audit ledger (never the raw secret — fingerprint only)
        if self._audit_ledger is not None:
            tool_name = ctx.get("tool_name", "unknown")
            try:
                await self._audit_ledger.append(
                    user_id=canonical_id,
                    channel=channel,
                    tool=str(tool_name),
                    provider=provider,
                    credential_material=secret,
                )
            except Exception as exc:
                self.logger.warning(
                    "CredentialBroker: audit append failed provider=%s user=%s: %s",
                    provider,
                    canonical_id,
                    exc,
                )

        self.logger.info(
            "CredentialBroker: resolved provider=%s user=%s fingerprint=%s...",
            provider,
            canonical_id,
            fingerprint[:8],
        )
        return credential

