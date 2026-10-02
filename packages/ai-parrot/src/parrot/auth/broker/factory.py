"""Strategy factory for the CredentialBroker (FEAT-264) and its vault-backed fallback resolvers."""

from __future__ import annotations

from typing import Any

from ..credentials import CredentialResolver, ProviderCredentialConfig
from .byok import _UserLLMKeyResolver


class CredentialResolverFactory:
    """Maps ``auth`` kind to a constructed :class:`CredentialResolver` strategy.

    Strategies are built lazily from a :class:`ProviderCredentialConfig` and
    injected dependencies.  The factory itself performs no I/O.

    Supported kinds
    ---------------
    ``obo``
        OBO exchange via ``WorkIQOBOCredentialResolver``
        (``O365Client.acquire_token_on_behalf_of`` + ``VaultTokenSync``).
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

    def __init__(self, deps: dict[str, Any] | None = None) -> None:
        self._deps: dict[str, Any] = deps or {}

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

    def _build_obo(self, cfg: ProviderCredentialConfig, opts: dict[str, Any]) -> CredentialResolver:
        """Build a WorkIQOBOCredentialResolver (or compatible OBO resolver).

        Expected deps: ``o365_interface``, ``o365_oauth_manager``, ``vault``.
        Expected opts: ``scope`` (defaults to WORKIQ_SCOPE).
        """
        try:
            from parrot.auth.oauth2.workiq_provider import (
                WORKIQ_SCOPE,
                WorkIQOBOCredentialResolver,
            )
        except ImportError as exc:
            raise ImportError("parrot.auth.oauth2.workiq_provider is required for auth='obo'.") from exc

        o365 = self._deps.get("o365_interface")
        o365_manager = self._deps.get("o365_oauth_manager")
        vault = self._deps.get("vault")
        if o365 is None or o365_manager is None or vault is None:
            raise KeyError(
                "CredentialResolverFactory: 'o365_interface', "
                "'o365_oauth_manager', and 'vault' deps are required for "
                f"auth='obo' (provider={cfg.provider!r})"
            )
        scope = opts.get("scope", WORKIQ_SCOPE)

        return WorkIQOBOCredentialResolver(
            o365_interface=o365,
            o365_oauth_manager=o365_manager,
            vault_token_sync=vault,
            workiq_scope=scope,
        )

    def _build_oauth2(self, cfg: ProviderCredentialConfig, opts: dict[str, Any]) -> CredentialResolver:
        """Build an OAuthCredentialResolver.

        Expected deps: ``oauth_manager`` (or ``oauth_managers`` dict keyed by provider).
        """
        from ..credentials import OAuthCredentialResolver

        manager = self._deps.get("oauth_manager") or self._deps.get("oauth_managers", {}).get(cfg.provider)
        if manager is None:
            raise KeyError(
                f"CredentialResolverFactory: 'oauth_manager' dep required for "
                f"auth='oauth2' (provider={cfg.provider!r})"
            )
        return OAuthCredentialResolver(manager)

    def _build_static_key(self, cfg: ProviderCredentialConfig, opts: dict[str, Any]) -> CredentialResolver:
        """Build a FirefliesCredentialResolver (or generic vault static-key resolver).

        Expected deps: ``vault``.
        Expected opts: ``capture_url``.
        """
        try:
            from parrot.integrations.mcp.fireflies_a2a import (
                FirefliesCredentialResolver,
            )
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

    def _build_mcp(self, cfg: ProviderCredentialConfig, opts: dict[str, Any]) -> CredentialResolver:
        """Build a thin MCP-backed vault resolver.

        Reads a bearer token from vault keyed by ``vault_key`` option.
        Expected deps: ``vault``.
        Expected opts: ``vault_key``, ``auth_url``.
        """
        vault = self._deps.get("vault")
        vault_key = opts.get("vault_key", f"{cfg.provider}:token")
        auth_url = opts.get("auth_url", "")
        return _MCPVaultResolver(vault=vault, vault_key=vault_key, auth_url=auth_url)

    def _build_device_code(self, cfg: ProviderCredentialConfig, opts: dict[str, Any]) -> CredentialResolver:
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
                "parrot.auth.oauth2.o365_devicecode_provider is required for " "auth='device_code'."
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

    def build_user_llm_key_resolver(self) -> CredentialResolver:
        """Build a :class:`_UserLLMKeyResolver` (FEAT-467 TASK-2516 — BYOK).

        NOT wired into the ``cfg.auth``-driven :meth:`build` dispatch above:
        every other strategy resolves an AGENT's credential for an
        externally-declared provider (:class:`ProviderCredentialConfig`,
        whose ``auth`` field is a closed ``Literal`` — ``obo``/``oauth2``/
        ``static_key``/``mcp``/``device_code``). BYOK resolves a SESSION
        USER's own bring-your-own LLM key and has no such declarative
        config; it is session-user-driven, not agent-declared. Exposed as
        its own factory method so callers still obtain a resolver
        uniformly through :class:`CredentialResolverFactory` (spec §3
        Module 8: "registered with CredentialResolverFactory").

        Returns:
            A stateless :class:`_UserLLMKeyResolver` instance.
        """
        return _UserLLMKeyResolver()


class _VaultStaticKeyResolver(CredentialResolver):
    """Minimal vault-backed static-key resolver (no integrations package dep).

    Used when ``ai-parrot-integrations`` is not installed but auth=``static_key``
    is requested.
    """

    def __init__(self, vault: Any, vault_key: str, capture_url: str) -> None:
        self._vault = vault
        self._vault_key = vault_key
        self._capture_url = capture_url

    async def resolve(self, channel: str, user_id: str) -> Any | None:
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

    async def resolve(self, channel: str, user_id: str) -> Any | None:
        if self._vault is None:
            return None
        tokens = await self._vault.read_tokens(user_id)
        return tokens.get(self._vault_key)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return self._auth_url
