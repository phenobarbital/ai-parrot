"""A2UI emission helper (Module 10).

The pure routing logic that sends an ``OutputMode.A2UI`` response around the legacy
``OutputFormatter``. It lives in the a2ui package (no heavy bot/client deps) so it is
unit-testable in isolation; ``parrot.bots.base`` imports and calls it at both formatter
call sites.
"""

from __future__ import annotations

from typing import Any

from parrot.models.outputs import OutputMode

__all__ = ["finalize_a2ui_response"]


def finalize_a2ui_response(response: Any) -> None:
    """Route an ``OutputMode.A2UI`` response around the legacy formatter (FEAT-273).

    Places the declarative envelope in ``response.a2ui_envelope`` (a plain dict), sets
    ``response.output_mode = OutputMode.A2UI``, and populates a human-readable fallback
    in ``response.response`` — without entering ``OutputFormatter`` or serializing the
    envelope into ``response.output`` (kept intact for legacy consumers).

    Args:
        response: The bot response object (duck-typed: ``a2ui_envelope``/``output``/
            ``response``/``output_mode`` attributes).
    """
    envelope = getattr(response, "a2ui_envelope", None)
    if envelope is None:
        out = getattr(response, "output", None)
        if isinstance(out, dict):
            envelope = out
        else:
            from parrot.outputs.a2ui.models import A2UIMessageBase
            from parrot.outputs.a2ui.serialization import serialize

            if isinstance(out, A2UIMessageBase):
                envelope = serialize(out)
    response.a2ui_envelope = envelope
    response.output_mode = OutputMode.A2UI
    if not getattr(response, "response", None):
        title = _surface_id(envelope)
        response.response = f"[A2UI surface: {title}]" if title else "[A2UI surface]"


def _surface_id(envelope: Any) -> str | None:
    """Best-effort surface id from a serialized envelope, for the text fallback.

    The v1.0 wire nests the surface under its message key
    (``{"version": "v1.0", "createSurface": {"surfaceId": ...}}``), so the id is
    one level down. A bare inner message (``{"surfaceId": ...}``) is also
    accepted, since ``response.output`` may carry one.

    Args:
        envelope: The serialized envelope, or anything else.

    Returns:
        The surface id, or ``None`` when it cannot be determined.
    """
    if not isinstance(envelope, dict):
        return None
    inner = envelope.get("createSurface")
    if isinstance(inner, dict) and isinstance(inner.get("surfaceId"), str):
        return inner["surfaceId"]
    surface_id = envelope.get("surfaceId")
    return surface_id if isinstance(surface_id, str) else None
