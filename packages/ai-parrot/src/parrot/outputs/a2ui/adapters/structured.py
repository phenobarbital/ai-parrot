"""``StructuredXConfig`` → A2UI v1.0 ``CreateSurface`` adapter (FEAT-473 Module 2).

Bridges the deterministic STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
output path (:mod:`parrot.models.outputs`, FEAT-215/218/221) to the A2UI
``Chart``/``DataTable``/``Map`` parrot-catalog components (FEAT-470), so every
structured response additionally carries a spec-conformant v1.0
``CreateSurface`` alongside its existing ``response.output``/``response.data``
contract (spec §1 G1).

The three ``*_to_surface`` functions are **pure and deterministic**: same
config + rows → byte-identical envelope. No clocks, no uuids inside the
component tree, no network, no LLM tokens (spec D1). Every surface is built
with ``origin=ProducerOrigin.TOOL`` (rows/features may be inlined into the
data model directly — the ``origin=LLM`` inline-data guard, FEAT-473 G8, does
not apply to tool-built surfaces) and validated against BOTH the catalog
allowlist (:func:`~parrot.outputs.a2ui.catalog.validate_envelope`, on the raw
Parrot-catalog surface) and the official jsonschema wire spec
(:func:`~parrot.outputs.a2ui.catalog.validate_message`, on its LOWERED,
Basic-catalog-only form — the vendored ``agent_to_renderer.json``'s
``Component``/``anyComponent`` definition enumerates only the 18 official
Basic Catalog primitives, so a raw ``Chart``/``DataTable``/``Map`` component
cannot validate directly; this is the same two-layer conformance pattern
``tests/outputs/a2ui/conformance/test_all_emitters.py`` established for every
other emitter in this codebase).

One-way import rule (D4): this module imports only the a2ui core plus pure
``parrot.models.outputs`` config models — never agents, ``DatasetManager``,
LLM clients, or ``SpatialResult``. Callers (the satellite
``StructuredOutputBase._route_envelope`` hook, TASK-2563) hand over plain
rows / per-layer feature-dict lists, already canonicalised
(``canonical_records()``, satellite-side).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from parrot.models.outputs import (
    StructuredChartConfig,
    StructuredMapConfig,
    StructuredTableConfig,
)
from parrot.outputs.a2ui.builders import build_surface
from parrot.outputs.a2ui.catalog import get_component, validate_message
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, to_components
from parrot.outputs.a2ui.models import A2UIAgentMessage, Component, CreateSurface
from parrot.outputs.a2ui.serialization import A2UI_VERSION

__all__ = [
    "DEFAULT_ROW_LIMIT",
    "LAYER_FEATURES_PATH",
    "ROWS_PATH",
    "SCHEMA_VERSION",
    "chart_to_surface",
    "config_to_component_props",
    "map_to_surface",
    "root_component",
    "table_to_surface",
]

#: ``artifacts[]`` entry version marker (spec §2 G5) for surfaces built here.
SCHEMA_VERSION = 2

#: Data-model pointer for Chart/DataTable rows.
ROWS_PATH = "/rows"

#: Data-model pointer TEMPLATE for a Map layer's features (``.format(i=...)``).
LAYER_FEATURES_PATH = "/layers/{i}/features"

#: Row/feature cap applied to the DATA MODEL (``response.data``/per-layer
#: payloads keep the full set). Re-declared here (not imported from the
#: satellite's ``structured_table.DEFAULT_ROW_LIMIT``) — core must not import
#: the satellite (D4 one-way import rule). Kept in sync with that constant
#: (both ``1000``).
DEFAULT_ROW_LIMIT = 1000

#: Input-only fields excluded from the wire props by default (their rows/
#: features live in the data model instead, bound via ``{"path": ...}``).
_DEFAULT_EXCLUDE: frozenset[str] = frozenset({"data", "datasets"})


def _snake_to_camel(name: str) -> str:
    """Convert a ``snake_case`` identifier to ``camelCase`` (no-op otherwise).

    Needed because a couple of config fields
    (``StructuredTableConfig.total_rows``/``truncated``) have no Pydantic
    ``alias``, so ``model_dump(by_alias=True)`` leaves them ``snake_case`` —
    every OTHER top-level prop already round-trips to the correct
    ``camelCase`` wire name via its alias.

    Args:
        name: The field name to convert.

    Returns:
        The ``camelCase`` form of ``name``.
    """
    if "_" not in name:
        return name
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest if part)


def config_to_component_props(
    cfg: BaseModel,
    *,
    exclude: frozenset[str] = _DEFAULT_EXCLUDE,
) -> dict[str, Any]:
    """Dump a structured config model to top-level, camelCase component props.

    Args:
        cfg: A ``StructuredChartConfig``/``StructuredTableConfig``/
            ``StructuredMapConfig`` instance.
        exclude: Field names to drop entirely (the INPUT-ONLY row/feature
            lists — their data lives in the data model instead, bound via a
            ``{"path": ...}`` descriptor the caller adds separately).

    Returns:
        A dict of camelCase prop name → JSON-ready value, with ``None``
        values dropped (matching the satellite's existing
        ``exclude={"data"}`` dump convention).
    """
    dumped = cfg.model_dump(mode="json", by_alias=True, exclude=set(exclude))
    return {_snake_to_camel(key): value for key, value in dumped.items() if value is not None}


def _lower_to_basic_components(envelope: CreateSurface) -> list[Component]:
    """Lower every non-primitive (Parrot catalog) top-level component to Basic form.

    The vendored ``agent_to_renderer.json``'s ``Component``/``anyComponent``
    definition enumerates only the 18 official Basic Catalog primitives — a
    raw ``Chart``/``DataTable``/``Map`` component cannot validate against it
    directly. Mirrors the lowering pass every satellite renderer runs
    internally before baking (e.g. ``SSRHTMLRenderer._lower_composites``) and
    the identical helper in
    ``tests/outputs/a2ui/conformance/test_all_emitters.py`` — built entirely
    from the public catalog API (``get_component``, ``to_components``).

    Args:
        envelope: The surface to lower.

    Returns:
        The flat, Basic-catalog-only component list.
    """
    lowered: list[Component] = []
    for comp in envelope.components:
        entry = get_component(comp.component)
        if entry.definition.is_primitive:
            lowered.append(comp)
        else:
            tree = entry.component_cls().lower(comp, envelope.data_model)
            lowered.extend(to_components(tree, id_prefix=f"{comp.id}-lc"))
    return lowered


def _validate_wire(surface: CreateSurface) -> None:
    """Validate ``surface``'s LOWERED form against the official jsonschema wire spec.

    ``validate_envelope(origin=TOOL)`` already ran inside :func:`build_surface`
    — this adds the ``validate_message`` (jsonschema) leg (spec AC-1), on the
    lowered, Basic-catalog-only form (see :func:`_lower_to_basic_components`).

    Args:
        surface: The built, catalog-valid ``CreateSurface`` (root component is
            a Parrot-catalog ``Chart``/``DataTable``/``Map``).

    Raises:
        jsonschema.exceptions.ValidationError: If the lowered form does not
            match the official ``agent_to_renderer.json`` schema.
    """
    lowered_envelope = surface.model_copy(update={"components": _lower_to_basic_components(surface)})
    validate_message(A2UIAgentMessage(version=A2UI_VERSION, createSurface=lowered_envelope))


def chart_to_surface(
    cfg: StructuredChartConfig,
    rows: list[dict[str, Any]],
    *,
    surface_id: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> CreateSurface:
    """Convert a ``StructuredChartConfig`` + rows into a v1.0 ``CreateSurface``.

    Args:
        cfg: The chart configuration (rows/``data`` are ignored — passed
            separately as ``rows``).
        rows: The chart's data rows, already canonicalised (JSON-ready).
        surface_id: The surface id to mint (caller-supplied — the satellite
            mints ``f"{mode}-{uuid4().hex[:8]}"``, FEAT-224 pattern).
        row_limit: Maximum rows placed in the data model (``response.data``,
            set by the caller, keeps the full set regardless).

    Returns:
        A ``CreateSurface`` with root component ``id="root"``,
        ``component="Chart"``, every config field as a top-level camelCase
        prop, ``data={"path": "/rows"}``, and ``dataModel.rows`` (capped).
    """
    props = config_to_component_props(cfg)
    props["data"] = {"path": ROWS_PATH}
    data_model = {"rows": list(rows[:row_limit])}
    surface = build_surface("Chart", props, surface_id=surface_id, data_model=data_model, origin=ProducerOrigin.TOOL)
    _validate_wire(surface)
    return surface


def table_to_surface(
    cfg: StructuredTableConfig,
    rows: list[dict[str, Any]],
    *,
    surface_id: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> CreateSurface:
    """Convert a ``StructuredTableConfig`` + rows into a v1.0 ``CreateSurface``.

    Args:
        cfg: The table configuration (rows/``data`` are ignored — passed
            separately as ``rows``). If ``cfg.total_rows`` is set, it is
            treated as the caller's own true pre-cap count (e.g. a
            satellite renderer that already capped ``rows`` upstream via
            its own ``row_limit`` before calling this adapter) and takes
            precedence over ``len(rows)`` — see the "Known bug fixed"
            note below.
        rows: The table's data rows, already canonicalised (JSON-ready).
            May already be capped by the caller (in which case
            ``cfg.total_rows``/``cfg.truncated`` must carry the true
            values) or the full, uncapped set (in which case
            ``cfg.total_rows`` is typically unset/``None`` and this
            function computes truth from ``len(rows)`` itself).
        surface_id: The surface id to mint.
        row_limit: Maximum rows placed in the data model; overflow sets
            ``truncated=True``/``totalRows`` accordingly (``response.data``
            keeps the full set).

    Returns:
        A ``CreateSurface`` with root component ``id="root"``,
        ``component="DataTable"``, ``data={"path": "/rows"}``, and
        ``dataModel.rows`` (capped).

    Note:
        Bug fix (post-review): a caller that pre-caps ``rows`` to
        ``row_limit`` before calling this adapter (e.g.
        ``StructuredTableRenderer`` via ``canonical_records(row_limit=...)``)
        would previously cause ``len(rows)`` to silently equal the CAPPED
        count, so ``totalRows``/``truncated`` were always wrong (never
        flagged as truncated). Preferring ``cfg.total_rows`` — the true
        pre-cap count the renderer already computed — when present fixes
        this without requiring every caller to pass the full, uncapped row
        list.
    """
    props = config_to_component_props(cfg)
    total = cfg.total_rows if cfg.total_rows is not None else len(rows)
    props["data"] = {"path": ROWS_PATH}
    props["totalRows"] = total
    props["truncated"] = bool(cfg.truncated) or total > row_limit
    data_model = {"rows": list(rows[:row_limit])}
    surface = build_surface(
        "DataTable", props, surface_id=surface_id, data_model=data_model, origin=ProducerOrigin.TOOL
    )
    _validate_wire(surface)
    return surface


def map_to_surface(
    cfg: StructuredMapConfig,
    layer_features: list[list[dict[str, Any]]],
    *,
    surface_id: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> CreateSurface:
    """Convert a ``StructuredMapConfig`` + per-layer features into a ``CreateSurface``.

    Args:
        cfg: The map configuration (``data``/``datasets`` are ignored —
            per-layer features are passed separately as ``layer_features``,
            ordered as ``cfg.layers``). Each ``cfg.layers[i].total_count``,
            when it exceeds ``len(layer_features[i])``, is treated as a more
            authoritative true count (e.g. a prior spatial-query-level cap
            distinct from this adapter's own ``row_limit``) and preserved —
            see the "Known bug fixed" note below.
        layer_features: One feature-dict list per ``cfg.layers`` entry,
            ideally the FULL (uncapped) per-layer set so this function's own
            ``row_limit`` can accurately detect overflow (never
            ``SpatialResult`` — D4 one-way import rule).
        surface_id: The surface id to mint.
        row_limit: Maximum features placed in the data model PER LAYER;
            overflow sets that layer's ``capped=True`` and bumps
            ``totalCount`` to at least ``len(features)``.

    Returns:
        A ``CreateSurface`` with root component ``id="root"``,
        ``component="Map"``, each ``layers[i]`` binding
        ``data={"path": "/layers/{i}/features"}``, and
        ``dataModel.layers[i].features`` (capped).

    Note:
        Bug fix (post-review): a caller that pre-caps ``layer_features[i]``
        to ``row_limit`` before calling this adapter would previously cause
        ``len(features)`` to silently equal the CAPPED count, so
        ``totalCount``/``capped`` were always wrong (never flagged as
        capped). Taking ``max(cfg.layers[i].total_count, len(features))``
        fixes this whether the caller pre-caps or hands the full set — a
        real upstream ``total_count`` (e.g. from ``SpatialLayerResult``,
        which may already reflect a prior, unrelated cap) is never
        under-reported by this adapter's own capping.
    """
    props = config_to_component_props(cfg)
    layers_prop: list[dict[str, Any]] = props.get("layers", [])
    new_layers: list[dict[str, Any]] = []
    data_model_layers: list[dict[str, Any]] = []
    for i, layer_prop in enumerate(layers_prop):
        features = layer_features[i] if i < len(layer_features) else []
        total = max(int(layer_prop.get("totalCount") or 0), len(features))
        layer_copy = dict(layer_prop)
        layer_copy["data"] = {"path": LAYER_FEATURES_PATH.format(i=i)}
        layer_copy["totalCount"] = total
        layer_copy["capped"] = bool(layer_prop.get("capped")) or total > row_limit
        new_layers.append(layer_copy)
        data_model_layers.append({"features": list(features[:row_limit])})
    props["layers"] = new_layers
    data_model = {"layers": data_model_layers}
    surface = build_surface("Map", props, surface_id=surface_id, data_model=data_model, origin=ProducerOrigin.TOOL)
    _validate_wire(surface)
    return surface


def root_component(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return a serialized envelope's root component (``createSurface.components[0]``).

    Args:
        envelope: A ``serialize()``-shaped dict:
            ``{"version": "v1.0", "createSurface": {"components": [...], ...}}``.

    Returns:
        The first (and, for surfaces built here, only) component dict —
        ``id == "root"``.

    Raises:
        KeyError: If ``envelope`` is not a ``createSurface`` envelope.
        IndexError: If ``createSurface.components`` is empty.
    """
    return envelope["createSurface"]["components"][0]
