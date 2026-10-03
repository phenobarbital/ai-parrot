"""The surface-agnostic :class:`CredentialBroker` (FEAT-264)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..credentials import (
    CredentialResolver,
    NeedsAuth,
    ProviderCredentialConfig,
    ResolvedCredential,
)
from .factory import CredentialResolverFactory

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.identity import CanonicalIdentityMapper
    from parrot.security.audit_ledger import AuditLedger

logger = logging.getLogger("parrot.auth.broker")


class CredentialBrokerConfigError(Exception):
    """Raised by :meth:`CredentialBroker.from_config` in strict mode when a
    resolver cannot be built for a declared provider.

    Inherits from ``Exception`` directly so callers can catch it without
    depending on any domain-specific base class.
    """


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
        audit_ledger: AuditLedger | None = None,
        identity_mapper: CanonicalIdentityMapper | None = None,
    ) -> None:
        # Stores (resolver, auth_kind) tuples so NeedsAuth.auth_kind is read
        # from the registry rather than sniffed from the class name.
        self._resolvers: dict[str, tuple[CredentialResolver, str]] = {}
        self._audit_ledger = audit_ledger
        self._identity_mapper = identity_mapper
        self.logger = logging.getLogger("parrot.auth.broker")

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
        configs: list[ProviderCredentialConfig],
        strict: bool = True,
        **deps: Any,
    ) -> CredentialBroker:
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
                    "CredentialBroker.from_config: could not build resolver for " "provider=%s auth=%s: %s",
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
    ) -> ResolvedCredential | NeedsAuth:
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
            raise KeyError(f"CredentialBroker: no resolver registered for provider={provider!r}. " "Failing closed.")

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
