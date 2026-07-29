# packages/ai-parrot/src/parrot/outputs/cards/attachment.py
"""Bot Framework attachment envelope helpers."""
from __future__ import annotations

from typing import Any

AC_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


def build_attachment(card: dict[str, Any]) -> dict[str, Any]:
    """Wrap a rendered Adaptive Card JSON payload in a Bot Framework attachment.

    Args:
        card: A JSON-serializable Adaptive Card payload (e.g. the output
            of :func:`parrot.outputs.cards.renderer.render`).

    Returns:
        A Bot Framework attachment envelope with ``contentType`` set to
        the Adaptive Card content type and ``content`` set to ``card``.
    """
    return {"contentType": AC_CONTENT_TYPE, "content": card}


def build_attachment_from_spec(spec: Any) -> dict[str, Any]:
    """Render a :class:`CardSpec` and wrap it in a Bot Framework attachment.

    Args:
        spec: The :class:`~parrot.outputs.cards.spec.CardSpec` to render.

    Returns:
        A Bot Framework attachment envelope wrapping the rendered card.
    """
    from .renderer import render
    return build_attachment(render(spec))
