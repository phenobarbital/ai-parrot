"""Per-user "bring your own key" LLM key resolver (FEAT-467 TASK-2516)."""

from __future__ import annotations

import logging

from parrot.auth import broker as _pkg  # patched/registered globals (``_PG_STORE``) are read at call time

from ..credentials import CredentialResolver

logger = logging.getLogger("parrot.auth.broker")


class _UserLLMKeyResolver(CredentialResolver):
    """Resolves a per-user "bring your own key" LLM provider API key
    (FEAT-467 TASK-2516).

    Distinct from every other resolver in this module (all of which
    resolve an AGENT's credential for an OAuth/static-key EXTERNAL
    service, declared via :class:`ProviderCredentialConfig`): this one
    resolves a SESSION USER's own LLM API key for Studio test/ask runs.
    ``channel`` here IS the LLM provider id (e.g. ``"anthropic"``,
    matching ``parrot.clients.factory.SUPPORTED_CLIENTS`` keys), not an
    OAuth "channel" concept.

    Reads the SAME durable store ``handlers/studio/byok.py``'s
    ``StudioKeysHandler`` writes to — the DocumentDB collection
    ``"user_llm_keys"`` — decrypting with the navigator-session AES-GCM
    vault helpers (:mod:`parrot.security.credentials_utils`). Fails
    CLOSED (returns ``None``) on any missing dependency, vault-key, or
    decrypt error — a BYOK lookup failure must never break agent
    creation/testing; callers fall back to the server's own configured
    LLM credentials.
    """

    COLLECTION: str = "user_llm_keys"

    async def resolve(self, channel: str, user_id: str) -> str | None:
        """Return the decrypted API key for ``(provider=channel, user_id)``.

        Args:
            channel: LLM provider id (normalized lowercase before lookup).
            user_id: Session user id, as stored by ``StudioKeysHandler``.

        Returns:
            The plaintext API key, or ``None`` if none is stored, the
            vault is unavailable, or decryption fails.
        """
        if _pkg.byok_store_setting() == "postgres":
            return await self._resolve_postgres(channel, user_id)

        from parrot.interfaces.documentdb import DocumentDb

        try:
            from parrot.security.credentials_utils import decrypt_credential, llm_key_context
            from parrot.security.vault_utils import get_vault_keyring
        except ImportError:
            logger.debug("_UserLLMKeyResolver: navigator_session.vault not available.")
            return None

        try:
            keyring = get_vault_keyring()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("_UserLLMKeyResolver: failed to load vault master keys: %s", exc)
            return None

        provider = channel.lower()
        try:
            async with DocumentDb() as db:
                doc = await db.read_one(self.COLLECTION, {"user_id": user_id, "provider": provider})
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "_UserLLMKeyResolver: DocumentDB read failed for user=%s " "provider=%s: %s",
                user_id,
                provider,
                exc,
            )
            return None

        if doc is None:
            return None

        try:
            credential = decrypt_credential(
                doc["api_key"], llm_key_context(user_id, provider), keyring
            )
            return credential.get("api_key")
        except Exception as exc:  # pylint: disable=broad-except
            # NEVER log the raw doc/ciphertext — only the failure.
            logger.warning(
                "_UserLLMKeyResolver: failed to decrypt key for user=%s " "provider=%s: %s",
                user_id,
                provider,
                exc,
            )
            return None

    async def _resolve_postgres(self, channel: str, user_id: str) -> str | None:
        """``BYOK_STORE=postgres``: read the registered store; fail closed, never touch DocumentDB."""
        if _pkg._PG_STORE is None:
            logger.warning("_UserLLMKeyResolver: BYOK_STORE=postgres but no store is registered")
            return None
        try:
            return await _pkg._PG_STORE.get(user_id, channel.lower())
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("_UserLLMKeyResolver: postgres read failed for provider=%s: %s", channel.lower(), exc)
            return None

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """No OOB auth flow for BYOK — users submit their key directly via
        ``POST /api/v1/astudio/keys``."""
        return ""
