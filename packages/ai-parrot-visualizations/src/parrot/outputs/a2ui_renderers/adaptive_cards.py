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
from parrot.outputs.cards import (
    CardSpec,
    Column,
    ColumnSet,
    Container,
    Image,
    RawElementsSection,
    TextBlock,
    render as render_card,
)
from parrot.outputs.cards.elements import ACElement

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
    """Basic-tree -> Adaptive Card JSON renderer (display subset, no actions)."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        deep_links: Optional[list[DeepLink]] = None,
    ) -> RenderedArtifact:
        """Render an envelope to a baked Adaptive Card ``RenderedArtifact``."""
        baked_components = bake_envelope(envelope)
        elements: list[ACElement] = []
        for bc in baked_components:
            elements.append(self._element_for_component(bc))

        for link in deep_links or []:
            # Deep links are rendered as DISPLAY text (never Action.OpenUrl) in v1.
            elements.append(
                TextBlock(text=f"{link.action_label}: {link.url}")
            )

        spec = CardSpec(sections=[RawElementsSection(elements=elements)])
        card = render_card(spec)
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

    def _element_for_component(self, comp: dict[str, Any]) -> ACElement:
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

    def _map_node(self, node: BasicNode) -> ACElement:
        """Map a Basic Catalog node to an Adaptive Card display element."""
        component = node.component
        props = node.properties or {}

        if component == "Text":
            role = props.get("role", "")
            text = props.get("text")
            kwargs: dict[str, Any] = {}
            if role in _TITLE_ROLES:
                kwargs["size"] = "Large"
                kwargs["weight"] = "Bolder"
            elif role in _HEADING_ROLES:
                kwargs["weight"] = "Bolder"
            return TextBlock(
                text="" if text is None else str(text),
                **kwargs,
            )

        if component == "Image":
            src = str(props.get("src", ""))
            return Image(url=src)

        if component == "Row":
            return ColumnSet(
                columns=[
                    Column(items=[self._map_node(child)])
                    for child in node.children
                ],
            )

        if component in ("Column", "Card"):
            style = "Emphasis" if component == "Card" else None
            return Container(
                items=[self._map_node(child) for child in node.children],
                style=style,
            )

        # Unmappable Basic element -> deterministic fallback (never a silent drop).
        logger.warning(
            "A2UI adaptive_cards: unmapped Basic element %r; using fallback",
            component,
        )
        return TextBlock(text=component)
