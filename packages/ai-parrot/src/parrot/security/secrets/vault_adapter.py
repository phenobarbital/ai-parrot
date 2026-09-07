"""Adapt a :class:`SecretStore` to the credential broker's ``vault`` dependency.

:class:`parrot.auth.broker.CredentialResolverFactory` builds its ``static_key``
and ``mcp`` strategies around an injected object it calls ``"vault"``, but no
concrete implementation ships in the repository — it has always been supplied
by the caller. This adapter is that implementation, so BYOK reuses the existing
FEAT-264 credential path (including its audit-ledger fingerprinting) instead of
growing a second, parallel one.

The contract, read off the two in-repo consumers
(``_VaultStaticKeyResolver`` and ``_MCPVaultResolver``), is three coroutines::

    async read_tokens(subject_id)          -> dict[str, str]
    async store_tokens(subject_id, tokens) -> None
    async delete_tokens(subject_id, keys)  -> None

``subject_id``
--------------
The resolvers pass their ``user_id`` argument as ``subject_id``. For
tenant-owned credentials the caller must pass the **tenant slug** there. That
overloading is inherited from the broker's signature, not introduced here, and
it is called out explicitly so nobody later assumes the subject is always a
user: :meth:`SecretStoreVault.read_tokens` is scoping by whatever it is given.
"""
from __future__ import annotations

import logging
from typing import Iterable, Mapping, Optional

from .base import SecretStore


class SecretStoreVault:
    """Expose a :class:`SecretStore` through the broker's ``vault`` protocol.

    Example:
        >>> vault = SecretStoreVault(store)
        >>> factory = CredentialResolverFactory(deps={"vault": vault})

        With ``ProviderCredentialConfig(provider="anthropic",
        auth="static_key", options={"vault_key": "anthropic:api_key"})`` the
        resolver then reads that tenant's own Anthropic key.
    """

    def __init__(self, store: SecretStore) -> None:
        """Wrap ``store``.

        Args:
            store: The backing secret store. Its tenant scoping is preserved:
                every call here forwards ``subject_id`` as ``tenant_id``.
        """
        self._store = store
        self.logger = logging.getLogger("parrot.security.secrets.vault")

    @property
    def store(self) -> SecretStore:
        """The wrapped store."""
        return self._store

    async def read_tokens(self, subject_id: str) -> dict[str, str]:
        """Return every secret owned by ``subject_id`` as a flat mapping.

        The broker's resolvers index the result by their configured
        ``vault_key``, so the mapping is keyed exactly as the secrets were
        stored (conventionally ``"<provider>:<field>"``).

        Args:
            subject_id: Tenant slug (or user id, depending on the caller).

        Returns:
            Mapping of secret key to plaintext value. Empty when the subject
            owns nothing.
        """
        tokens: dict[str, str] = {}
        for meta in await self._store.list_keys(subject_id):
            value = await self._store.get(subject_id, meta.key)
            if value is not None:
                tokens[meta.key] = value
        return tokens

    async def store_tokens(
        self, subject_id: str, tokens: Mapping[str, str]
    ) -> None:
        """Persist a mapping of secrets for ``subject_id``.

        Args:
            subject_id: Tenant slug (or user id, depending on the caller).
            tokens: Mapping of secret key to plaintext value.
        """
        for key, value in tokens.items():
            await self._store.put(subject_id, key, value)
        # Log the key names only — never the values, and never the count of
        # characters, which would leak information about the material.
        self.logger.debug(
            "stored %d secret(s) for subject %s: %s",
            len(tokens),
            subject_id,
            sorted(tokens),
        )

    async def delete_tokens(
        self, subject_id: str, keys: Optional[Iterable[str]] = None
    ) -> None:
        """Delete some or all of ``subject_id``'s secrets.

        Args:
            subject_id: Tenant slug (or user id, depending on the caller).
            keys: Secret names to remove. When omitted, every secret owned by
                the subject is removed.
        """
        if keys is None:
            keys = [meta.key for meta in await self._store.list_keys(subject_id)]
        for key in keys:
            await self._store.delete(subject_id, key)


__all__ = ("SecretStoreVault",)
