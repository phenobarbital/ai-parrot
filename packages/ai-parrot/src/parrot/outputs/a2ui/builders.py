"""Typed deterministic A2UI v1.0 envelope builders (Module 5, decision D1a).

Tools emit A2UI envelopes **deterministically from their own data — zero LLM tokens,
zero HTML string assembly** (spec G2/D1a). These builders construct catalog-valid
``CreateSurface`` envelopes from structured Python data and validate them against the
catalog allowlist (display-only: ``requires_actions`` components are rejected here).
Every envelope carries a component with ``id="root"`` (spec G6) and top-level props
(no ``properties`` nesting, no ``$bind`` — v1.0 wire throughout).

Pure functions: same input → byte-identical envelope. No clocks, no uuids inside the
component tree (artifact ids live outside the payload), no network, no LLM.

One-way import rule (G8): this module imports only the a2ui core; never agents,
DatasetManager, LLM clients, or the satellite renderers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Ensure the v1 parrot catalog is registered so allowlist validation resolves components.
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401

# Ensure viz-core (and its Graph registration) is registered too — same
# reasoning as the parrot import above (FEAT-529).
import parrot.outputs.a2ui.catalog.viz_core  # noqa: F401
from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    ProducerOrigin,
    validate_envelope,
)
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.graph import (
    Direction,
    GraphEdge,
    GraphGroup,
    GraphKind,
    GraphLayout,
    GraphNode,
    GraphSelection,
    GraphSpec,
    VizSize,
    compute_positions,
)
from parrot.outputs.a2ui.models import Action, Component, ComponentMetadata, CreateSurface

__all__ = [
    "build_card",
    "build_chart",
    "build_datatable",
    "build_graph",
    "build_html_document",
    "build_infographic",
    "build_kpicard",
    "build_map",
    "build_surface",
]

#: Every builder emits its single top-level component under this id (spec G6:
#: builders guarantee a component with id="root").
_ROOT_COMPONENT_ID = "root"


def _binding(pointer: str | None) -> dict[str, str] | None:
    return {"path": pointer} if pointer else None


def build_surface(
    component: str,
    properties: dict[str, Any],
    *,
    surface_id: str,
    component_id: str = _ROOT_COMPONENT_ID,
    data_model: dict[str, Any] | None = None,
    origin: ProducerOrigin = ProducerOrigin.LLM,
    metadata: ComponentMetadata | None = None,
) -> CreateSurface:
    """Build and validate a single-component display ``CreateSurface``.

    Display-only by default (``origin=LLM``): the envelope is validated with
    LLM-origin semantics so any ``requires_actions``/``action``-bearing
    component, any unknown component, and (FEAT-473 G8) any inlined ``data``/
    ``datasets`` row list on a Chart/DataTable/Map is rejected. Pass
    ``origin=ProducerOrigin.TOOL`` for deterministic tool-built surfaces
    (e.g. the FEAT-473 structured-output adapter), which MAY inline rows
    directly. ``component_id`` defaults to ``"root"`` so the envelope
    satisfies the v1.0 wire's root requirement (spec G6) out of the box.

    Args:
        metadata: Optional component-level metadata (e.g. carrying
            ``extensions.parrot_optional``) to attach to the root component
            (FEAT-499). Wins over any ``"metadata"`` key inside
            ``properties``. Omitted entirely (no key emitted) when ``None``.

    Raises:
        CatalogValidationError: If the component is unknown, action-bearing
            (LLM origin), or inlines rows on a structured component (LLM origin).
    """
    component_kwargs: dict[str, Any] = {"id": component_id, "component": component}
    remaining_properties = properties
    if metadata is not None:
        remaining_properties = dict(properties)
        remaining_properties.pop("metadata", None)
        component_kwargs["metadata"] = metadata
    envelope = CreateSurface(
        surfaceId=surface_id,
        catalogId=DEFAULT_CATALOG_ID,
        components=[Component(**component_kwargs, **remaining_properties)],
        dataModel=data_model or {},
    )
    validate_envelope(envelope, origin=origin)
    return envelope


def build_chart(
    *,
    chart_type: str,
    x: str,
    y: Sequence[str],
    title: str | None = None,
    data_binding: str | None = None,
    show_legend: bool = True,
    surface_id: str = "chart",
    data_model: dict[str, Any] | None = None,
) -> CreateSurface:
    """Build a display envelope carrying a single Chart component."""
    props: dict[str, Any] = {"type": chart_type, "x": x, "y": list(y), "showLegend": show_legend}
    if title is not None:
        props["title"] = title
    binding = _binding(data_binding)
    if binding is not None:
        props["data"] = binding
    return build_surface("Chart", props, surface_id=surface_id, data_model=data_model)


def build_kpicard(
    *,
    label: str,
    value: Any,
    unit: str | None = None,
    delta: Any = None,
    trend: str | None = None,
    surface_id: str = "kpi",
) -> CreateSurface:
    """Build a display envelope carrying a single KPICard component."""
    props: dict[str, Any] = {"label": label, "value": value}
    if unit is not None:
        props["unit"] = unit
    if delta is not None:
        props["delta"] = delta
    if trend is not None:
        props["trend"] = trend
    return build_surface("KPICard", props, surface_id=surface_id)


def build_card(
    *,
    title: str,
    subtitle: str | None = None,
    body: str | None = None,
    image: str | None = None,
    footer: str | None = None,
    surface_id: str = "card",
) -> CreateSurface:
    """Build a display envelope carrying a single InfoCard component.

    Public API name is kept as ``build_card`` (no breaking change to callers);
    the emitted component type is ``InfoCard`` (spec G9 — ``Card`` is now the
    official Basic Catalog primitive).
    """
    props: dict[str, Any] = {"title": title}
    for key, val in (("subtitle", subtitle), ("body", body), ("image", image), ("footer", footer)):
        if val is not None:
            props[key] = val
    return build_surface("InfoCard", props, surface_id=surface_id)


def build_datatable(
    *,
    columns: Sequence[dict[str, Any]],
    data_binding: str | None = None,
    title: str | None = None,
    total_rows: int | None = None,
    truncated: bool = False,
    surface_id: str = "table",
    data_model: dict[str, Any] | None = None,
) -> CreateSurface:
    """Build a display envelope carrying a single DataTable component."""
    props: dict[str, Any] = {"columns": [dict(c) for c in columns]}
    if title is not None:
        props["title"] = title
    if total_rows is not None:
        props["totalRows"] = total_rows
    if truncated:
        props["truncated"] = True
    binding = _binding(data_binding)
    if binding is not None:
        props["data"] = binding
    return build_surface("DataTable", props, surface_id=surface_id, data_model=data_model)


def build_map(
    *,
    layers: Sequence[dict[str, Any]],
    viewport: dict[str, Any] | None = None,
    base_layer: str | None = None,
    title: str | None = None,
    description: str | None = None,
    query: dict[str, Any] | None = None,
    data_model: dict[str, Any] | None = None,
    surface_id: str = "map",
) -> CreateSurface:
    """Build a display envelope carrying a single Map component.

    Mirrors :func:`build_chart`/:func:`build_datatable`. ``layers`` is a
    sequence of ``MapLayer``-shaped dicts (camelCase props: ``layer``,
    ``columns``, ``tooltipTemplate``, ``labelField``, ``dataShape``,
    ``totalCount``, ``capped``, ``geodesic``, ``markerColor``).
    """
    props: dict[str, Any] = {"layers": [dict(layer) for layer in layers]}
    if viewport is not None:
        props["viewport"] = dict(viewport)
    if base_layer is not None:
        props["baseLayer"] = base_layer
    if title is not None:
        props["title"] = title
    if description is not None:
        props["description"] = description
    if query is not None:
        props["query"] = dict(query)
    return build_surface("Map", props, surface_id=surface_id, data_model=data_model)


def build_infographic(
    *,
    title: str,
    sections: Sequence[dict[str, Any]],
    subtitle: str | None = None,
    theme: str | None = None,
    surface_id: str = "infographic",
    data_model: dict[str, Any] | None = None,
    metadata: ComponentMetadata | None = None,
) -> CreateSurface:
    """Build a display envelope carrying a single Infographic composite component.

    ``sections`` is a list of ``{"heading": ..., "text"?: ..., "components"?: [...]}``
    dicts (nested ``components`` are ``{"component": name, "properties": {...}}``).

    Args:
        metadata: Optional component-level metadata (e.g. carrying
            ``extensions.parrot_optional``) forwarded to the underlying
            ``build_surface`` call and attached to the root component
            (FEAT-499).
    """
    props: dict[str, Any] = {"title": title, "sections": [dict(s) for s in sections]}
    if subtitle is not None:
        props["subtitle"] = subtitle
    if theme is not None:
        props["theme"] = theme
    return build_surface("Infographic", props, surface_id=surface_id, data_model=data_model, metadata=metadata)


def build_html_document(
    *,
    title: str,
    html: str | None = None,
    src_url: str | None = None,
    theme: str | None = None,
    surface_id: str = "html-document",
    metadata: ComponentMetadata | None = None,
) -> CreateSurface:
    """Build a tool-only display envelope carrying a single HtmlDocument component.

    Wraps a TRUSTED, already-rendered HTML document (e.g. the Jinja
    ``render_template`` lane, FEAT-527 spec G5) as an opaque A2UI surface.
    Always emitted with ``origin=ProducerOrigin.TOOL`` — ``HtmlDocument`` is
    registered ``tool_only=True`` (TASK-2862) and an LLM-origin envelope
    containing it fails :func:`~parrot.outputs.a2ui.catalog.validate_envelope`.

    Args:
        title: Document title.
        html: Trusted, fully rendered HTML (inline when < 50 KB). Exactly
            one of ``html``/``src_url`` must be given.
        src_url: Signed artifact URL when the document is too large to inline.
        theme: Optional theme hint.
        surface_id: Envelope surface id.
        metadata: Optional component-level metadata (e.g. carrying
            ``extensions.parrot_optional``) forwarded to the underlying
            ``build_surface`` call and attached to the root component.

    Returns:
        The validated ``CreateSurface``.

    Raises:
        ValueError: If neither or both of ``html``/``src_url`` are given.
    """
    if (html is None) == (src_url is None):
        raise ValueError("build_html_document requires exactly one of 'html' or 'src_url'.")
    props: dict[str, Any] = {"title": title}
    if html is not None:
        props["html"] = html
    if src_url is not None:
        props["srcUrl"] = src_url
    if theme is not None:
        props["theme"] = theme
    return build_surface(
        "HtmlDocument",
        props,
        surface_id=surface_id,
        origin=ProducerOrigin.TOOL,
        metadata=metadata,
    )


def build_graph(
    *,
    nodes: Sequence[GraphNode | dict[str, Any]],
    edges: Sequence[GraphEdge | dict[str, Any]],
    kind: GraphKind = "flowchart",
    direction: Direction = "TB",
    title: str | None = None,
    accessible_description: str | None = None,
    size: VizSize = "tile",
    groups: Sequence[GraphGroup | dict[str, Any]] | None = None,
    layout: GraphLayout | dict[str, Any] | None = None,
    selection: GraphSelection | dict[str, Any] | None = None,
    data_binding: str | None = None,
    data_model: dict[str, Any] | None = None,
    action: Action | None = None,
    compute_layout: bool = True,
    surface_id: str = "graph",
    origin: ProducerOrigin = ProducerOrigin.TOOL,
) -> CreateSurface:
    """Build a display (or action-bearing, TOOL-origin) envelope carrying a
    single viz-core ``Graph`` component.

    Unlike every other ``build_*`` helper, the emitted ``Graph`` component
    carries its OWN ``catalogId`` (:data:`~parrot.outputs.a2ui.catalog.
    viz_core.VIZ_CORE_CATALOG_ID`) — the surface's default ``catalogId``
    stays the Parrot catalog (every public builder does this, spec §2 New
    Public Interfaces), so ``Graph`` resolves under viz-core purely via its
    own component-level override (spec §2 G2 resolution rule).

    Args:
        nodes: The graph's nodes (:class:`~parrot.outputs.a2ui.graph.
            GraphNode` instances or equivalent wire-shaped dicts).
        edges: The graph's edges.
        kind: ``GraphSpec.kind``.
        direction: ``GraphSpec.direction``.
        title: Optional display title.
        accessible_description: viz-core common prop; also the lowered
            fallback's first line and the SVG ``<title>`` on static lanes.
        size: viz-core common prop (layout intent, never pixels).
        groups: Optional node groupings.
        layout: Optional layout configuration. When given WITHOUT
            ``positions`` and ``compute_layout=True`` (default), positions
            are filled in (see ``compute_layout`` below); its own
            ``rank_sep``/``node_sep`` (if set) are honoured.
        selection: Optional selection state.
        data_binding: Optional data-model pointer (e.g. ``"/nodes"``) —
            becomes ``{"path": "/nodes"}`` on the wire, overlaying each
            node's ``state``/``label``/``meta`` at render time.
        data_model: The envelope's ``dataModel`` (forwarded to
            :func:`build_surface`).
        action: Optional component-level action. TOOL origin (this
            function's default) may carry one; ``origin=ProducerOrigin.LLM``
            with an ``action`` set is rejected by the existing
            ``ACTION_NOT_ALLOWED_FOR_LLM`` gate (spec G3 — no new gate).
        compute_layout: When ``True`` (default) and the (implicit or
            explicit) layout engine is ``"layered"`` with no ``positions``
            already given, fills ``layout.positions`` via
            :func:`~parrot.outputs.a2ui.graph.compute_positions`. ``False``
            leaves ``layout.positions`` absent (renderers without native
            layout call ``compute_positions`` themselves at render time).
        surface_id: Envelope surface id.
        origin: Producer origin forwarded to :func:`build_surface`'s
            :func:`~parrot.outputs.a2ui.catalog.validate_envelope` call.
            Defaults to ``TOOL`` (unlike every other ``build_*`` helper,
            which default to ``LLM``) since a builder-authored ``Graph`` —
            positions, `action` — is deterministic tool output by
            construction (spec's "authoring tiers": the LLM path never
            calls this builder with positions/`action` set).

    Returns:
        The validated :class:`~parrot.outputs.a2ui.models.CreateSurface`.
    """

    def _model(value, model_cls):
        if value is None or isinstance(value, model_cls):
            return value
        return model_cls(**value)

    node_models = [_model(n, GraphNode) for n in nodes]
    edge_models = [_model(e, GraphEdge) for e in edges]
    group_models = [_model(g, GraphGroup) for g in groups] if groups else None
    layout_model = _model(layout, GraphLayout)
    selection_model = _model(selection, GraphSelection)

    spec = GraphSpec(
        kind=kind,
        direction=direction,
        title=title,
        accessible_description=accessible_description,
        size=size,
        nodes=node_models,
        edges=edge_models,
        groups=group_models,
        layout=layout_model,
        selection=selection_model,
    )

    if compute_layout:
        engine = spec.layout.engine if spec.layout else "layered"
        positions_present = spec.layout.positions is not None if spec.layout else False
        if engine == "layered" and not positions_present:
            layout_kwargs: dict[str, float] = {}
            if spec.layout and spec.layout.rank_sep is not None:
                layout_kwargs["rank_sep"] = spec.layout.rank_sep
            if spec.layout and spec.layout.node_sep is not None:
                layout_kwargs["node_sep"] = spec.layout.node_sep
            result = compute_positions(spec, **layout_kwargs)
            base = spec.layout.model_dump(exclude_none=True) if spec.layout else {}
            spec = spec.model_copy(update={"layout": GraphLayout(**{**base, "positions": result.positions})})

    props = spec.model_dump(by_alias=True, exclude_none=True)
    props["catalogId"] = VIZ_CORE_CATALOG_ID

    binding = _binding(data_binding)
    if binding is not None:
        props["data"] = binding
    if action is not None:
        props["action"] = action

    return build_surface(
        "Graph",
        props,
        surface_id=surface_id,
        data_model=data_model,
        origin=origin,
    )
