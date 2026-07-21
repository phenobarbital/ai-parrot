"""Adaptive Cards renderer (Module 5, satellite).

Transcodes A2UI envelopes into Adaptive Card JSON for Teams-style surfaces. It is the
"AC fallback transcode" lane: it consumes LOWERED Basic Catalog trees only — mandatory
lowering (G4) guarantees every Parrot component has one, so this renderer needs no
per-component knowledge of the custom catalog.

v1 is a **display subset**: display elements only (TextBlock / Container / ColumnSet /
Image). NO ``Action.*`` elements are ever emitted — action dispatch is FEAT-B, and
static-surface actions degrade via deep links rendered as display text (G6).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import parrot.outputs.a2ui.catalog.components  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import DeepLink, RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)

logger = logging.getLogger(__name__)

_SURFACE_NAME = "adaptive_cards"
_AC_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
_AC_VERSION = "1.5"  # pinned to match msteams/hitl_cards.py
_AC_MIME = "application/vnd.microsoft.card.adaptive"

# Text roles that get emphasized styling in the card.
_TITLE_ROLES = {"title"}
_HEADING_ROLES = {"heading", "subtitle", "label"}


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output=_AC_MIME,
    ),
)
class AdaptiveCardsRenderer(AbstractA2UIRenderer):
    """Basic-tree → Adaptive Card JSON renderer (display subset, no actions)."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        deep_links: Optional[list[DeepLink]] = None,
    ) -> RenderedArtifact:
        """Render an envelope to a baked Adaptive Card ``RenderedArtifact``."""
        baked_components = bake_envelope(envelope)
        body: list[dict[str, Any]] = []
        for bc in baked_components:
            body.append(self._element_for_component(bc))

        for link in deep_links or []:
            # Deep links are rendered as DISPLAY text (never Action.OpenUrl) in v1.
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"{link.action_label}: {link.url}",
                    "wrap": True,
                }
            )

        card = {
            "$schema": _AC_SCHEMA,
            "type": "AdaptiveCard",
            "version": _AC_VERSION,
            "body": body,
        }
        content = json.dumps(card, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type=_AC_MIME,
            content=content,
            filename=f"{envelope.surface_id}.card.json",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
            deep_links=list(deep_links or []),
        )

    # -- internal mapping ---------------------------------------------------

    def _element_for_component(self, comp: dict[str, Any]) -> dict[str, Any]:
        """Lower a baked component to a Basic tree and map it to an AC element."""
        name = comp["component"]
        try:
            entry = get_component(name)
        except KeyError:
            node = BasicNode(**comp)
            return self._map_node(node)
        lowered = entry.component_cls().lower(
            Component(
                id=comp.get("id", ""),
                component=name,
                properties=comp.get("properties", {}) or {},
                children=comp.get("children", []) or [],
            ),
            {},
        )
        return self._map_node(lowered)

    def _map_node(self, node: BasicNode) -> dict[str, Any]:
        """Map a Basic Catalog node to an Adaptive Card display element."""
        component = node.component
        props = node.properties or {}

        if component == "Text":
            role = props.get("role", "")
            text = props.get("text")
            element: dict[str, Any] = {
                "type": "TextBlock",
                "text": "" if text is None else str(text),
                "wrap": True,
            }
            if role in _TITLE_ROLES:
                element["size"] = "Large"
                element["weight"] = "Bolder"
            elif role in _HEADING_ROLES:
                element["weight"] = "Bolder"
            return element

        if component == "Image":
            src = str(props.get("src", ""))
            return {"type": "Image", "url": src}

        if component == "Row":
            return {
                "type": "ColumnSet",
                "columns": [
                    {"type": "Column", "items": [self._map_node(child)]}
                    for child in node.children
                ],
            }

        if component in ("Column", "Card"):
            container: dict[str, Any] = {
                "type": "Container",
                "items": [self._map_node(child) for child in node.children],
            }
            if component == "Card":
                container["style"] = "emphasis"
            return container

        # Unmappable Basic element → deterministic fallback (never a silent drop).
        logger.warning("A2UI adaptive_cards: unmapped Basic element %r; using fallback", component)
        return {"type": "TextBlock", "text": component, "wrap": True}
