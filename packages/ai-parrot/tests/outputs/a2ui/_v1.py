"""Shared A2UI v1.0 fixture constructors (FEAT-470 TASK-2532).

Reused across the FEAT-470 test suite so each task doesn't hand-roll its own
JSON envelopes. Kept dependency-free (only imports ``parrot.outputs.a2ui``)
so any test module can import it without pulling in heavier fixtures.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.models import Component, CreateSurface

#: A stable, minimal-but-non-trivial default catalog id used across fixtures.
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"


def make_component(component: str, *, id: str = "blk-000", **props: Any) -> Component:
    """Build a v1.0 :class:`Component` with props passed straight through.

    Args:
        component: The catalog component type name (e.g. ``"Text"``).
        id: The component id. Defaults to ``"blk-000"``.
        **props: Component-specific top-level properties (e.g. ``text="hi"``)
            plus any of the generic envelope fields (``catalogId``, ``child``,
            ``children``, ``weight``, ``accessibility``, ``checks``,
            ``action``, ``metadata``).

    Returns:
        The constructed :class:`Component`.
    """
    return Component(id=id, component=component, **props)


def make_root_column(children: list[Component]) -> list[Component]:
    """Build a ``root`` ``Column`` component wrapping ``children`` by id.

    Args:
        children: The child components (already constructed).

    Returns:
        ``[root_column, *children]`` — the root ``Column`` followed by its
        children, ready to drop into ``CreateSurface.components``.
    """
    root = Component(
        id="root", component="Column", children=[c.id for c in children]
    )
    return [root, *children]


def make_create_surface(
    components: list[Component] | None = None,
    *,
    surface_id: str = "main",
    catalog_id: str = DEFAULT_CATALOG_ID,
    data_model: dict[str, Any] | None = None,
) -> CreateSurface:
    """Build a minimal, valid v1.0 :class:`CreateSurface`.

    Args:
        components: Inline components. Defaults to a single ``root`` ``Text``.
        surface_id: The surface id. Defaults to ``"main"``.
        catalog_id: The surface-level default catalog id.
        data_model: The initial data model. Defaults to ``{}``.

    Returns:
        The constructed :class:`CreateSurface`.
    """
    if components is None:
        components = [Component(id="root", component="Text", text="Hello")]
    return CreateSurface(
        surfaceId=surface_id,
        catalogId=catalog_id,
        components=components,
        dataModel=data_model or {},
    )


def legacy_create_surface_envelope() -> dict[str, Any]:
    """A representative pre-v1.0 dialect ``createSurface`` envelope.

    Exercises: ``messageType``, nested ``properties``, a legacy ``Card``
    (which must normalize to ``InfoCard``), and a ``{"$bind", "optional"}``
    binding (which must normalize to ``{"path": ...}`` plus
    ``metadata.extensions.parrot_optional``).

    Returns:
        The legacy-dialect envelope dict.
    """
    return {
        "messageType": "createSurface",
        "surfaceId": "main",
        "catalogId": DEFAULT_CATALOG_ID,
        "components": [
            {
                "id": "blk-000",
                "component": "Column",
                "properties": {},
                "children": ["blk-001"],
            },
            {
                "id": "blk-001",
                "component": "Card",
                "properties": {
                    "title": {"$bind": "/title"},
                    "subtitle": {"$bind": "/subtitle", "optional": True},
                },
                "children": [],
            },
        ],
        "dataModel": {"title": "Hello", "subtitle": "World"},
    }
