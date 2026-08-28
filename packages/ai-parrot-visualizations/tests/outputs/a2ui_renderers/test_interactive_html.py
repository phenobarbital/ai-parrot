"""Unit tests for the interactive-HTML renderer (FEAT-324, Module 7;
rewritten to v1.0 by FEAT-470 TASK-2544)."""

import json
import re

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui.renderers import get_a2ui_renderer  # noqa: E402
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer  # noqa: E402

pytestmark = pytest.mark.asyncio


def _envelope(*components: Component, data_model=None) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=list(components),
        dataModel=data_model or {},
    )


class TestInteractiveHTMLRenderer:
    async def test_capabilities_declared(self):
        caps = InteractiveHTMLRenderer.capabilities
        assert caps.interactive is True
        assert caps.supports_actions is False
        assert caps.supports_updates is False
        assert caps.output == "text/html"

    async def test_registration_resolves(self):
        assert get_a2ui_renderer("interactive-html") is InteractiveHTMLRenderer

    async def test_interactive_html_self_contained(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["actual", "budget"],
                data={"path": "/rows"},
                title="Actual vs Budget",
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10, "budget": 8}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert doc.startswith("<!DOCTYPE html>")
        assert art.mime_type == "text/html"
        assert art.surface == "interactive-html"
        # Zero external network references — works from file://. A vendored
        # library's license-header comment MAY mention its homepage URL as
        # plain text; only actual resource-loading references are forbidden
        # (matches the SSR-HTML self-containment test's approach).
        externals = re.findall(r'(?:src|href)="https?://[^"]+"', doc)
        assert externals == []
        assert "@import" not in doc
        assert "<script src=" not in doc
        assert "<link " not in doc

    async def test_datamodel_embedded_and_parseable(self):
        data_model = {"rows": [{"day": "Mon", "actual": 10, "budget": 8}]}
        env = _envelope(
            Component(id="root", component="InfoCard", title="T"),
            data_model=data_model,
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        match = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', doc, re.DOTALL)
        assert match is not None
        parsed = json.loads(match.group(1))
        assert parsed == data_model

    async def test_chart_rendered_from_properties(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["actual", "budget"],
                data={"path": "/rows"},
                title="Actual vs Budget",
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10, "budget": 8}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Actual vs Budget" in doc
        assert "data-chart-config=" in doc
        assert "<canvas" in doc
        # Vendored Chart.js bundle is inlined (license header preserved).
        assert "Chart.js" in doc
        assert "MIT License" in doc
        # Multi-y-column chart gets metric-toggle buttons.
        assert "data-metric-toggle-for=" in doc
        assert "data-metric-index=" in doc

    async def test_chart_with_tabs_renders_day_tabs(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="line",
                x="division",
                y=["variance"],
                tabs={"path": "/tabs"},
                title="Daily Variance",
            ),
            data_model={
                "tabs": [
                    {"label": "Jul 1", "data": [{"division": "Sales", "variance": 10}]},
                    {"label": "Jul 22", "data": [{"division": "Sales", "variance": -5}]},
                ]
            },
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert 'data-tabs-for="' in doc
        assert 'data-tab-index="0"' in doc
        assert 'data-tab-index="1"' in doc
        assert "Jul 1" in doc and "Jul 22" in doc

    async def test_datatable_rendered_with_sort_hooks(self):
        env = _envelope(
            Component(
                id="root",
                component="DataTable",
                title="Ledger",
                columns=[{"name": "division", "title": "Division"}, {"name": "rev"}],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"division": "Sales", "rev": 100}, {"division": "Ops", "rev": 50}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-sort-table" in doc
        assert 'data-sort-key="division"' in doc
        assert 'data-sort-key="rev"' in doc
        assert "Sales" in doc and "Ops" in doc
        assert "<table" in doc

    async def test_non_chart_components_render_server_side(self):
        env = _envelope(
            Component(id="k0", component="KPICard", label="Revenue", value=100),
            Component(id="c1", component="InfoCard", title="Notes"),
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Revenue" in doc
        assert "Notes" in doc

    async def test_infographic_nested_chart_and_datatable(self):
        env = _envelope(
            Component(
                id="root",
                component="Infographic",
                title="Budget Variance",
                sections=[
                    {
                        "heading": "Overview",
                        "components": [
                            {
                                "component": "Chart",
                                "properties": {
                                    "type": "bar",
                                    "x": "day",
                                    "y": ["actual"],
                                    "data": {"path": "/rows"},
                                },
                            },
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [{"name": "day"}],
                                    "data": {"path": "/rows"},
                                },
                            },
                        ],
                    }
                ],
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Budget Variance" in doc
        assert "Overview" in doc
        assert "data-chart-config=" in doc
        assert "data-sort-table" in doc

    async def test_sort_and_tab_hooks_present_in_behavior_js(self):
        env = _envelope(Component(id="root", component="InfoCard", title="T"))
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-sort-table" in doc  # behavior JS references the hook name
        assert "data-tabs-for" in doc
        assert "data-metric-toggle-for" in doc


class TestTASK2544:
    """FEAT-470 TASK-2544: 18-primitive dispatch, Tabs/List/Divider/inputs."""

    async def test_interactive_html_renders_new_primitives(self):
        """Tabs/List/Divider/inputs are present in the DOM (spec acceptance
        criterion)."""
        env = _envelope(
            Component(
                id="root",
                component="Column",
                children=["tabs1", "list1", "div1", "tf1", "cb1"],
            ),
            Component(
                id="tabs1",
                component="Tabs",
                tabs=[{"title": "Tab A", "child": "ta1"}, {"title": "Tab B", "child": "tb1"}],
            ),
            Component(id="ta1", component="Text", text="content A"),
            Component(id="tb1", component="Text", text="content B"),
            Component(id="list1", component="List", direction="horizontal", children=["lt1"]),
            Component(id="lt1", component="Text", text="list item"),
            Component(id="div1", component="Divider", axis="horizontal"),
            Component(id="tf1", component="TextField", label="Name", value="Alice"),
            Component(id="cb1", component="CheckBox", label="Agree", value=True),
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-tabs=" in doc
        assert "data-tabs-panes=" in doc
        assert "content A" in doc and "content B" in doc
        assert "list item" in doc
        assert '<hr class="a2ui-divider-h">' in doc
        assert "Name" in doc and "Alice" in doc
        assert "Agree" in doc
        assert art.metadata.get("degraded", []) == []

    async def test_interactive_chart_reads_top_level_props(self):
        """Chart props (v1.0) live top-level, not nested under "properties"."""
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["actual"],
                data=[{"day": "Mon", "actual": 5}],
                title="Top Level",
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "Top Level" in doc
        assert '"day":"Mon"' in doc.replace(" ", "") or "Mon" in doc

    async def test_unsupported_component_degrades(self):
        env = _envelope(Component(id="root", component="NotARealComponent", foo="bar"))
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "no renderer" in doc.lower() or "not supported" in doc.lower()
        assert len(art.metadata["degraded"]) == 1
