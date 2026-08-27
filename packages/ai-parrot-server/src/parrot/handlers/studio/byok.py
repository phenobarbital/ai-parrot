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
from parrot.auth.broker import _UserLLMKeyResolver
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.interfaces.documentdb import DocumentDb
from parrot.security.credentials_utils import decrypt_credential, encrypt_credential
from pydantic import ValidationError

try:
    from navigator_session.vault.config import get_active_key_id, load_master_keys
except ImportError:  # pragma: no cover — navigator-session always installed in prod
    get_active_key_id = None  # type: ignore[assignment]
    load_master_keys = None   # type: ignore[assignment]

from ._base import StudioBaseView
from .models import ByokKeyRequest, StudioError

COLLECTION = "user_llm_keys"
SESSION_PREFIX = "_byok:"


def _load_vault_keys() -> tuple[int, bytes, dict]:
    """Load vault master keys (soft-import guard — pattern:
    ``handlers/credentials.py::_load_vault_keys``).

    Returns:
        Tuple of (active_key_id, active_master_key, all_master_keys).

    Raises:
        RuntimeError: If vault keys are not configured/available.
    """
    if load_master_keys is None or get_active_key_id is None:
        raise RuntimeError(
            "navigator_session.vault.config is not available. "
            "Ensure navigator-session is installed."
        )
    master_keys = load_master_keys()
    active_key_id = get_active_key_id()
    active_key = master_keys[active_key_id]
    return active_key_id, active_key, master_keys


def _mask(api_key: str) -> str:
    """Mask an API key, showing first 3 + last 4 chars max (spec §7 Key
    Constraints — never expose more than that)."""
    if len(api_key) <= 7:
        return "*" * len(api_key)
    return f"{api_key[:3]}…{api_key[-4:]}"


async def resolve_user_api_key(
    app: Any, user_id: str, provider: str
) -> str | None:
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
    del app  # reserved for future app-scoped caching; unused today.
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
            _, _, master_keys = _load_vault_keys()
        except RuntimeError as exc:
            self.logger.error("BYOK: vault key loading failed: %s", exc)
            return self._error(
                "Encryption service unavailable.",
                status=503,
                code="vault_unavailable",
            )

        try:
            async with DocumentDb() as db:
                docs = await db.read(COLLECTION, {"user_id": user.user_id})
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("BYOK: failed to list keys for user %s: %s", user.user_id, exc)
            return self._error(
                "Failed to list keys.", status=500, code="list_failed"
            )

        keys = []
        for doc in docs or []:
            try:
                credential = decrypt_credential(doc["api_key"], master_keys)
                masked = _mask(credential.get("api_key", ""))
            except Exception as exc:  # pylint: disable=broad-except
                # NEVER log the raw doc/ciphertext.
                self.logger.warning(
                    "BYOK: failed to decrypt key for masking (provider=%s): %s",
                    doc.get("provider"), exc,
                )
                masked = "****"
            keys.append({
                "provider": doc.get("provider"),
                "masked": masked,
                "created_at": doc.get("created_at"),
            })

        return self.json_response({"keys": keys, "count": len(keys)})

    async def post(self):
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
            return self._error(
                f"Invalid request: {exc}", status=400, code="invalid_request"
            )

        provider = key_request.provider.lower()
        if provider not in SUPPORTED_CLIENTS:
            return self._error(
                f"Unsupported provider '{provider}'. Supported: "
                f"{sorted(SUPPORTED_CLIENTS)}.",
                status=400,
                code="invalid_provider",
            )

        try:
            active_key_id, active_key, _ = _load_vault_keys()
        except RuntimeError as exc:
            self.logger.error("BYOK: vault key loading failed: %s", exc)
            return self._error(
                "Encryption service unavailable.",
                status=503,
                code="vault_unavailable",
            )

        user = await self._get_user()
        plaintext = key_request.api_key.get_secret_value()
        encrypted = encrypt_credential({"api_key": plaintext}, active_key_id, active_key)

        # Session vault hot copy (pattern: CredentialsHandler._set_session_credential).
        session = await self._resolve_session()
        if session is not None:
            try:
                session[f"{SESSION_PREFIX}{provider}"] = encrypted
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("BYOK: failed to set session vault copy: %s", exc)

        now = datetime.now(UTC)
        doc = {
            "user_id": user.user_id,
            "provider": provider,
            "api_key": encrypted,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        try:
            async with DocumentDb() as db:
                await db.documentdb_connect()
                existing = await db.read_one(
                    COLLECTION, {"user_id": user.user_id, "provider": provider}
                )
                if existing is not None:
                    doc["created_at"] = existing.get("created_at", doc["created_at"])
                db.save_background(
                    COLLECTION,
                    doc,
                    on_error=lambda e: self.logger.warning(
                        "BYOK: background save failed (provider=%s): %s",
                        provider, e,
                    ),
                )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("BYOK: failed to persist key (provider=%s): %s", provider, exc)
            return self._error("Failed to store key.", status=500, code="store_failed")

        # NEVER echo the plaintext back — masked preview only.
        return self.json_response(
            {"provider": provider, "masked": _mask(plaintext)}, status=201
        )

    async def delete(self):
        provider = self.request.match_info.get("provider")
        if not provider:
            return self._error(
                "Provider is required.", status=400, code="missing_provider"
            )
        provider = provider.lower()

        user = await self._get_user()

        session = await self._resolve_session()
        if session is not None:
            try:
                session.pop(f"{SESSION_PREFIX}{provider}", None)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("BYOK: failed to clear session vault copy: %s", exc)

        try:
            async with DocumentDb() as db:
                await db.delete(COLLECTION, {"user_id": user.user_id, "provider": provider})
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("BYOK: failed to delete key (provider=%s): %s", provider, exc)
            return self._error("Failed to delete key.", status=500, code="delete_failed")

        return self.json_response({"provider": provider, "deleted": True})
