"""Folium map renderer (Module 5, satellite).

Deterministic replacement for the legacy ``formats/map.py`` ``FoliumRenderer`` (which
executed LLM-generated Python via the arbitrary-code sink). This renderer builds the map
**only through folium's Python API from the baked Map component's data** — no code
strings, no ``exec``, nothing LLM-authored.

``folium`` is imported lazily with an actionable error. Note: folium's own generated
HTML references tile-server URLs at *view* time (a runtime map-tile concern, not a
render dependency); the PDF path uses SSR alternatives (TASK-1732).

FEAT-473 (Module 5, G7): when the baked ``Map`` component's ``layers`` carry a
per-layer ``data`` binding (the structured-output adapter's
``/layers/<i>/features`` shape — resolved to an actual feature list by
``bake_envelope``), this renderer builds one ``folium.FeatureGroup`` per
layer, honouring that layer's ``markerColor``/``tooltipTemplate``/
``labelField``/``geodesic``. Older envelopes with a single top-level ``data``
binding (no per-layer ``data``) render exactly as before via the legacy
single-layer path — this is a pure additive extension, not a rewrite.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record
from parrot.outputs.a2ui_renderers._map_vendor import VENDORED_ASSET_PATHS

logger = logging.getLogger(__name__)

_SURFACE_NAME = "folium_map"
_MAP_EXTRA = "ai-parrot-visualizations[a2ui,map]"

#: Default marker-count threshold above which a layer's markers are wrapped
#: in a `folium.plugins.MarkerCluster` (FEAT-522, spec §8 resolved: 500,
#: per-layer overridable via `cluster_threshold_by_layer`).
DEFAULT_CLUSTER_THRESHOLD: int = 500


def _import_folium():
    """Import ``folium`` (indirection point so tests can force failure).

    Also imports ``folium.plugins`` (ships with ``folium>=0.14``, no new
    pyproject dependency — spec §6 "Verified Imports") so
    ``folium.plugins.MarkerCluster`` is reachable off the returned module
    without a separate lazy-import call site.
    """
    import folium
    import folium.plugins  # noqa: F401 — binds `folium.plugins` as an attribute

    return folium


def _load_folium():
    """Lazily load ``folium`` with an actionable error naming the extras."""
    try:
        return _import_folium()
    except ImportError as exc:
        raise ImportError(
            "The A2UI folium_map renderer requires 'folium'. " f"Install it with: pip install {_MAP_EXTRA}"
        ) from exc


def _data_uri(path: Path, mime: str) -> str:
    """Build a base64-encoded ``data:`` URI from a vendored asset file.

    Args:
        path: The vendored file's local path (from
            ``_map_vendor.VENDORED_ASSET_PATHS``).
        mime: The MIME type to embed (``"text/javascript"`` for ``.js``,
            ``"text/css"`` for ``.css``).

    Returns:
        A ``data:{mime};base64,{...}`` URI string.
    """
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_offline_url_map() -> dict[str, str]:
    """Build the ``{cdn_url: data_uri}`` swap table (FEAT-522, TASK-2787).

    Introspects ``folium.Map().default_js``/``default_css`` and
    ``folium.plugins.MarkerCluster().default_js``/``default_css`` LIVE
    (never a hardcoded URL list) so a future ``folium`` bump that keeps the
    same resource ``name`` but changes its pinned CDN URL is still matched
    correctly — the swap is keyed by the CURRENT url, looked up via each
    resource's stable ``name`` against
    ``_map_vendor.VENDORED_ASSET_PATHS`` (spec §7 Known Risks: "folium
    version drift").

    Read ONCE at import time (module-level ``_OFFLINE_URL_MAP`` below) —
    mirrors this codebase's established ``_CHART_JS_SOURCE``/``_BASE_CSS``
    "read once, never per-render" convention; base64-encoding ~13 small-to-
    medium vendored files is a one-time, bounded cost.

    Returns:
        A mapping from each verified folium/MarkerCluster default resource
        URL to its locally-vendored ``data:`` URI equivalent.
    """
    import folium
    import folium.plugins as fp

    pairs: dict[str, str] = {}
    m = folium.Map()
    mc = fp.MarkerCluster()
    for name, url in [*m.default_js, *mc.default_js]:
        pairs[url] = _data_uri(VENDORED_ASSET_PATHS[name], "text/javascript")
    for name, url in [*m.default_css, *mc.default_css]:
        pairs[url] = _data_uri(VENDORED_ASSET_PATHS[name], "text/css")
    return pairs


#: Read ONCE at import time (not per-render) — see `_build_offline_url_map`.
_OFFLINE_URL_MAP: dict[str, str] = _build_offline_url_map()


def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Build one folium HTML document from baked Map properties.

    Synchronous by design (FEAT-522, spec §2 "Why a new shared builder"):
    ``InteractiveHTMLRenderer``'s internal render chain
    (``_render_top``/``_render_descriptor``) is fully synchronous, so this
    function — shared by both :class:`FoliumMapRenderer` (a thin async
    wrapper around it) and ``InteractiveHTMLRenderer._render_map`` — must
    not be ``async`` and must not ``await`` anything.

    Args:
        props: The single baked ``Map`` component's own top-level props
            dict (what :meth:`FoliumMapRenderer.render` calls ``map_comp``).
        cluster_threshold: Default marker-count threshold above which a
            layer's markers are wrapped in ``folium.plugins.MarkerCluster``.
        cluster_threshold_by_layer: Optional per-layer threshold override,
            keyed by layer name — renderer-internal only, never LLM-settable
            (spec §2 Data Models / Non-Goals).

    Returns:
        ``(document_bytes, degradations)`` — ``degradations`` is always
        ``[]`` today (reserved for a future layer-level-skip case; the
        caller's own sibling-component degradations are built separately,
        since they need the full baked component list, not just ``props``).
    """
    folium = _load_folium()
    viewport = props.get("viewport") or {}
    center = viewport.get("center") or [0.0, 0.0]
    # Bug fix (post-review): `viewport.get("zoom", 2)` only falls back
    # to 2 when the "zoom" KEY is absent — a real STRUCTURED_MAP
    # viewport (`_compute_viewport`, which only derives bbox/center,
    # never zoom) dumps an explicit `"zoom": null` key, so `.get()`
    # returned `None` and `folium.Map(zoom_start=None)` produced a map
    # with a center but no usable zoom level.
    zoom = viewport.get("zoom")
    if zoom is None:
        zoom = 2

    fmap = folium.Map(location=list(center), zoom_start=zoom)

    layers = props.get("layers")
    has_layer_data = isinstance(layers, list) and any(
        isinstance(layer, dict) and "data" in layer for layer in layers
    )
    if has_layer_data:
        # FEAT-473: multi-layer path — each layer's baked `data` is its
        # own resolved feature list (bound at /layers/<i>/features).
        for i, layer in enumerate(layers):
            if not isinstance(layer, dict):
                continue
            layer_name = str(layer.get("layer") or f"layer-{i}")
            group = folium.FeatureGroup(name=layer_name)
            marker_color = layer.get("markerColor")
            tooltip_template = layer.get("tooltipTemplate")
            label_field = layer.get("labelField")
            geodesic = bool(layer.get("geodesic"))
            features = FoliumMapRenderer._iter_layer_features(layer.get("data"))

            effective_threshold = (
                cluster_threshold_by_layer.get(layer_name, cluster_threshold)
                if cluster_threshold_by_layer
                else cluster_threshold
            )
            # FEAT-522: above threshold, markers wrap in a MarkerCluster
            # (added to the layer's FeatureGroup); below threshold,
            # unchanged individual-marker behavior straight on the group.
            if len(features) > effective_threshold:
                target = folium.plugins.MarkerCluster()
                target.add_to(group)
            else:
                target = group

            for feature in features:
                FoliumMapRenderer._add_feature(
                    folium,
                    target,
                    feature,
                    marker_color=marker_color,
                    tooltip_template=tooltip_template,
                    label_field=label_field,
                    geodesic=geodesic,
                )
            group.add_to(fmap)
    else:
        # Legacy single-layer path (pre-FEAT-473 envelopes): a single
        # top-level `data` binding of flat {"lat", "lon", "popup"} points.
        for feature in FoliumMapRenderer._iter_points(props.get("data")):
            lat = feature.get("lat")
            lon = feature.get("lon")
            if lat is None or lon is None:
                continue
            folium.Marker(
                location=[lat, lon],
                popup=str(feature.get("popup", "")) or None,
            ).add_to(fmap)

    document = fmap.get_root().render()
    # FEAT-522 (TASK-2787): swap every one of folium's default CDN URLs for
    # an inlined `data:` URI built from a locally vendored copy of that
    # exact file — a plain string `.replace()` pass over the ALREADY-
    # rendered HTML, never `add_js_link()`/`add_css_link()` (spec §2: those
    # mutate a shared, class-level mutable list on `JSCSSMixin` that every
    # `folium.Map`/`MarkerCluster` instance in the process shares). A
    # `.replace()` on a URL that isn't present in this particular render
    # (e.g. MarkerCluster's resources when clustering wasn't triggered) is
    # a harmless no-op, so all pairs are applied unconditionally.
    for cdn_url, data_uri in _OFFLINE_URL_MAP.items():
        document = document.replace(cdn_url, data_uri)
    return document.encode("utf-8"), []


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="text/html",
        supported_components={"Map"},
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
            A ``RenderedArtifact`` with ``mime_type="text/html"``; any sibling
            component this renderer does not render is recorded in
            ``metadata["degraded"]`` (AC-G3 — degradation must be visible,
            never silent).

        Raises:
            ValueError: If the envelope contains no ``Map`` component.
            ImportError: If ``folium`` is unavailable (names the extra).
        """
        baked = bake_envelope(envelope)
        map_comp = next((c for c in baked if c["component"] == "Map"), None)
        if map_comp is None:
            raise ValueError("folium_map renderer requires a 'Map' component in the envelope.")

        degradations = [
            degradation_record(
                BasicNode(id=item["id"], component=item["component"]),
                f"{_SURFACE_NAME} renderer only renders a single Map component per surface",
            )
            for item in baked
            if item is not map_comp
        ]

        document, _ = build_map_document(map_comp, cluster_threshold=DEFAULT_CLUSTER_THRESHOLD)
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="text/html",
            content=document,
            filename=f"{envelope.surface_id}.html",
            title=map_comp.get("title") or envelope.surface_id,
            surface=_SURFACE_NAME,
            metadata={"degraded": degradations} if degradations else {},
        )

    @staticmethod
    def _iter_points(data: Any) -> list[dict[str, Any]]:
        """Return the point features from baked Map data (list of point dicts)."""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _iter_layer_features(data: Any) -> list[dict[str, Any]]:
        """Return a layer's baked feature-property dicts (list of flat dicts).

        Mirrors :meth:`_iter_points` — the FEAT-473 adapter's per-layer rows
        are flat property dicts, each optionally carrying a ``_geometry``
        GeoJSON geometry (:meth:`_extract_lat_lon`/:meth:`_extract_line_coords`).

        Args:
            data: A layer's baked ``data`` value (resolved feature list).

        Returns:
            The list of feature dicts, or ``[]`` if ``data`` isn't a list.
        """
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_lat_lon(feature: dict[str, Any]) -> tuple[float, float] | None:
        """Extract a ``(lat, lon)`` pair from a baked feature dict.

        Prefers the FEAT-473 ``_geometry`` GeoJSON ``Point`` shape
        (``coordinates: [lon, lat]``, GeoJSON order); falls back to legacy
        flat ``lat``/``lon`` keys for older single-layer envelopes.

        Args:
            feature: A baked feature-property dict.

        Returns:
            ``(lat, lon)``, or ``None`` if neither shape is present.
        """
        geometry = feature.get("_geometry")
        if isinstance(geometry, dict) and geometry.get("type") == "Point":
            coords = geometry.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
                return (lat, lon)
        lat, lon = feature.get("lat"), feature.get("lon")
        if lat is not None and lon is not None:
            return (lat, lon)
        return None

    @staticmethod
    def _extract_line_coords(feature: dict[str, Any]) -> list[tuple[float, float]] | None:
        """Extract a ``[(lat, lon), ...]`` path from a baked feature's ``_geometry``.

        Only a GeoJSON ``LineString`` geometry yields a path (straight-line
        polyline through the given points — this codebase does not vendor a
        true great-circle/geodesic curve plugin; ``geodesic=True`` layers
        still render as a polyline, per spec §7).

        Args:
            feature: A baked feature-property dict.

        Returns:
            The ``(lat, lon)`` point list, or ``None`` if not a LineString.
        """
        geometry = feature.get("_geometry")
        if isinstance(geometry, dict) and geometry.get("type") == "LineString":
            coords = geometry.get("coordinates") or []
            return [(c[1], c[0]) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
        return None

    @staticmethod
    def _add_feature(
        folium_mod: Any,
        group: Any,
        feature: dict[str, Any],
        *,
        marker_color: str | None,
        tooltip_template: str | None,
        label_field: str | None,
        geodesic: bool,
    ) -> None:
        """Add one baked feature to a folium ``FeatureGroup`` (marker or polyline).

        Args:
            folium_mod: The imported ``folium`` module (passed through to
                avoid a second lazy import per feature).
            group: The layer's ``folium.FeatureGroup``.
            feature: A baked feature-property dict.
            marker_color: The layer's ``markerColor`` (CSS name or hex), if any.
            tooltip_template: The layer's ``tooltipTemplate``
                (``str.format_map`` template over feature properties), if any.
            label_field: The layer's ``labelField`` (feature key for the
                marker label), if any.
            geodesic: Whether this layer's path features render as polylines.
        """
        if geodesic:
            line_coords = FoliumMapRenderer._extract_line_coords(feature)
            if line_coords:
                folium_mod.PolyLine(locations=line_coords, color=marker_color or "blue").add_to(group)
                return

        latlon = FoliumMapRenderer._extract_lat_lon(feature)
        if latlon is None:
            return
        lat, lon = latlon

        label_value = feature.get(label_field) if label_field else None
        tooltip_text: str | None = None
        if tooltip_template:
            try:
                tooltip_text = tooltip_template.format_map(feature)
            except Exception as exc:  # noqa: BLE001
                logger.debug("folium_map: tooltipTemplate %r failed: %s", tooltip_template, exc)
        popup_text = tooltip_text or (str(label_value) if label_value is not None else None)

        if marker_color:
            try:
                folium_mod.CircleMarker(
                    location=[lat, lon],
                    radius=6,
                    color=marker_color,
                    fill=True,
                    fill_color=marker_color,
                    fill_opacity=0.8,
                    popup=popup_text,
                    tooltip=popup_text,
                ).add_to(group)
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "folium_map: markerColor %r rejected by folium; falling back to default marker: %s",
                    marker_color,
                    exc,
                )

        folium_mod.Marker(location=[lat, lon], popup=popup_text, tooltip=popup_text).add_to(group)
