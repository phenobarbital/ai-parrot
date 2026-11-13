"""Process-wide registry of string gate kinds."""

from __future__ import annotations

from .models import GateError, GateErrorCode

_KINDS: dict[str, str] = {}


def register_gate_kind(kind: str, *, description: str = "") -> None:
    """Register ``kind``; idempotent for an identical description, GATE_KIND_CONFLICT otherwise."""
    if not kind.strip():
        raise ValueError("Gate kind must not be empty or whitespace")

    existing_description = _KINDS.get(kind)
    if existing_description is None:
        _KINDS[kind] = description
        return

    if existing_description != description:
        raise GateError(
            GateErrorCode.GATE_KIND_CONFLICT,
            f"Gate kind {kind!r} is already registered with a different description",
        )


def is_registered(kind: str) -> bool:
    """Return True when ``kind`` was registered."""
    return kind in _KINDS


def registered_kinds() -> dict[str, str]:
    """Return a copy of the registry."""
    return dict(_KINDS)
