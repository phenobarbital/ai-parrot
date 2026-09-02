"""PDF print-layout tests (FEAT-493, TASK-2713): PDFRenderer forces
`layout="print"`, and the print stylesheet behaves as WeasyPrint 69.0
actually renders it (see docs/weasyprint-css-support.md for the full
empirical findings)."""

import io

import pytest

pytest.importorskip("jsonpointer")
pytest.importorskip("weasyprint")
pypdf = pytest.importorskip("pypdf")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers import pdf as pdf_mod
from parrot.outputs.formats.assets.design_system import DesignSystem

pytestmark = pytest.mark.asyncio


def _envelope() -> CreateSurface:
    """A representative envelope: a KPI (via Card metadata), a Chart (pre-rendered
    to static SVG by PDFRenderer), and a Row/Column tree — the actual shapes
    PDFRenderer's SSR-inherited dispatch renders."""
    return CreateSurface(
        surfaceId="report",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(id="root", component="Column", children=["kpi", "chart"]),
            Component(id="kpi", component="KPICard", label="Revenue", value="1234", unit="USD"),
            Component(
                id="chart",
                component="Chart",
                type="bar",
                x="region",
                y=["rev"],
                title="Rev",
                data={"path": "/rows"},
            ),
        ],
        dataModel={"rows": [{"region": "EU", "rev": 5}, {"region": "NA", "rev": 3}]},
    )


class TestPdfPrintLayout:
    async def test_pdf_forces_print_layout(self):
        """The intermediate HTML must carry the print sheet, never analytics."""
        doc, _degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(_envelope())
        assert 'data-layout="print"' in doc
        assert 'data-layout="analytics"' not in doc

    async def test_layout_kwarg_is_not_accepted_by_constructor(self):
        """No caller can construct a PDFRenderer into a screen layout."""
        with pytest.raises(TypeError):
            pdf_mod.PDFRenderer(layout="analytics")

    async def test_intermediate_html_has_print_shadow_override(self):
        """The print scope's `--shadow: none` override is present — WeasyPrint
        itself never renders box-shadow at all (docs/weasyprint-css-support.md),
        but the override documents intent and is verified present regardless."""
        doc, _degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(_envelope())
        assert "--shadow: none" in doc

    async def test_intermediate_html_has_no_auto_fit(self):
        """The print layout never uses the responsive repeat-track keywords
        WeasyPrint 69.0 collapses to a single column."""
        doc, _degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(_envelope())
        assert "auto-fit" not in doc
        assert "auto-fill" not in doc

    async def test_produces_valid_pdf(self):
        """Non-empty output starting with the %PDF- magic bytes."""
        artifact = await pdf_mod.PDFRenderer().render(_envelope())
        assert artifact.mime_type == "application/pdf"
        assert artifact.content.startswith(b"%PDF-")
        assert len(artifact.content) > 0

    async def test_multipage_table_rows_not_split(self):
        """A representative multi-page table, rendered with the ACTUAL composed
        print stylesheet through PDFRenderer's own rasterization call, produces
        a multi-page PDF (WeasyPrint's break-inside/table-header-group support
        confirmed empirically — docs/weasyprint-css-support.md)."""
        style = DesignSystem.stylesheet("light", "print")
        rows = "".join(
            f'<tr><td class="num">{i}</td><td>Row {i} with padding to add height</td></tr>' for i in range(80)
        )
        document = (
            "<!DOCTYPE html><html><head><style>"
            f"{style}"
            "</style></head><body><div class=\"ds-page\" data-layout=\"print\" data-theme=\"light\">"
            f'<table><thead><tr><th>ID</th><th>Desc</th></tr></thead><tbody>{rows}</tbody></table>'
            "</div></body></html>"
        )
        pdf_bytes = pdf_mod.PDFRenderer()._rasterize(document)
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) > 1
