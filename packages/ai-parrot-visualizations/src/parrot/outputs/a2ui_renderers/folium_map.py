"""Folium map renderer (Module 5, satellite).

Deterministic replacement for the legacy ``formats/map.py`` ``FoliumRenderer`` (which
executed LLM-generated Python via the arbitrary-code sink). This renderer builds the map
**only through folium's Python API from the baked Map component's data** — no code
strings, no ``exec``, nothing LLM-authored.

``folium`` is imported lazily with an actionable error. Note: folium's own generated
HTML references tile-server URLs at *view* time (a runtime map-tile concern, not a
render dependency); the PDF path uses SSR alternatives (TASK-1732).
"""

from __future__ import annotations

import logging
from typing import Any

import parrot.outputs.a2ui.catalog.components  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)

logger = logging.getLogger(__name__)

_SURFACE_NAME = "folium_map"
_MAP_EXTRA = "ai-parrot-visualizations[a2ui,map]"


def _import_folium():
    """Import ``folium`` (indirection point so tests can force failure)."""
    import folium  # noqa: PLC0415 — lazy by design

    return folium


def _load_folium():
    """Lazily load ``folium`` with an actionable error naming the extras."""
    try:
        return _import_folium()
    except ImportError as exc:
        raise ImportError(
            "The A2UI folium_map renderer requires 'folium'. "
            f"Install it with: pip install {_MAP_EXTRA}"
        ) from exc


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="text/html",
    ),
)
class FoliumMapRenderer(AbstractA2UIRenderer):
    """Deterministic Map-component → folium HTML renderer."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
    ) -> RenderedArtifact:
        """Render the first Map component to a folium HTML ``RenderedArtifact``.

        Args:
            envelope: The validated envelope containing a ``Map`` component.
            bake: Bindings are always resolved (static output).

        Returns:
            A ``RenderedArtifact`` with ``mime_type="text/html"``.

        Raises:
            ValueError: If the envelope contains no ``Map`` component.
            ImportError: If ``folium`` is unavailable (names the extra).
        """
        folium = _load_folium()
        baked = bake_envelope(envelope)
        map_comp = next((c for c in baked if c["component"] == "Map"), None)
        if map_comp is None:
            raise ValueError("folium_map renderer requires a 'Map' component in the envelope.")

        props = map_comp["properties"]
        viewport = props.get("viewport") or {}
        center = viewport.get("center") or [0.0, 0.0]
        zoom = viewport.get("zoom", 2)

        fmap = folium.Map(location=list(center), zoom_start=zoom)
        for feature in self._iter_points(props.get("data")):
            lat = feature.get("lat")
            lon = feature.get("lon")
            if lat is None or lon is None:
                continue
            folium.Marker(
                location=[lat, lon],
                popup=str(feature.get("popup", "")) or None,
            ).add_to(fmap)

        document = fmap.get_root().render()
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="text/html",
            content=document.encode("utf-8"),
            filename=f"{envelope.surface_id}.html",
            title=props.get("title") or envelope.surface_id,
            surface=_SURFACE_NAME,
        )

    @staticmethod
    def _iter_points(data: Any) -> list[dict[str, Any]]:
        """Return the point features from baked Map data (list of point dicts)."""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
