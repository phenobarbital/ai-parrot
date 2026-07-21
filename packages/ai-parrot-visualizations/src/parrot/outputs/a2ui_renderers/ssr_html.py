"""SSR-HTML renderer (Module 5, satellite).

Turns a validated ``CreateSurface`` envelope into a single self-contained, baked HTML
document. It is the backbone of static delivery (G5): the PDF renderer rasterizes its
output and email attaches it directly.

Security invariants (spec G1):

* Subclasses the core :class:`AbstractA2UIRenderer` — never the legacy ``BaseRenderer``
  (which holds the arbitrary-code sink FEAT-273 exists to kill).
* Every data value is HTML-escaped — envelope data is data, never markup/JS.
* Output is self-contained — all CSS inline, no external CDN/script/style/font refs.
"""

from __future__ import annotations

import html
import logging
from typing import Any, Optional

# Ensure the core v1 catalog components are registered so lowering can resolve them.
import parrot.outputs.a2ui.catalog.components  # noqa: F401
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

_SURFACE_NAME = "ssr_html"

_STYLE = (
    "body{font-family:sans-serif;margin:1rem;color:#1a1a1a}"
    ".a2ui-card{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:.5rem 0}"
    ".a2ui-row{display:flex;gap:1rem}.a2ui-col{display:flex;flex-direction:column}"
    ".a2ui-text{margin:.25rem 0}.a2ui-title{font-size:1.4rem;font-weight:700}"
    ".a2ui-heading{font-size:1.15rem;font-weight:600}.a2ui-notice{color:#a00}"
    ".a2ui-deeplink{display:inline-block;margin:.25rem 0}"
)

_CONTAINER_COMPONENTS = {"Column": "a2ui-col", "Row": "a2ui-row", "Card": "a2ui-card"}


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="text/html",
    ),
)
class SSRHTMLRenderer(AbstractA2UIRenderer):
    """Static, self-contained HTML renderer for A2UI envelopes."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        deep_links: Optional[list[DeepLink]] = None,
    ) -> RenderedArtifact:
        """Render an envelope to a baked, self-contained HTML ``RenderedArtifact``.

        Args:
            envelope: The validated ``createSurface`` envelope.
            bake: Always effectively ``True`` for this static renderer (bindings are
                resolved regardless); kept for ABC compatibility.
            deep_links: Deep links to render as anchors for degraded actions.

        Returns:
            A ``RenderedArtifact`` with ``mime_type="text/html"``.
        """
        # Static renderer: always bake so the document has zero live bindings.
        baked_components = bake_envelope(envelope)
        body_parts: list[str] = [self._render_component(bc) for bc in baked_components]

        for link in deep_links or []:
            body_parts.append(
                f'<a class="a2ui-deeplink" href="{html.escape(link.url, quote=True)}">'
                f"{html.escape(link.action_label)}</a>"
            )

        document = (
            "<!DOCTYPE html>"
            '<html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(envelope.surface_id)}</title>"
            f"<style>{_STYLE}</style></head>"
            f'<body>{"".join(body_parts)}</body></html>'
        )
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="text/html",
            content=document.encode("utf-8"),
            filename=f"{envelope.surface_id}.html",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
            deep_links=list(deep_links or []),
        )

    # -- internal rendering -------------------------------------------------

    def _render_component(self, comp: dict[str, Any]) -> str:
        """Lower a baked component to a Basic tree and render it to HTML."""
        name = comp["component"]
        try:
            entry = get_component(name)
        except KeyError:
            # Already a Basic Catalog primitive — render directly.
            node = BasicNode(**comp)
            return self._render_basic(node)
        lowered = entry.component_cls().lower(
            Component(
                id=comp.get("id", ""),
                component=name,
                properties=comp.get("properties", {}) or {},
                children=comp.get("children", []) or [],
            ),
            {},
        )
        return self._render_basic(lowered)

    def _render_basic(self, node: BasicNode) -> str:
        """Recursively render a lowered Basic Catalog node to escaped HTML."""
        component = node.component
        props = node.properties or {}

        if component == "Text":
            role = props.get("role", "")
            text = props.get("text")
            cls = f"a2ui-text a2ui-{html.escape(str(role))}" if role else "a2ui-text"
            return f'<p class="{cls}">{html.escape("" if text is None else str(text))}</p>'

        if component == "Image":
            src = str(props.get("src", ""))
            if src.startswith("data:"):
                return f'<img src="{html.escape(src, quote=True)}" alt="">'
            # Self-contained: never emit external src; keep URL in a data attribute.
            return f'<div class="a2ui-image" data-image-url="{html.escape(src, quote=True)}">[image]</div>'

        children_html = "".join(self._render_basic(child) for child in node.children)
        css_class = _CONTAINER_COMPONENTS.get(component, f"a2ui-{html.escape(component.lower())}")
        return f'<div class="{css_class}">{children_html}</div>'
