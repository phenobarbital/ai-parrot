"""Unit tests for the interactive-HTML renderer (FEAT-324, Module 7)."""

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
                id="b0",
                component="Chart",
                properties={
                    "type": "bar",
                    "x": "day",
                    "y": ["actual", "budget"],
                    "data": {"$bind": "/rows"},
                    "title": "Actual vs Budget",
                },
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
            Component(id="b0", component="Card", properties={"title": "T"}),
            data_model=data_model,
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        match = re.search(
            r'<script type="application/json" id="report-data">(.*?)</script>', doc, re.DOTALL
        )
        assert match is not None
        parsed = json.loads(match.group(1))
        assert parsed == data_model

    async def test_chart_rendered_from_properties(self):
        env = _envelope(
            Component(
                id="b0",
                component="Chart",
                properties={
                    "type": "bar",
                    "x": "day",
                    "y": ["actual", "budget"],
                    "data": {"$bind": "/rows"},
                    "title": "Actual vs Budget",
                },
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
                id="b0",
                component="Chart",
                properties={
                    "type": "line",
                    "x": "division",
                    "y": ["variance"],
                    "tabs": {"$bind": "/tabs"},
                    "title": "Daily Variance",
                },
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
                id="b0",
                component="DataTable",
                properties={
                    "title": "Ledger",
                    "columns": [{"name": "division", "title": "Division"}, {"name": "rev"}],
                    "data": {"$bind": "/rows"},
                },
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
            Component(
                id="b0", component="KPICard", properties={"label": "Revenue", "value": 100}
            ),
            Component(id="b1", component="Card", properties={"title": "Notes"}),
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Revenue" in doc
        assert "Notes" in doc

    async def test_infographic_nested_chart_and_datatable(self):
        env = _envelope(
            Component(
                id="b0",
                component="Infographic",
                properties={
                    "title": "Budget Variance",
                    "sections": [
                        {
                            "heading": "Overview",
                            "components": [
                                {
                                    "component": "Chart",
                                    "properties": {
                                        "type": "bar",
                                        "x": "day",
                                        "y": ["actual"],
                                        "data": {"$bind": "/rows"},
                                    },
                                },
                                {
                                    "component": "DataTable",
                                    "properties": {
                                        "columns": [{"name": "day"}],
                                        "data": {"$bind": "/rows"},
                                    },
                                },
                            ],
                        }
                    ],
                },
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
        env = _envelope(Component(id="b0", component="Card", properties={"title": "T"}))
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-sort-table" in doc  # behavior JS references the hook name
        assert "data-tabs-for" in doc
        assert "data-metric-toggle-for" in doc
