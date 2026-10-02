"""BYOK — per-user LLM API keys (FEAT-467 TASK-2516).

Keys are persisted encrypted per-user via the existing navigator-session
AES-GCM vault (NOT Fernet — Fernet does not exist in this codebase),
following the ``CredentialsHandler`` storage discipline (``handlers/
credentials.py``): a session-vault hot copy plus a fire-and-forget
DocumentDB durable copy (collection ``"user_llm_keys"``). Keys are NEVER
returned in plaintext — GET only ever returns a masked preview.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from navigator_auth.decorators import is_authenticated, user_session
from parrot.auth.broker import _UserLLMKeyResolver, byok_store_setting
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.interfaces.documentdb import DocumentDb
from parrot.security.credentials_utils import (
    decrypt_credential,
    encrypt_credential,
    llm_key_context,
)
from parrot.security.vault_utils import get_vault_keyring
from pydantic import ValidationError

from ._base import StudioBaseView
from .models import ByokKeyRequest, StudioError

COLLECTION = "user_llm_keys"
SESSION_PREFIX = "_byok:"


def _vault_keyring():
    """Process-wide vault KeyRing (FEAT-099).

    Returns:
        ``navigator_session.vault.KeyRing`` built from the vault env vars.

    Raises:
        RuntimeError: If vault keys are not configured/available.
    """
    return get_vault_keyring()


def _mask(api_key: str) -> str:
    """Mask an API key, showing first 3 + last 4 chars max (spec §7 Key
    Constraints — never expose more than that)."""
    if len(api_key) <= 7:
        return "*" * len(api_key)
    return f"{api_key[:3]}…{api_key[-4:]}"


async def resolve_user_api_key(app: Any, user_id: str, provider: str) -> str | None:
    """Resolve a user's stored BYOK API key for ``provider``.

    Used by the Studio testing surface (FEAT-467 TASK-2517) to pass
    ``api_key=`` into ``LLMFactory.create(...)`` for test/ask runs.
    Delegates to :class:`parrot.auth.broker._UserLLMKeyResolver` (the
    SAME decrypt path this module's own GET uses) — this function takes
    only ``app`` (no per-request session), so it always reads the
    DocumentDB durable copy; the session-vault hot copy is a per-request
    fast path only reachable from inside a live Studio handler request
    (see :class:`StudioKeysHandler`).

    Args:
        app: The aiohttp Application (unused directly today — accepted
            for signature stability / future app-scoped caching).
        user_id: Session user id, as stored by :class:`StudioKeysHandler`.
        provider: LLM provider id (normalized lowercase before lookup).

    Returns:
        The plaintext API key, or ``None`` if none is stored or the
        vault/DB is unavailable — callers pass this straight through to
        ``LLMFactory.create(..., api_key=api_key)``, whose own ``api_key
        =None`` default already falls back to the server's configured key.
    """
    if byok_store_setting() == "postgres" and app.get("database") is not None:
        from .storage.byok_store import get_byok_store

        get_byok_store(app)  # registers the Postgres store with the core resolver
    resolver = _UserLLMKeyResolver()
    return await resolver.resolve(provider, user_id)


@is_authenticated()
@user_session()
class StudioKeysHandler(StudioBaseView):
    """``/api/v1/astudio/keys`` and ``/api/v1/astudio/keys/{provider}``.

    GET (masked list), POST (store — encrypted, session vault + DocumentDB
    dual-write), DELETE (remove both copies).
    """

    def _error(self, message: str, *, status: int, code: str | None = None):
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )

    async def get(self):
        user = await self._get_user()

        try:
            keyring = _vault_keyring()
        except RuntimeError as exc:
            self.logger.error("BYOK: vault key loading failed: %s", exc)
            return self._error(
                "Encryption service unavailable.",
                status=503,
                code="vault_unavailable",
            )

        try:
            keys = await self._list_keys(user, keyring)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("BYOK: failed to list keys for user %s: %s", user.user_id, exc)
            return self._error("Failed to list keys.", status=500, code="list_failed")

        return self.json_response({"keys": keys, "count": len(keys)})

    async def _list_keys(self, user, keyring) -> list[dict]:
        """Masked key previews from the store ``BYOK_STORE`` selects."""
        if byok_store_setting() == "postgres":
            from .storage.byok_store import get_byok_store

            return await get_byok_store(self.request.app).list_masked(user.user_id)
        async with DocumentDb() as db:
            docs = await db.read(COLLECTION, {"user_id": user.user_id})
        return [self._masked_item(doc, user, keyring) for doc in docs or []]

    def _masked_item(self, doc: dict, user, keyring) -> dict:
        """One DocumentDB doc as a masked list item (``****`` when it cannot be decrypted)."""
        try:
            credential = decrypt_credential(
                doc["api_key"], llm_key_context(user.user_id, doc.get("provider")), keyring
            )
            masked = _mask(credential.get("api_key", ""))
        except Exception as exc:  # pylint: disable=broad-except
            # NEVER log the raw doc/ciphertext.
            self.logger.warning(
                "BYOK: failed to decrypt key for masking (provider=%s): %s",
                doc.get("provider"),
                exc,
            )
            masked = "****"
        return {"provider": doc.get("provider"), "masked": masked, "created_at": doc.get("created_at")}

    async def post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("keys", "astudio:keys:store")) is not None:
            return denied

        if self.request.match_info.get("provider"):
            return self._error(
                "Use POST /astudio/keys (no provider in the URL) to store a key.",
                status=400,
                code="invalid_route",
            )

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            key_request = ByokKeyRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        provider = key_request.provider.lower()
        if provider not in SUPPORTED_CLIENTS:
            return self._error(
                f"Unsupported provider '{provider}'. Supported: " f"{sorted(SUPPORTED_CLIENTS)}.",
                status=400,
                code="invalid_provider",
            )

        try:
            keyring = _vault_keyring()
        except RuntimeError as exc:
            self.logger.error("BYOK: vault key loading failed: %s", exc)
            return self._error(
                "Encryption service unavailable.",
                status=503,
                code="vault_unavailable",
            )

        user = await self._get_user()
        plaintext = key_request.api_key.get_secret_value()
        encrypted = encrypt_credential(
            {"api_key": plaintext}, llm_key_context(user.user_id, provider), keyring
        )

        # Session vault hot copy (pattern: CredentialsHandler._set_session_credential).
        session = await self._resolve_session()
        if session is not None:
            try:
                session[f"{SESSION_PREFIX}{provider}"] = encrypted
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("BYOK: failed to set session vault copy: %s", exc)

        try:
            await self._persist_key(user, provider, encrypted, plaintext)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("BYOK: failed to persist key (provider=%s): %s", provider, exc)
            return self._error("Failed to store key.", status=500, code="store_failed")

        # NEVER echo the plaintext back — masked preview only.
        return self.json_response({"provider": provider, "masked": _mask(plaintext)}, status=201)

    async def _persist_key(self, user, provider: str, encrypted: str, plaintext: str) -> None:
        """Durable write to the store ``BYOK_STORE`` selects."""
        if byok_store_setting() == "postgres":
            from .storage.byok_store import get_byok_store

            await get_byok_store(self.request.app).put(user.user_id, provider, plaintext)
            return
        now = datetime.now(UTC)
        doc = {
            "user_id": user.user_id,
            "provider": provider,
            "api_key": encrypted,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        async with DocumentDb() as db:
            await db.documentdb_connect()
            existing = await db.read_one(COLLECTION, {"user_id": user.user_id, "provider": provider})
            if existing is not None:
                doc["created_at"] = existing.get("created_at", doc["created_at"])
            # Adversarial-review fix: save_background() is an INSERT —
            # re-storing a key for a provider the user already has
            # created a duplicate document, so rotation could silently
            # keep serving the stale key (read_one on duplicates is
            # order-dependent). update(..., upsert=True) replaces the
            # single (user_id, provider) document atomically.
            await db.update(
                COLLECTION,
                {"user_id": user.user_id, "provider": provider},
                {"$set": doc},
                upsert=True,
            )

    async def _remove_key(self, user, provider: str) -> None:
        """Durable delete from the store ``BYOK_STORE`` selects."""
        if byok_store_setting() == "postgres":
            from .storage.byok_store import get_byok_store

            await get_byok_store(self.request.app).delete(user.user_id, provider)
            return
        async with DocumentDb() as db:
            await db.delete(COLLECTION, {"user_id": user.user_id, "provider": provider})

    async def delete(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("keys", "astudio:keys:delete")) is not None:
            return denied

        provider = self.request.match_info.get("provider")
        if not provider:
            return self._error("Provider is required.", status=400, code="missing_provider")
        provider = provider.lower()

        user = await self._get_user()

        session = await self._resolve_session()
        if session is not None:
            try:
                session.pop(f"{SESSION_PREFIX}{provider}", None)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("BYOK: failed to clear session vault copy: %s", exc)

        try:
            await self._remove_key(user, provider)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("BYOK: failed to delete key (provider=%s): %s", provider, exc)
            return self._error("Failed to delete key.", status=500, code="delete_failed")

        return self.json_response({"provider": provider, "deleted": True})
