"""Recipe schema migration — v1 -> v2 ``LayoutSpec`` (Module 6, FEAT-470 TASK-2542).

A v1 recipe's ``layout`` is exactly the legacy single-component shape
(``{"component": ..., "properties": {...}}``, nested ``{"$bind": ...}``
bindings) that :mod:`parrot.outputs.a2ui.compat` already knows how to
promote to the A2UI v1.0 wire shape (top-level props, ``{"path": ...}``
bindings) for a single :class:`~parrot.outputs.a2ui.models.Component` dict.
:func:`migrate_layout` reuses that exact transform — a v2 ``LayoutSpec`` IS
that same promoted shape.

:func:`migrate_store` sweeps an :class:`~parrot.outputs.a2ui.recipes.store.AbstractRecipeStore`,
re-saving every recipe still at ``schema_version < SUPPORTED_SCHEMA_VERSION``
(idempotent — a v2 recipe is a no-op) and reporting a :class:`MigrationReport`.

One-way import rule (G8): this module imports only a2ui core (``compat``)
plus sibling ``recipes`` modules — never ``parrot.bots``/``parrot.clients``/
``DatasetManager``.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot.outputs.a2ui.compat import normalize_legacy_component
from parrot.outputs.a2ui.recipes.store import (
    SUPPORTED_SCHEMA_VERSION,
    AbstractRecipeStore,
)

__all__ = ["MigrationReport", "migrate_layout", "migrate_store"]

logger = logging.getLogger(__name__)

#: Placeholder id promoted layouts are given before being handed to
#: ``compat.normalize_legacy_component`` (which mirrors a wire ``Component``
#: dict and requires an ``"id"`` key) and stripped back out immediately
#: after — a recipe ``LayoutSpec`` carries no wire id of its own (one is
#: assigned at emission time by ``build_surface``/``build_infographic``).
_PLACEHOLDER_LAYOUT_ID = "_recipe_layout"


class MigrationReport(BaseModel):
    """Outcome of a :func:`migrate_store` sweep.

    Attributes:
        dry_run: Whether this sweep only inspected recipes without writing.
        migrated: Names of recipes actually migrated (or that WOULD be,
            under ``dry_run``).
        already_current: Names of recipes already at
            ``SUPPORTED_SCHEMA_VERSION`` on disk (idempotent no-ops).
        errors: ``{name: error message}`` for recipes that failed to load or
            migrate — a single failure never aborts the sweep.
    """

    model_config = ConfigDict(populate_by_name=True)

    dry_run: bool = False
    migrated: list[str] = Field(default_factory=list)
    already_current: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


def migrate_layout(layout: dict[str, Any], *, from_version: int) -> dict[str, Any]:
    """Migrate a single recipe ``layout`` mapping from ``from_version`` to v2.

    Args:
        layout: The raw ``layout`` mapping (before ``LayoutSpec`` validation),
            e.g. ``{"component": "Infographic", "properties": {...}}`` (v1)
            or an already-v2-shaped mapping.
        from_version: The recipe's declared ``schema_version``.

    Returns:
        The equivalent v2 layout mapping (component name + top-level props,
        ``{"path"}`` bindings — nested composite-descriptor ``properties``
        wrappers, e.g. inside an ``Infographic``'s ``sections[].components[]``,
        are untouched: that is the composite's OWN authored-descriptor shape,
        not the wire ``Component`` shape ``LayoutSpec`` mirrors). Already-v2
        input (``from_version >= SUPPORTED_SCHEMA_VERSION``) is returned as a
        shallow copy, unchanged.

    Raises:
        ValueError: If ``from_version`` is outside ``[1, SUPPORTED_SCHEMA_VERSION]``.
    """
    if from_version < 1 or from_version > SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"Cannot migrate a layout from schema_version={from_version!r}: only "
            f"versions 1..{SUPPORTED_SCHEMA_VERSION} are supported."
        )
    if from_version >= SUPPORTED_SCHEMA_VERSION:
        return dict(layout)

    pseudo_component = {"id": _PLACEHOLDER_LAYOUT_ID, **layout}
    normalized = normalize_legacy_component(pseudo_component)
    normalized.pop("id", None)
    return normalized


async def migrate_store(
    store: AbstractRecipeStore, *, dry_run: bool = False
) -> MigrationReport:
    """Migrate every recipe in ``store`` to ``SUPPORTED_SCHEMA_VERSION`` (idempotent).

    Sweeps the unscoped (``owner=None``) recipe scope — the same scope
    ``store.list(owner=None)`` exposes; a caller with multiple known owner
    scopes calls this once per owner. A recipe already at
    ``SUPPORTED_SCHEMA_VERSION`` on disk is a no-op (idempotent — checked via
    ``store._raw_schema_version``, NOT ``store.get()``, since `get()` always
    returns an in-memory-migrated recipe and would otherwise make every
    recipe look current). Each recipe is read, migrated, and re-saved with
    its own ``store.get()``/``store.save()`` call — ``DBRecipeStore.save()``
    is a single atomic ``SET`` per recipe (spec: "transacción por receta"),
    so one recipe's failure never partially-writes another.

    Args:
        store: The recipe store to migrate in place.
        dry_run: If ``True``, only inspects recipes and reports what WOULD be
            migrated — never calls ``store.save``.

    Returns:
        A :class:`MigrationReport` summarizing the sweep.
    """
    report = MigrationReport(dry_run=dry_run)
    summaries = await store.list(owner=None)

    for summary in summaries:
        name = summary["name"]
        owner = summary.get("owner")
        try:
            raw_version = await store._raw_schema_version(name, owner=owner)
        except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
            report.errors[name] = str(exc)
            continue

        if raw_version == SUPPORTED_SCHEMA_VERSION:
            report.already_current.append(name)
            continue

        try:
            recipe = await store.get(name, owner=owner)  # auto-migrated in memory
            if not dry_run:
                await store.save(recipe)
            report.migrated.append(name)
        except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
            report.errors[name] = str(exc)

    return report
