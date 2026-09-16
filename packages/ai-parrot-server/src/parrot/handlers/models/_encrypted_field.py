"""Transparent authenticated encryption for postgres TEXT columns.

Used by :class:`UserBotModel` to seal/unseal ``mcp_config`` and ``tools_config``
blobs which may contain credentials. Reuses the vault key ring of
:mod:`parrot.security.credentials_utils`, so existing master keys cover this
table without further configuration.

Plaintext shape is JSON-serialisable (typically a list of dicts).

Each blob is sealed with envelope v2 and bound — through AEAD associated data —
to its ``(user_id, chatbot_id, field)`` tuple, so ciphertext substitution
between rows or columns fails authentication. Before FEAT-099 the binding was
an in-plaintext ``{"_v": 1, "_ctx": {...}, "v": ...}`` envelope (AAD was not
exposed then); those legacy blobs are converted by the offline migrator
(``navigator-vault migrate``), which verifies the old envelope before re-sealing.

Security Note:
    Never log plaintext or ciphertext values.
"""
from __future__ import annotations

from typing import Any, Optional

from navigator_session.vault import VaultContext, VaultCryptoError
from parrot.security.credentials_utils import (
    decrypt_credential,
    encrypt_credential,
    normalize_user_id,
)
from parrot.security.vault_utils import get_vault_keyring

USER_BOT_PURPOSE = "parrot-user-bot"
USER_BOT_FIELDS = ("mcp_config", "tools_config")

# Legacy (pre-FEAT-099) in-plaintext envelope, still read by the migrator hook.
LEGACY_ENVELOPE_VERSION = 1
_VERSION_KEY = "_v"
_CTX_KEY = "_ctx"
_VALUE_KEY = "v"


def user_bot_context(user_id: Any, chatbot_id: Any, field: str) -> VaultContext:
    """Context binding one sealed column of one user bot.

    Args:
        user_id: Owning user id.
        chatbot_id: Owning bot id (UUID or str; encoded as ``str``).
        field: ``mcp_config`` or ``tools_config``.

    Raises:
        ValueError: On an unknown field or a missing bot id.
    """
    if field not in USER_BOT_FIELDS:
        raise ValueError(f"unknown sealed field {field!r}")
    if chatbot_id in (None, ""):
        raise ValueError("chatbot_id is required for sealed user-bot fields")
    return VaultContext(
        purpose=USER_BOT_PURPOSE,
        layer="db",
        fields=(
            ("user_id", normalize_user_id(user_id)),
            ("chatbot_id", str(chatbot_id)),
            ("field", field),
        ),
    )


def _legacy_ctx(user_id: Any, chatbot_id: Any, field: str) -> dict:
    """Canonical context dict of the legacy in-plaintext envelope."""
    return {"u": int(user_id), "c": str(chatbot_id), "f": str(field)}


def seal(
    value: Any,
    *,
    user_id: int,
    chatbot_id: Any,
    field: str,
) -> Optional[str]:
    """Encrypt a JSON-serialisable value bound to ``(user_id, chatbot_id, field)``.

    The binding is the AEAD associated data, so a ciphertext moved to another
    user, bot or column fails to open.

    Args:
        value: Anything JSON-serialisable. ``None`` / empty containers
            collapse to ``NULL`` to keep the column NULLable.
        user_id: Owning user id; bound into the ciphertext.
        chatbot_id: Owning bot id (UUID, str, etc.); bound as ``str(chatbot_id)``.
        field: Logical column name (``mcp_config`` / ``tools_config``).

    Returns:
        Base64 ciphertext string, or ``None`` for empty values.

    Raises:
        RuntimeError: If the vault keys are not configured.
        ValueError: If ``field`` or ``chatbot_id`` is invalid.
    """
    if value in (None, [], {}, ""):
        return None
    context = user_bot_context(user_id, chatbot_id, field)
    return encrypt_credential({_VALUE_KEY: value}, context, get_vault_keyring())


def unseal(
    blob: Optional[str],
    *,
    user_id: int,
    chatbot_id: Any,
    field: str,
) -> Any:
    """Decrypt a base64 ciphertext string bound to the expected context.

    Args:
        blob: Base64 ciphertext string from the database, or ``None``.
        user_id: Expected owning user id.
        chatbot_id: Expected owning bot id.
        field: Expected logical column name.

    Returns:
        Original plaintext value, or ``None`` if ``blob`` is empty / NULL.

    Raises:
        ValueError: If the ciphertext does not belong to this
            ``(user_id, chatbot_id, field)`` tuple, or is a legacy blob that
            has not been migrated yet.
        RuntimeError: If the vault keys are not configured.
    """
    if not blob:
        return None
    context = user_bot_context(user_id, chatbot_id, field)
    try:
        payload = decrypt_credential(blob, context, get_vault_keyring())
    except VaultCryptoError as err:
        raise ValueError(
            "Sealed blob context mismatch: ciphertext does not belong to this "
            "(user_id, chatbot_id, field) tuple, or it is a legacy blob that "
            f"must be migrated ({type(err).__name__})."
        ) from None
    if not isinstance(payload, dict) or _VALUE_KEY not in payload:
        raise ValueError(
            "Sealed blob missing or unsupported payload; row must be "
            "re-encrypted under the current schema version."
        )
    return payload[_VALUE_KEY]


def unwrap_legacy_envelope(
    plaintext: bytes, *, user_id: Any, chatbot_id: Any, field: str
) -> bytes:
    """Verify a legacy ``_ctx`` envelope and return the inner value's bytes.

    Used by the migration target: a legacy blob that was already substituted
    between rows/columns must not be legitimised as a v2 ciphertext.

    Args:
        plaintext: Decrypted v1 plaintext (orjson-encoded envelope).
        user_id: Row's user id.
        chatbot_id: Row's bot id.
        field: Column being migrated.

    Returns:
        orjson bytes of ``{"v": <original value>}`` ready to be re-sealed.

    Raises:
        ValueError: If the envelope is missing, unsupported, or its context
            does not match the row.
    """
    import orjson  # local import: only the migrator needs it

    payload = orjson.loads(plaintext)
    if (
        not isinstance(payload, dict)
        or payload.get(_VERSION_KEY) != LEGACY_ENVELOPE_VERSION
        or _CTX_KEY not in payload
        or _VALUE_KEY not in payload
    ):
        raise ValueError(
            "Sealed blob missing or unsupported context envelope; row must "
            "be re-encrypted under the current schema version."
        )
    if payload[_CTX_KEY] != _legacy_ctx(user_id, chatbot_id, field):
        raise ValueError(
            "Sealed blob context mismatch: ciphertext does not belong to "
            "this (user_id, chatbot_id, field) tuple."
        )
    return orjson.dumps({_VALUE_KEY: payload[_VALUE_KEY]})
