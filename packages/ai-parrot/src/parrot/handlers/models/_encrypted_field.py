"""Transparent AES-GCM encryption helpers for postgres TEXT columns.

Used by :class:`UserBotModel` to seal/unseal ``mcp_config`` and ``tools_config``
blobs which may contain credentials. Reuses the same vault key system as
:mod:`parrot.handlers.credentials_utils` so existing master keys cover this
table without further configuration.

Plaintext shape is JSON-serialisable (typically a list of dicts).

Each sealed blob carries an embedded ``_ctx`` envelope binding the ciphertext
to a specific ``(user_id, chatbot_id, field)`` tuple. The envelope is
verified on :func:`unseal` and ciphertext substitution between rows or
columns raises :class:`ValueError`. This is the in-plaintext substitute for
AES-GCM AAD because the underlying ``encrypt_for_db`` helper from
``navigator-session`` does not expose an AAD parameter.

Schema version 1 envelope::

    {"_v": 1, "_ctx": {"u": <int>, "c": <str>, "f": <str>}, "v": <plaintext>}
"""
from __future__ import annotations

from typing import Any, Optional

from parrot.handlers.credentials_utils import (
    decrypt_credential,
    encrypt_credential,
)
from parrot.handlers.vault_utils import load_vault_keys


_ENVELOPE_VERSION = 1
_VERSION_KEY = "_v"
_CTX_KEY = "_ctx"
_VALUE_KEY = "v"


def _build_ctx(user_id: int, chatbot_id: Any, field: str) -> dict:
    """Build the canonical context dict used in the sealed envelope."""
    return {
        "u": int(user_id),
        "c": str(chatbot_id),
        "f": str(field),
    }


def seal(
    value: Any,
    *,
    user_id: int,
    chatbot_id: Any,
    field: str,
) -> Optional[str]:
    """Encrypt a JSON-serialisable value bound to ``(user_id, chatbot_id, field)``.

    The bound context is verified on :func:`unseal`, defending against
    ciphertext substitution between rows (user A → user B) or between
    columns (mcp_config → tools_config) by a database-layer attacker.

    Args:
        value: Anything JSON-serialisable. ``None`` / empty containers
            collapse to ``NULL`` to keep the column NULLable.
        user_id: Owning user id; bound into the ciphertext.
        chatbot_id: Owning bot id (UUID, str, etc.); bound into the
            ciphertext as ``str(chatbot_id)``.
        field: Logical column name (e.g. ``"mcp_config"``); bound into the
            ciphertext to prevent column-swap attacks.

    Returns:
        Base64 ciphertext string, or ``None`` for empty values.

    Raises:
        RuntimeError: If the vault keys are not configured.
    """
    if value in (None, [], {}, ""):
        return None
    active_key_id, active_key, _ = load_vault_keys()
    envelope = {
        _VERSION_KEY: _ENVELOPE_VERSION,
        _CTX_KEY: _build_ctx(user_id, chatbot_id, field),
        _VALUE_KEY: value,
    }
    return encrypt_credential(envelope, active_key_id, active_key)


def unseal(
    blob: Optional[str],
    *,
    user_id: int,
    chatbot_id: Any,
    field: str,
) -> Any:
    """Decrypt a base64 ciphertext string and verify its bound context.

    Args:
        blob: Base64 ciphertext string from the database, or ``None``.
        user_id: Expected owning user id.
        chatbot_id: Expected owning bot id.
        field: Expected logical column name.

    Returns:
        Original plaintext value, or ``None`` if ``blob`` is empty / NULL.

    Raises:
        ValueError: If the sealed blob is missing its ``_ctx`` envelope
            (legacy schema) or the embedded context does not match the
            expected ``(user_id, chatbot_id, field)`` tuple.
        KeyError: If the embedded key version is not present in the
            configured vault keys.
    """
    if not blob:
        return None
    _, _, all_keys = load_vault_keys()
    payload = decrypt_credential(blob, all_keys)
    if (
        not isinstance(payload, dict)
        or payload.get(_VERSION_KEY) != _ENVELOPE_VERSION
        or _CTX_KEY not in payload
        or _VALUE_KEY not in payload
    ):
        raise ValueError(
            "Sealed blob missing or unsupported context envelope; row must "
            "be re-encrypted under the current schema version."
        )
    expected = _build_ctx(user_id, chatbot_id, field)
    if payload[_CTX_KEY] != expected:
        raise ValueError(
            "Sealed blob context mismatch: ciphertext does not belong to "
            "this (user_id, chatbot_id, field) tuple."
        )
    return payload[_VALUE_KEY]
