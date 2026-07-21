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
        title = envelope.get("surfaceId") if isinstance(envelope, dict) else None
        response.response = f"[A2UI surface: {title}]" if title else "[A2UI surface]"
