"""Core-side bake tests for the v1.0 wire (FEAT-470 TASK-2538).

Skipped when ``jsonpointer`` (the ``ai-parrot-visualizations[a2ui]`` extra)
is unavailable — see ``ai-parrot-visualizations/tests/outputs/a2ui_renderers/
test_baking.py`` for the satellite-side counterpart.
"""

from __future__ import annotations

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.baking import (
    BakeError,
    _has_live_binding,
    bake_envelope,
)
from parrot.outputs.a2ui.models import Component, CreateSurface


def _surface(*components: Component, data_model: dict) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=list(components),
        dataModel=data_model,
    )


class TestBakeResolvesPathCallTemplate:
    def test_bake_resolves_absolute_path(self):
        surface = _surface(
            Component(id="root", component="Text", text={"path": "/title"}),
            data_model={"title": "Hello"},
        )
        baked = bake_envelope(surface)
        assert baked[0]["text"] == "Hello"

    def test_bake_evaluates_call(self):
        surface = _surface(
            Component(
                id="root",
                component="Text",
                text={"call": "formatString", "args": {"value": "Hi ${/name}"}},
            ),
            data_model={"name": "Bob"},
        )
        baked = bake_envelope(surface)
        assert baked[0]["text"] == "Hi Bob"

    def test_bake_expands_child_template_with_index(self):
        surface = _surface(
            Component(
                id="root",
                component="List",
                children={"componentId": "row", "path": "/items"},
            ),
            Component(
                id="row",
                component="Text",
                text={"call": "formatString", "args": {"value": "#${@index}: ${name}"}},
            ),
            data_model={"items": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
        )
        baked = bake_envelope(surface)
        root = next(c for c in baked if c["id"] == "root")
        assert root["children"] == ["row-0", "row-1", "row-2"]
        clones = [c for c in baked if c["id"].startswith("row-")]
        assert [c["text"] for c in clones] == ["#0: A", "#1: B", "#2: C"]
        # The template source component never appears standalone.
        assert not any(c["id"] == "row" for c in baked)


class TestBakeOptionalBindingOmitted:
    def test_optional_binding_omitted_not_raised(self):
        surface = _surface(
            Component(
                id="root",
                component="Text",
                text={"path": "/missing"},
                metadata={"extensions": {"parrot_optional": ["/missing"]}},
            ),
            data_model={},
        )
        baked = bake_envelope(surface)
        assert "text" not in baked[0]

    def test_required_binding_not_in_optional_list_still_raises(self):
        surface = _surface(
            Component(
                id="root",
                component="Text",
                text={"path": "/missing"},
                metadata={"extensions": {"parrot_optional": ["/other"]}},
            ),
            data_model={},
        )
        with pytest.raises(BakeError):
            bake_envelope(surface)


class TestBakeUnresolvableRaises:
    def test_bake_unresolvable_raises(self):
        surface = _surface(
            Component(id="root", component="Text", text={"path": "/nope"}),
            data_model={},
        )
        with pytest.raises(BakeError):
            bake_envelope(surface)

    def test_bake_unknown_template_source_raises(self):
        surface = _surface(
            Component(
                id="root",
                component="List",
                children={"componentId": "ghost", "path": "/items"},
            ),
            data_model={"items": [1, 2]},
        )
        with pytest.raises(BakeError):
            bake_envelope(surface)

    def test_bake_template_path_not_a_list_raises(self):
        surface = _surface(
            Component(
                id="root", component="List", children={"componentId": "row", "path": "/notalist"}
            ),
            Component(id="row", component="Text", text="x"),
            data_model={"notalist": {"a": 1}},
        )
        with pytest.raises(BakeError):
            bake_envelope(surface)


class TestBakeRelativePathInTemplateScope:
    def test_relative_path_resolves_against_scope(self):
        surface = _surface(
            Component(
                id="root", component="List", children={"componentId": "row", "path": "/items"}
            ),
            Component(id="row", component="Text", text={"path": "label"}),
            data_model={"items": [{"label": "One"}, {"label": "Two"}]},
        )
        baked = bake_envelope(surface)
        clones = [c for c in baked if c["id"].startswith("row-")]
        assert [c["text"] for c in clones] == ["One", "Two"]


class TestBakePostconditionNoLiveBinding:
    def test_all_baked_components_have_no_live_binding(self):
        surface = _surface(
            Component(id="root", component="Column", children=["a", "list"]),
            Component(id="a", component="Text", text={"path": "/title"}),
            Component(
                id="list", component="List", children={"componentId": "row", "path": "/items"}
            ),
            Component(id="row", component="Text", text={"path": "name"}),
            data_model={"title": "Hi", "items": [{"name": "X"}, {"name": "Y"}]},
        )
        baked = bake_envelope(surface)
        assert len(baked) == 5  # root, a, list, row-0, row-1 (row excluded standalone)
        for comp in baked:
            assert _has_live_binding(comp) is False
