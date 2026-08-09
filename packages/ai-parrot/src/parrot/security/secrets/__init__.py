"""Tenant-scoped secret custody (BYOK).

Exports the :class:`SecretStore` port, the in-memory implementation used by
tests, and the adapter that lets any store satisfy the credential broker's
``vault`` dependency.

The encrypted Postgres backend is exported lazily so that importing this
package does not require ``asyncdb`` or ``cryptography`` to be installed.
"""
from typing import TYPE_CHECKING, Any

from .base import (
    MasterKeyUnavailable,
    SecretDecryptionError,
    SecretMeta,
    SecretStore,
    SecretStoreError,
)
from .memory import InMemorySecretStore
from .vault_adapter import SecretStoreVault

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .postgres import EncryptedPostgresSecretStore

__all__ = (
    "EncryptedPostgresSecretStore",
    "InMemorySecretStore",
    "MasterKeyUnavailable",
    "SecretDecryptionError",
    "SecretMeta",
    "SecretStore",
    "SecretStoreError",
    "SecretStoreVault",
)

_LAZY_EXPORTS = {
    "EncryptedPostgresSecretStore": (
        "parrot.security.secrets.postgres",
        "EncryptedPostgresSecretStore",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562)."""
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
