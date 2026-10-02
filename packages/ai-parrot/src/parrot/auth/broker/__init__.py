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

from typing import Any

from .byok import _UserLLMKeyResolver  # noqa: F401  (re-exported)
from .core import CredentialBroker, CredentialBrokerConfigError
from .factory import CredentialResolverFactory, _MCPVaultResolver, _VaultStaticKeyResolver  # noqa: F401  (re-exported)

__all__ = [
    "CredentialBroker",
    "CredentialBrokerConfigError",
    "CredentialResolverFactory",
]

_PG_STORE: Any = None


def set_user_llm_key_store(store: Any) -> None:
    """Register the Postgres BYOK store (``get(user_id, provider)``); ``None`` unregisters.

    The server calls this at startup when ``BYOK_STORE=postgres`` so core never imports server code.
    """
    global _PG_STORE
    _PG_STORE = store


def byok_store_setting() -> str:
    """The ``BYOK_STORE`` switch: ``documentdb`` (default) or ``postgres``."""
    from navconfig import config

    value = str(config.get("BYOK_STORE", fallback="documentdb") or "documentdb").strip().lower()
    return value if value in ("documentdb", "postgres") else "documentdb"
