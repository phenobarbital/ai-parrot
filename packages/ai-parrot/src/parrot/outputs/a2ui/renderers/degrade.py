"""Renderer degradation helper (Module 7, core side, FEAT-470 TASK-2543).

A static renderer must NEVER raise for a component it merely doesn't
natively support (spec §7 Known Risks: "degradación registrada, nunca
excepción silenciosa"). :func:`degrade` builds the visible placeholder; the
CALLING renderer is responsible for collecting one record per degradation
into a list it dumps into ``RenderedArtifact.metadata["degraded"]`` (this
module holds no state of its own — recording is the renderer's job, since
only the renderer knows the full set of degradations for one render pass).

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog.base import BasicNode

__all__ = ["degrade"]


def degrade(node: BasicNode, reason: str) -> BasicNode:
    """Replace an unsupported ``node`` with a visible ``Text`` placeholder.

    Args:
        node: The original (unsupported, on THIS renderer) ``BasicNode``.
            Its ``id`` is preserved so the placeholder can still be located
            by anything that referenced the original node's id.
        reason: Human-readable reason for the degradation (e.g. the renderer
            name and the missing capability).

    Returns:
        A ``Text`` ``BasicNode`` (``metadata.extensions.parrot_role="notice"``)
        standing in for ``node``.
    """
    return BasicNode(
        id=node.id,
        component="Text",
        text=f"[{node.component} not supported here: {reason}]",
        metadata={"extensions": {"parrot_role": "notice"}},
    )


def degradation_record(node: BasicNode, reason: str) -> dict[str, Any]:
    """Build the structured record a renderer appends for one degradation.

    Args:
        node: The original (unsupported) ``BasicNode``.
        reason: Human-readable reason for the degradation.

    Returns:
        A ``{"id", "component", "reason"}`` dict — the shape every renderer
        collects into ``RenderedArtifact.metadata["degraded"]``.
    """
    return {"id": node.id, "component": node.component, "reason": reason}
