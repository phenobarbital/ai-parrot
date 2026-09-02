"""FilterBar degradation tests on JS-less surfaces (FEAT-493, TASK-2715):
ssr-html (and pdf, which inherits its dispatch) render a static filter-state
summary line — never a `<select>`/dropdown."""

import pytest

pytest.importorskip("jsonpointer")

# Ensure the FilterBar catalog component self-registers.
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers import pdf as pdf_mod
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

pytestmark = pytest.mark.asyncio


def _filterbar_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="s",
        catalogId="c",
        components=[
            Component(
                id="root",
                component="FilterBar",
                filters=[
                    {
                        "column": "month",
                        "label": "Month",
                        "options": [{"label": "Aug-2026", "value": "2026-08"}],
                        "multiple": True,
                    },
                    {"column": "pay_code", "label": "Pay Code", "options": []},
                ],
            )
        ],
        dataModel={},
    )


class TestFilterBarDegradation:
    async def test_ssr_renders_summary_not_a_control(self):
        art = await SSRHTMLRenderer().render(_filterbar_envelope())
        doc = art.content.decode()
        assert "<select" not in doc
        assert "Filters:" in doc

    async def test_ssr_records_degradation(self):
        art = await SSRHTMLRenderer().render(_filterbar_envelope())
        degraded = art.metadata.get("degraded", [])
        assert any(d["component"] == "Row" for d in degraded)

    async def test_summary_names_unconstrained_filters_as_all(self):
        art = await SSRHTMLRenderer().render(_filterbar_envelope())
        doc = art.content.decode()
        assert "Month = Aug-2026" in doc
        assert "Pay Code = all" in doc

    async def test_pdf_inherits_the_degradation(self):
        doc, degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(_filterbar_envelope())
        assert "<select" not in doc
        assert "Filters:" in doc
        assert any(d["component"] == "Row" for d in degraded)
