"""Content-hash sealing for BOE article versions (FEAT-449 R3/R11).

The span existence gate (FEAT-449 span verifier) can only be deterministic
if every stored ``articulo.versions[]`` entry carries a sealed
``content_hash`` computed over the *exact* text that is stored — hash what
you store, slice what you stored.

``HASH_NORM_VERSION`` MUST only be bumped alongside a migration plan:
changing the normalization contract invalidates every previously stored
span (recomputed hashes would no longer match, and existing span offsets
would no longer index the same normalized text).
"""

from __future__ import annotations

import hashlib
import unicodedata

HASH_NORM_VERSION = 1
"""Normalization contract version. Bump ONLY with a migration plan —
changing this invalidates every stored span."""


def normalize_for_hash(text: str) -> str:
    """Normalize text before hashing and storage.

    Applies Unicode NFC composition and newline normalization
    (``\\r\\n`` or ``\\r`` -> ``\\n``). NOTHING else — no whitespace
    collapse, no stripping. Offsets derived later must index text
    identical to what the lawyer is shown (R11).

    Args:
        text: Raw extracted text.

    Returns:
        NFC-normalized text with newlines normalized to ``\\n``.
    """
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")


def seal_hash(normalized_text: str) -> str:
    """Compute the sealed content hash over already-normalized text.

    Args:
        normalized_text: Text that has already been passed through
            ``normalize_for_hash`` (or is otherwise known to already be
            in normalized form).

    Returns:
        sha256 hex digest over the UTF-8 encoding of ``normalized_text``.
    """
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
