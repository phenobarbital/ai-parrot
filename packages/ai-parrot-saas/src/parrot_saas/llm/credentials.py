"""Names and lookup for a tenant's own LLM credentials.

Two things live here and nowhere else: what a stored secret is *called*, and
what happens when it is missing.

The names matter beyond this module. The same strings are what the secrets API
accepts as a path segment, and what
``parrot.auth.broker._VaultStaticKeyResolver`` derives by default
(``vault_key = f"{provider}:api_key"``) — so a tenant that stores
``anthropic:api_key`` gets both its agent credentials and its tool credentials
from one entry. Keeping the constants in one place is what makes that true.

Nothing here ever puts a secret value in an exception message, a log record or
a repr. ``TenantCredentialMissing`` carries the *name* of the key, never the
value it failed to find.
"""
from __future__ import annotations

from typing import Any

#: Secret holding the tenant's Google GenAI API key (triage, and later Veo/Imagen).
GOOGLE_API_KEY_SECRET = "google:api_key"

#: Secret holding the tenant's Anthropic API key (reply drafting).
ANTHROPIC_API_KEY_SECRET = "anthropic:api_key"


class TenantCredentialMissing(RuntimeError):
    """A tenant has not supplied a credential its agents need.

    Raised at runtime-construction time rather than mid-flow: a run that dies
    three nodes in has already published a reply, and the operator sees a
    confusing partial execution instead of "this tenant has no Anthropic key".

    Attributes:
        tenant_id: The tenant whose credential is missing.
        key: Name of the missing secret. Never its value.
    """

    def __init__(self, tenant_id: str, key: str) -> None:
        self.tenant_id = tenant_id
        self.key = key
        super().__init__(
            f"tenant {tenant_id!r} has no credential stored under {key!r}"
        )


async def require_secret(store: Any, tenant_id: str, key: str) -> str:
    """Read a tenant secret, refusing to return an empty one.

    An absent key and a blank one have to be treated alike. Neither provider
    client validates its key at construction: a ``None`` key makes the SDK
    fall back to the process-wide environment variable, and a blank one fails
    much later as a 401 from the provider. Both outcomes are worse than an
    error here.

    Args:
        store: A :class:`~parrot.security.secrets.SecretStore`.
        tenant_id: Tenant owning the secret.
        key: Secret name, e.g. :data:`GOOGLE_API_KEY_SECRET`.

    Returns:
        The secret value.

    Raises:
        TenantCredentialMissing: If the secret is absent or blank.
    """
    value = await store.get(tenant_id, key)
    if not value or not value.strip():
        raise TenantCredentialMissing(tenant_id, key)
    return value


__all__ = (
    "ANTHROPIC_API_KEY_SECRET",
    "GOOGLE_API_KEY_SECRET",
    "TenantCredentialMissing",
    "require_secret",
)
