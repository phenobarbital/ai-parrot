"""Unit tests for the PDF renderer (TASK-1732, rewritten to v1.0 by FEAT-470 TASK-2543)."""

import threading

import pytest

pytest.importorskip("jsonpointer")
pytest.importorskip("weasyprint")

from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui.renderers import get_a2ui_renderer  # noqa: E402
from parrot.outputs.a2ui_renderers import pdf as pdf_mod  # noqa: E402

pytestmark = pytest.mark.asyncio


def _envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="report",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="region",
                y=["rev"],
                title="Rev",
                data={"path": "/rows"},
            )
        ],
        dataModel={"rows": [{"region": "EU", "rev": 5}, {"region": "NA", "rev": 3}]},
    )


class TestPDFRenderer:
    async def test_capabilities_declared(self):
        caps = pdf_mod.PDFRenderer.capabilities
        assert caps.interactive is False
        assert caps.supports_actions is False
        assert caps.output == "application/pdf"

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("pdf") is pdf_mod.PDFRenderer

    async def test_renders_baked_ssr_html_to_pdf(self):
        art = await pdf_mod.PDFRenderer().render(_envelope())
        assert art.mime_type == "application/pdf"
        assert art.content is not None and art.path is None
        assert art.content[:5] == b"%PDF-"

    async def test_charts_prerendered_to_svg_under_weasyprint(self):
        doc, _degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(_envelope())
        assert "<svg" in doc
        assert "<script" not in doc  # no JS-dependent chart content

    async def test_missing_backend_actionable_error(self, monkeypatch):
        def _boom():
            raise ImportError("no weasyprint")

        monkeypatch.setattr(pdf_mod, "_import_weasyprint", _boom)
        with pytest.raises(ImportError) as exc:
            pdf_mod.PDFRenderer()._rasterize("<html></html>")
        assert "ai-parrot-visualizations[a2ui-pdf]" in str(exc.value)

    async def test_render_does_not_block_event_loop(self, monkeypatch):
        seen = {}

        def _fake_rasterize(self, document):
            seen["thread"] = threading.current_thread().name
            return b"%PDF-fake"

        monkeypatch.setattr(pdf_mod.PDFRenderer, "_rasterize", _fake_rasterize)
        art = await pdf_mod.PDFRenderer().render(_envelope())
        assert art.content == b"%PDF-fake"
        # _rasterize ran off the main thread (via asyncio.to_thread).
        assert seen["thread"] != threading.main_thread().name


class TestTASK2543:
    """FEAT-470 TASK-2543: PDF declares supported_components sans Video/Audio."""

    async def test_pdf_degrades_media_to_links(self):
        caps = pdf_mod.PDFRenderer.capabilities
        assert "Video" not in caps.supported_components
        assert "AudioPlayer" not in caps.supported_components
        assert "Text" in caps.supported_components

    async def test_video_degrades_to_notice_under_pdf(self):
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[Component(id="root", component="Video", url="https://x/v.mp4")],
            dataModel={},
        )
        doc, degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(env)
        assert "<video" not in doc
        assert len(degraded) == 1
        assert degraded[0]["component"] == "Video"


class TestHtmlDocumentUnderPdf:
    """FEAT-527: PDFRenderer inherits SSRHTMLRenderer's HtmlDocument
    degradation with zero code changes — the titled link survives the print
    layout (weasyprint renders plain `<a href>` fine)."""

    async def test_htmldocument_link_survives_print_layout(self):
        env = CreateSurface(
            surfaceId="s", catalogId="c",
            components=[
                Component(id="root", component="HtmlDocument", title="Doc", srcUrl="https://x/infographic-a.html")
            ],
            dataModel={},
        )
        doc, degraded = await pdf_mod.PDFRenderer()._build_intermediate_html(env)
        assert '<a href="https://x/infographic-a.html">Doc</a>' in doc
        assert any("HtmlDocument" in d.get("reason", "") for d in degraded)
