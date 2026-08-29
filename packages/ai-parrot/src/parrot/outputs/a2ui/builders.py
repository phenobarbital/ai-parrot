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
from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    ProducerOrigin,
    validate_envelope,
)
from parrot.outputs.a2ui.models import Component, CreateSurface

__all__ = [
    "build_card",
    "build_chart",
    "build_datatable",
    "build_infographic",
    "build_kpicard",
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
) -> CreateSurface:
    """Build and validate a single-component display ``CreateSurface``.

    Display-only: the envelope is validated with LLM-origin semantics so any
    ``requires_actions``/``action``-bearing component (and any unknown
    component) is rejected. ``component_id`` defaults to ``"root"`` so the
    envelope satisfies the v1.0 wire's root requirement (spec G6) out of the box.

    Raises:
        CatalogValidationError: If the component is unknown or action-bearing.
    """
    envelope = CreateSurface(
        surfaceId=surface_id,
        catalogId=DEFAULT_CATALOG_ID,
        components=[Component(id=component_id, component=component, **properties)],
        dataModel=data_model or {},
    )
    # Display-only guard (rejects action-bearing + unknown components).
    validate_envelope(envelope, origin=ProducerOrigin.LLM)
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
) -> CreateSurface:
    """Build a display envelope carrying a single Chart component."""
    props: dict[str, Any] = {"type": chart_type, "x": x, "y": list(y), "showLegend": show_legend}
    if title is not None:
        props["title"] = title
    binding = _binding(data_binding)
    if binding is not None:
        props["data"] = binding
    return build_surface("Chart", props, surface_id=surface_id)


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
    return build_surface("DataTable", props, surface_id=surface_id)


def build_infographic(
    *,
    title: str,
    sections: Sequence[dict[str, Any]],
    subtitle: str | None = None,
    theme: str | None = None,
    surface_id: str = "infographic",
    data_model: dict[str, Any] | None = None,
) -> CreateSurface:
    """Build a display envelope carrying a single Infographic composite component.

    ``sections`` is a list of ``{"heading": ..., "text"?: ..., "components"?: [...]}``
    dicts (nested ``components`` are ``{"component": name, "properties": {...}}``).
    """
    props: dict[str, Any] = {"title": title, "sections": [dict(s) for s in sections]}
    if subtitle is not None:
        props["subtitle"] = subtitle
    if theme is not None:
        props["theme"] = theme
    return build_surface("Infographic", props, surface_id=surface_id, data_model=data_model)
