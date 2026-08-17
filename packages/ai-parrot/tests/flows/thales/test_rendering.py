"""Golden-file determinism tests for `parrot.flows.thales.rendering` (TASK-2228)."""

import pytest

from parrot.flows.thales.models import Bibliography, SlideSpec
from parrot.flows.thales.rendering import charts, document, slides


@pytest.fixture
def sample_slide_spec() -> SlideSpec:
    return SlideSpec(
        deck_ref="d1", layout="default", headline="H",
        bullets=["b1"],
        charts=[{"type": "bar", "labels": ["a"], "series": [{"name": "s", "data": [1]}]}],
        tables=[], quotes=[],
    )


@pytest.fixture
def no_chart_slide_spec() -> SlideSpec:
    return SlideSpec(
        deck_ref="d2", layout="default", headline="No charts",
        bullets=["b1"],
        tables=[{"headers": ["A"], "rows": [["1"]]}],
        quotes=[{"text": "quoted text", "source": "Someone"}],
    )


class TestRenderSlide:
    @pytest.mark.asyncio
    async def test_slide_render_deterministic(self, sample_slide_spec):
        one = await slides.render_slide(sample_slide_spec)
        two = await slides.render_slide(sample_slide_spec)
        assert one == two and "<svg" in one or "echarts" in one

    @pytest.mark.asyncio
    async def test_slide_render_byte_identical(self, sample_slide_spec):
        one = await slides.render_slide(sample_slide_spec)
        two = await slides.render_slide(sample_slide_spec)
        assert one == two

    @pytest.mark.asyncio
    async def test_charts_only_when_present(self, no_chart_slide_spec):
        html = await slides.render_slide(no_chart_slide_spec)
        assert "thales-slide-charts" not in html
        assert "thales-slide-tables" in html
        assert "thales-slide-quotes" in html
        assert "quoted text" in html


class TestRenderDocument:
    @pytest.mark.asyncio
    async def test_document_print_css(self, sample_slide_spec):
        html = await document.render_document(
            ["<section class='slide'>s1</section>"],
            Bibliography(entries=["Doe, J. (2024)..."], claims=[]),
            title="T",
        )
        assert "@page" in html and "page-break" in html
        assert html.rstrip().find("Doe, J.") > html.find("slide")  # bibliography last

    @pytest.mark.asyncio
    async def test_document_deterministic(self):
        bib = Bibliography(entries=["A", "B"], claims=[])
        one = await document.render_document(["<section>s1</section>"], bib, title="T")
        two = await document.render_document(["<section>s1</section>"], bib, title="T")
        assert one == two


class TestRasterizePdf:
    def test_pdf_optional(self, monkeypatch):
        monkeypatch.setattr(document, "_import_weasyprint", lambda: None)
        assert document.rasterize_pdf("<html></html>") is None

    def test_pdf_emitted_when_weasyprint_available(self, monkeypatch):
        class _FakeHTML:
            def __init__(self, string):
                self.string = string

            def write_pdf(self):
                return b"%PDF-fake"

        class _FakeWeasyprint:
            HTML = _FakeHTML

        monkeypatch.setattr(document, "_import_weasyprint", lambda: _FakeWeasyprint())
        result = document.rasterize_pdf("<html></html>")
        assert result == b"%PDF-fake"


class TestCharts:
    def test_echarts_block_deterministic(self):
        chart = {"type": "bar", "labels": ["a", "b"], "series": [{"name": "s", "data": [1, 2]}]}
        one = charts.echarts_option_block(chart)
        two = charts.echarts_option_block(chart)
        assert one == two
        assert "echarts" in one

    def test_static_svg_bar(self):
        chart = {"type": "bar", "labels": ["a"], "series": [{"name": "s", "data": [1]}]}
        svg = charts.static_svg_chart(chart)
        assert svg.startswith("<svg")
        assert "<rect" in svg

    def test_static_svg_line(self):
        chart = {"type": "line", "labels": ["a", "b"], "series": [{"name": "s", "data": [1, 2]}]}
        svg = charts.static_svg_chart(chart)
        assert svg.startswith("<svg")
        assert "<polyline" in svg


def test_no_matplotlib_import():
    import ast
    from pathlib import Path

    pkg_dir = Path(__file__).parents[3] / "src" / "parrot" / "flows" / "thales"
    for py_file in pkg_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "matplotlib" not in alias.name, py_file
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module and "matplotlib" in node.module), py_file
