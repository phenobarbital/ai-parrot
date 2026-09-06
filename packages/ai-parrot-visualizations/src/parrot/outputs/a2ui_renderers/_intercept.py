"""Catalog-aware renderer interception helpers (FEAT-529 Module 0).

Every satellite renderer draws a handful of composite components (``Chart``,
``DataTable``, ``Map``, ...) NATIVELY, intercepting them before the generic
lowering pass runs (see ``interactive_html.py``'s ``_INTERCEPTED``,
``ssr_html.py``'s ``_lower_composites``). Until now that interception was
keyed by bare component NAME alone — safe only because every catalog had a
disjoint name set. With a second catalog (``viz-core``) registering
components, interception must resolve the SAME catalog id
:func:`~parrot.outputs.a2ui.catalog.resolve_catalog` would (component's own
``catalogId``, else the surface default) and key on the
``(catalog_id, name)`` pair — so a future viz-core ``Chart`` and the existing
Parrot ``Chart`` never intercept for each other's renderer branch.
"""

from __future__ import annotations

from parrot.outputs.a2ui.catalog import resolve_catalog
from parrot.outputs.a2ui.models import Component

__all__ = ["intercepts", "resolve_component_catalog"]


def resolve_component_catalog(comp: Component, surface_catalog_id: str | None) -> str:
    """Resolve the effective catalog id for a wire ``Component``.

    Thin wrapper over :func:`parrot.outputs.a2ui.catalog.resolve_catalog` so
    renderers never re-implement the component-vs-surface precedence rule.

    Args:
        comp: The wire component.
        surface_catalog_id: The owning surface's default ``catalogId``.

    Returns:
        The resolved catalog id.

    Raises:
        CatalogValidationError: If neither the component nor the surface
            declares a catalog id.
    """
    return resolve_catalog(comp.catalog_id, surface_catalog_id)


def intercepts(
    table: frozenset[tuple[str, str]],
    comp: Component,
    surface_catalog_id: str | None,
) -> bool:
    """Whether ``comp`` should be drawn natively instead of lowered.

    Args:
        table: A frozenset of ``(catalog_id, name)`` pairs this renderer
            draws natively — e.g.
            ``{(DEFAULT_CATALOG_ID, "Chart"), (VIZ_CORE_CATALOG_ID, "Graph")}``.
        comp: The wire component being considered.
        surface_catalog_id: The owning surface's default ``catalogId``.

    Returns:
        ``True`` if ``comp``'s resolved ``(catalog_id, name)`` is in
        ``table``. ``False`` (never raises) when the catalog id cannot be
        resolved — an unresolved component is a validation failure caught
        elsewhere, not this helper's concern.
    """
    try:
        resolved = resolve_component_catalog(comp, surface_catalog_id)
    except Exception:  # noqa: BLE001 - CatalogValidationError; validation reports it elsewhere
        return False
    return (resolved, comp.component) in table
