"""The :class:`SecretStore` port — tenant-scoped custody of secret material.

This is the abstraction behind BYOK ("bring your own key"): a customer supplies
their own provider API keys and the platform holds them on their behalf. It is
deliberately narrow, and two of its properties are load-bearing rather than
stylistic:

* **Values are write-only through the API.** :class:`SecretMeta` has no field
  capable of carrying a secret, so a handler cannot leak one by serialising a
  listing. Retrieval is a separate, explicit :meth:`SecretStore.get`.
* **Every operation is tenant-scoped.** ``tenant_id`` is the first positional
  parameter of every method, with no default, so "which tenant?" can never be
  answered implicitly.

The port is defined in ``ai-parrot`` core rather than in the SaaS package
because :class:`parrot.auth.broker.CredentialResolverFactory` — which lives
here — consumes an implementation as its ``"vault"`` dependency. See
:mod:`parrot.security.secrets.vault_adapter`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class SecretStoreError(RuntimeError):
    """Base class for secret-store failures."""


class MasterKeyUnavailable(SecretStoreError):
    """Raised when key material required to encrypt or decrypt is missing.

    Always fatal at construction time. A secret store must never fall back to
    an ephemeral, self-generated key: doing so silently produces ciphertext
    that no later process can read, which looks like data loss rather than a
    configuration error.
    """


class SecretDecryptionError(SecretStoreError):
    """Raised when stored ciphertext cannot be authenticated or decrypted.

    With AAD-bound envelopes this is also what a *relocated* row looks like —
    ciphertext copied to another tenant or another key fails authentication
    rather than decrypting into someone else's secret.
    """


@dataclass(frozen=True, slots=True)
class SecretMeta:
    """Everything about a stored secret except the secret.

    Attributes:
        tenant_id: Owning tenant.
        key: Logical name, conventionally ``"<provider>:<field>"`` (e.g.
            ``"anthropic:api_key"``) so it lines up with the credential
            broker's ``vault_key`` option.
        fingerprint: SHA-256 hex digest of the value, from
            :func:`parrot.security.audit_ledger.derive_key_fingerprint`. Lets
            a key be correlated across systems — and lets a caller check
            whether an upload changed anything — without either side seeing
            plaintext.
        created_at: First write.
        updated_at: Most recent write.
    """

    tenant_id: str
    key: str
    fingerprint: str
    created_at: datetime
    updated_at: datetime


class SecretStore(ABC):
    """Tenant-scoped store for secret values.

    Implementations must guarantee that no method returns, logs, or otherwise
    emits a secret value except :meth:`get`.
    """

    @abstractmethod
    async def get(self, tenant_id: str, key: str) -> Optional[str]:
        """Return a secret value.

        Args:
            tenant_id: Owning tenant.
            key: Secret name.

        Returns:
            The plaintext value, or ``None`` when the tenant has no such key.

        Raises:
            SecretDecryptionError: If stored ciphertext fails authentication.
        """

    @abstractmethod
    async def put(self, tenant_id: str, key: str, value: str) -> SecretMeta:
        """Create or replace a secret value.

        Args:
            tenant_id: Owning tenant.
            key: Secret name.
            value: Plaintext to store.

        Returns:
            Metadata for the stored secret. The value is never echoed back.
        """

    @abstractmethod
    async def delete(self, tenant_id: str, key: str) -> bool:
        """Remove a secret.

        Args:
            tenant_id: Owning tenant.
            key: Secret name.

        Returns:
            ``True`` if a secret was removed, ``False`` if none existed.
        """

    @abstractmethod
    async def list_keys(self, tenant_id: str) -> list[SecretMeta]:
        """List a tenant's secrets as metadata only.

        Args:
            tenant_id: Owning tenant.

        Returns:
            Metadata for every secret the tenant owns, ordered by key.
        """

    async def rotate_dek(self, tenant_id: str) -> int:
        """Re-encrypt a tenant's secrets under a fresh data-encryption key.

        The default is a no-op for stores that do not use an envelope.

        Args:
            tenant_id: Tenant whose secrets should be re-encrypted.

        Returns:
            Number of secrets re-encrypted.
        """
        return 0

    async def rotate_kek(self) -> int:
        """Re-wrap every data-encryption key under the active master key.

        Ciphertexts are untouched — re-wrapping only the DEKs is the whole
        point of an envelope. The default is a no-op for stores that do not
        use one.

        Returns:
            Number of data-encryption keys re-wrapped.
        """
        return 0

    async def aclose(self) -> None:
        """Release any resources held by the store."""
        return None

    async def __aenter__(self) -> "SecretStore":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the store on context exit."""
        await self.aclose()


__all__ = (
    "MasterKeyUnavailable",
    "SecretDecryptionError",
    "SecretMeta",
    "SecretStore",
    "SecretStoreError",
)
