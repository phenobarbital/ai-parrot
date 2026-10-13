"""Typed post-processors for spoken form answers (FEAT-653).

``normalize_spoken`` turns a transcript into the canonical value its field type expects. It is
pure and sync (the audio engine never awaits) and never raises.
"""

from __future__ import annotations

import importlib
import logging

from ...core.types import FieldType
from ...services.validators import EMAIL_PATTERN
from .base import REFINABLE_TYPES, NormalizeContext, NormalizeResult
from .numbers import normalize_number

logger = logging.getLogger(__name__)

__all__ = [
    "REFINABLE_TYPES",
    "NormalizeContext",
    "NormalizeResult",
    "normalize_spoken",
    "validate_typed",
]

# field type → (module under audio.normalize, function). Resolved lazily so the family modules
# (email/phone: TASK-4246, temporal: TASK-4247) can be added without editing this file.
_REGISTRY: dict[FieldType, tuple[str, str]] = {
    FieldType.EMAIL: ("email", "normalize_email"),
    FieldType.PHONE: ("phone", "normalize_phone"),
    FieldType.DATE: ("temporal", "normalize_date"),
    FieldType.TIME: ("temporal", "normalize_time"),
    FieldType.DATETIME: ("temporal", "normalize_datetime"),
}


def normalize_spoken(field_type: FieldType, text: str, *, ctx: NormalizeContext) -> NormalizeResult | None:
    """Dispatch to the family normalizer; None when the type is not handled (caller keeps the raw text). Never raises."""
    if field_type == FieldType.NUMBER:
        return normalize_number(text, ctx, integer=False)
    if field_type == FieldType.INTEGER:
        return normalize_number(text, ctx, integer=True)
    target = _REGISTRY.get(field_type)
    if target is None:
        return None
    try:
        module = importlib.import_module(f"{__name__}.{target[0]}")
        return getattr(module, target[1])(text, ctx)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.warning("normalizer %s.%s failed: %s", target[0], target[1], type(exc).__name__)
        return NormalizeResult.rejected("no_parse")


def validate_typed(field_type: FieldType, value: str) -> str | None:
    """Typed-answer check: 'INVALID_EMAIL' for a non-empty EMAIL value failing EMAIL_PATTERN; else None."""
    if field_type == FieldType.EMAIL and value.strip() and not EMAIL_PATTERN.match(value.strip()):
        return "INVALID_EMAIL"
    return None
