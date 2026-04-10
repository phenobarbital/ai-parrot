"""
Comprehensive tests for the Infographic HTML Output feature (FEAT-094).

Covers:
- Theme system (ThemeConfig, ThemeRegistry, built-in themes)
- Block renderers (all 12 block types)
- ECharts chart mapping (all ChartType values)
- Document structure (HTML5, CSS variables, responsive/print)
- Content negotiation wiring
- Edge cases (empty, unknown, XSS, special characters)
"""
import pytest

from parrot.models.infographic import (
    BlockType,
    BulletListBlock,
    CalloutBlock,
    CalloutLevel,
    ChartBlock,
    ChartDataSeries,
    ChartType,
    DividerBlock,
    HeroCardBlock,
    ImageBlock,
    InfographicResponse,
    ProgressBlock,
    ProgressItem,
    QuoteBlock,
    SummaryBlock,
    TableBlock,
    ThemeConfig,
    ThemeRegistry,
    TimelineBlock,
    TimelineEvent,
    TitleBlock,
    TrendDirection,
    theme_registry,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def renderer():
    """Fresh InfographicHTMLRenderer instance."""
    return InfographicHTMLRenderer()


@pytest.fixture
def basic_response():
    """Minimal InfographicResponse with 3 block types."""
    return InfographicResponse(
        template="basic",
        theme="light",
        blocks=[
            TitleBlock(type="title", title="Test Report", subtitle="Q4 2025"),
            HeroCardBlock(type="hero_card", label="Revenue", value="$1.2M"),
            SummaryBlock(type="summary", content="**Key findings** from the analysis."),
        ],
    )


@pytest.fixture
def full_infographic_response():
    """InfographicResponse with all 12 block types for integration testing."""
    return InfographicResponse(
        template="executive",
        theme="light",
        blocks=[
            TitleBlock(
                type="title", title="Full Test Report", subtitle="All Block Types",
                author="Test", date="2026-04-10",
            ),
            HeroCardBlock(
                type="hero_card", label="Revenue", value="$1.2M",
                trend=TrendDirection.UP, trend_value="+15%", color="#10b981",
            ),
            HeroCardBlock(
                type="hero_card", label="Users", value="50K",
                trend=TrendDirection.DOWN, trend_value="-3%",
            ),
            HeroCardBlock(
                type="hero_card", label="NPS", value="72",
                trend=TrendDirection.FLAT,
            ),
            SummaryBlock(
                type="summary", title="Executive Summary",
                content="**Strong** quarter with *notable* growth in key metrics.",
            ),
            DividerBlock(type="divider", style="gradient"),
            ChartBlock(
                type="chart", chart_type=ChartType.BAR, title="Quarterly Revenue",
                labels=["Q1", "Q2", "Q3", "Q4"],
                series=[ChartDataSeries(name="2025", values=[100, 200, 150, 300])],
                x_axis_label="Quarter", y_axis_label="Revenue ($K)",
            ),
            ChartBlock(
                type="chart", chart_type=ChartType.PIE, title="Market Share",
                labels=["Product A", "Product B", "Product C"],
                series=[ChartDataSeries(name="Share", values=[45, 30, 25])],
            ),
            TableBlock(
                type="table", title="Top Performers",
                columns=["Name", "Revenue", "Growth"],
                rows=[["Alpha", "$500K", "+20%"], ["Beta", "$400K", "+15%"]],
                highlight_first_column=True,
            ),
            BulletListBlock(
                type="bullet_list", title="Key Recommendations",
                items=["Expand into new markets", "Increase R&D investment",
                       "Optimize supply chain"],
                ordered=True,
            ),
            CalloutBlock(
                type="callout", level=CalloutLevel.SUCCESS,
                title="Milestone", content="Achieved 100K customer milestone",
            ),
            ImageBlock(
                type="image", url="https://example.com/chart.png",
                alt="Overview chart", caption="Figure 1: Overview",
            ),
            QuoteBlock(
                type="quote",
                text="Innovation distinguishes leaders from followers.",
                author="Steve Jobs",
            ),
            TimelineBlock(
                type="timeline", title="Project Milestones",
                events=[
                    TimelineEvent(date="2026-01", title="Phase 1", description="Research"),
                    TimelineEvent(date="2026-03", title="Phase 2", description="Development"),
                    TimelineEvent(date="2026-06", title="Phase 3", description="Launch"),
                ],
            ),
            ProgressBlock(
                type="progress", title="OKR Progress",
                items=[
                    ProgressItem(label="Revenue Target", value=75, target=100, color="#10b981"),
                    ProgressItem(label="User Growth", value=90, color="#6366f1"),
                ],
            ),
        ],
    )


@pytest.fixture
def sample_theme():
    """Custom test theme."""
    return ThemeConfig(name="test", primary="#ff0000", primary_dark="#cc0000")


# ──────────────────────────────────────────────
# Theme System Tests
# ──────────────────────────────────────────────

class TestThemeConfig:
    """Tests for ThemeConfig model."""

    def test_defaults(self):
        theme = ThemeConfig(name="test")
        assert theme.primary == "#6366f1"
        assert theme.font_family.startswith("-apple-system")

    def test_custom_values(self):
        theme = ThemeConfig(name="custom", primary="#000", neutral_text="#fff")
        assert theme.primary == "#000"
        assert theme.neutral_text == "#fff"

    def test_to_css_variables(self):
        theme = ThemeConfig(name="test", primary="#ff0000")
        css = theme.to_css_variables()
        assert ":root" in css
        assert "--primary: #ff0000" in css
        assert "--primary-dark:" in css
        assert "--neutral-text:" in css
        assert "--body-bg:" in css
        assert "--font-family:" in css

    def test_to_css_variables_all_tokens(self):
        theme = ThemeConfig(name="test")
        css = theme.to_css_variables()
        expected_tokens = [
            "--primary:", "--primary-dark:", "--primary-light:",
            "--accent-green:", "--accent-amber:", "--accent-red:",
            "--neutral-bg:", "--neutral-border:", "--neutral-muted:",
            "--neutral-text:", "--body-bg:", "--font-family:",
        ]
        for token in expected_tokens:
            assert token in css, f"Missing CSS token: {token}"


class TestThemeRegistry:
    """Tests for ThemeRegistry."""

    def test_builtin_light(self):
        theme = theme_registry.get("light")
        assert theme.name == "light"
        assert theme.primary == "#6366f1"

    def test_builtin_dark(self):
        theme = theme_registry.get("dark")
        assert theme.name == "dark"
        assert theme.neutral_text == "#f1f5f9"  # light text on dark

    def test_builtin_corporate(self):
        theme = theme_registry.get("corporate")
        assert theme.name == "corporate"
        assert theme.primary == "#1e40af"

    def test_custom_registration(self):
        reg = ThemeRegistry()
        custom = ThemeConfig(name="brand", primary="#e11d48")
        reg.register(custom)
        assert reg.get("brand").primary == "#e11d48"

    def test_unknown_raises(self):
        with pytest.raises(KeyError, match="nonexistent"):
            theme_registry.get("nonexistent")

    def test_list_themes(self):
        names = theme_registry.list_themes()
        assert "light" in names
        assert "dark" in names
        assert "corporate" in names

    def test_overwrite_registration(self):
        reg = ThemeRegistry()
        reg.register(ThemeConfig(name="x", primary="#aaa"))
        reg.register(ThemeConfig(name="x", primary="#bbb"))
        assert reg.get("x").primary == "#bbb"


# ──────────────────────────────────────────────
# Block Renderer Tests
# ──────────────────────────────────────────────

class TestTitleBlock:
    def test_render(self, renderer):
        block = TitleBlock(type="title", title="Hello", subtitle="World")
        html = renderer._render_title(block)
        assert "Hello" in html
        assert "World" in html
        assert "hero" in html

    def test_with_author_date(self, renderer):
        block = TitleBlock(type="title", title="T", author="A", date="2026")
        html = renderer._render_title(block)
        assert "A" in html
        assert "2026" in html

    def test_xss_prevention(self, renderer):
        block = TitleBlock(type="title", title="<script>alert(1)</script>")
        html = renderer._render_title(block)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestHeroCardBlock:
    def test_render(self, renderer):
        block = HeroCardBlock(
            type="hero_card", label="Rev", value="$1M",
            trend=TrendDirection.UP, trend_value="+10%",
        )
        html = renderer._render_hero_card(block)
        assert "$1M" in html
        assert "Rev" in html
        assert "kpi-card" in html

    def test_trend_arrows(self, renderer):
        for trend, arrow_code in [
            (TrendDirection.UP, "&#9650;"),
            (TrendDirection.DOWN, "&#9660;"),
            (TrendDirection.FLAT, "&#9654;"),
        ]:
            block = HeroCardBlock(
                type="hero_card", label="X", value="1", trend=trend,
            )
            html = renderer._render_hero_card(block)
            assert arrow_code in html

    def test_custom_color(self, renderer):
        block = HeroCardBlock(
            type="hero_card", label="X", value="1", color="#ff0000",
        )
        html = renderer._render_hero_card(block)
        assert "#ff0000" in html


class TestSummaryBlock:
    def test_markdown_rendering(self, renderer):
        block = SummaryBlock(type="summary", content="**bold** and *italic*")
        html = renderer._render_summary(block)
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html

    def test_highlight(self, renderer):
        block = SummaryBlock(type="summary", content="text", highlight=True)
        html = renderer._render_summary(block)
        assert "highlight" in html

    def test_with_title(self, renderer):
        block = SummaryBlock(type="summary", title="Summary", content="text")
        html = renderer._render_summary(block)
        assert "Summary" in html


class TestChartBlock:
    def test_render_contains_echarts(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR,
            labels=["a"], series=[ChartDataSeries(name="s", values=[1])],
        )
        html = renderer._render_chart(block)
        assert "echarts.init" in html
        assert "resize" in html

    def test_chart_with_title(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.LINE, title="My Chart",
            labels=["a"], series=[ChartDataSeries(name="s", values=[1])],
        )
        html = renderer._render_chart(block)
        assert "My Chart" in html


class TestBulletListBlock:
    def test_unordered(self, renderer):
        block = BulletListBlock(type="bullet_list", items=["a", "b"])
        html = renderer._render_bullet_list(block)
        assert "<ul" in html
        assert "<li>" in html

    def test_ordered(self, renderer):
        block = BulletListBlock(type="bullet_list", items=["a", "b"], ordered=True)
        html = renderer._render_bullet_list(block)
        assert "<ol" in html

    def test_with_title(self, renderer):
        block = BulletListBlock(
            type="bullet_list", title="My List", items=["x"],
        )
        html = renderer._render_bullet_list(block)
        assert "My List" in html


class TestTableBlock:
    def test_render(self, renderer):
        block = TableBlock(
            type="table", columns=["A", "B"],
            rows=[["1", "2"], ["3", "4"]],
        )
        html = renderer._render_table(block)
        assert "<table" in html
        assert "<th" in html
        assert "<td" in html

    def test_xss_in_cells(self, renderer):
        block = TableBlock(
            type="table", columns=["Col"],
            rows=[["<img src=x onerror=alert(1)>"]],
        )
        html = renderer._render_table(block)
        assert "<img " not in html
        assert "&lt;img" in html


class TestImageBlock:
    def test_render_url(self, renderer):
        block = ImageBlock(
            type="image", url="https://example.com/img.png", alt="test",
        )
        html = renderer._render_image(block)
        assert "example.com/img.png" in html
        assert 'alt="test"' in html

    def test_with_caption(self, renderer):
        block = ImageBlock(
            type="image", url="http://x.com/a.png", alt="a",
            caption="Caption text",
        )
        html = renderer._render_image(block)
        assert "Caption text" in html


class TestQuoteBlock:
    def test_render(self, renderer):
        block = QuoteBlock(type="quote", text="To be or not", author="Shakespeare")
        html = renderer._render_quote(block)
        assert "To be or not" in html
        assert "Shakespeare" in html
        assert "blockquote" in html


class TestCalloutBlock:
    def test_levels(self, renderer):
        for level in CalloutLevel:
            block = CalloutBlock(
                type="callout", level=level,
                title="T", content="C",
            )
            html = renderer._render_callout(block)
            assert level.value in html

    def test_content(self, renderer):
        block = CalloutBlock(
            type="callout", level=CalloutLevel.WARNING,
            title="Warn", content="Be careful",
        )
        html = renderer._render_callout(block)
        assert "Warn" in html
        assert "Be careful" in html


class TestDividerBlock:
    def test_styles(self, renderer):
        for style in ["solid", "dashed", "dotted", "gradient"]:
            block = DividerBlock(type="divider", style=style)
            html = renderer._render_divider(block)
            assert style in html
            assert "<hr" in html


class TestTimelineBlock:
    def test_render(self, renderer):
        block = TimelineBlock(
            type="timeline", title="Timeline",
            events=[
                TimelineEvent(date="2026-01", title="Start", description="Begin"),
                TimelineEvent(date="2026-06", title="End"),
            ],
        )
        html = renderer._render_timeline(block)
        assert "Timeline" in html
        assert "2026-01" in html
        assert "Start" in html
        assert "Begin" in html


class TestProgressBlock:
    def test_render(self, renderer):
        block = ProgressBlock(
            type="progress", title="Progress",
            items=[
                ProgressItem(label="Task A", value=75, color="#10b981"),
                ProgressItem(label="Task B", value=50, target=80),
            ],
        )
        html = renderer._render_progress(block)
        assert "Task A" in html
        assert "75%" in html
        assert "progress-track" in html

    def test_target_marker(self, renderer):
        block = ProgressBlock(
            type="progress",
            items=[ProgressItem(label="X", value=60, target=90)],
        )
        html = renderer._render_progress(block)
        assert "progress-target" in html
        assert "90" in html  # 90.0% or 90%


# ──────────────────────────────────────────────
# ECharts Mapping Tests
# ──────────────────────────────────────────────

class TestEChartsMapping:
    """Tests for _build_echarts_option()."""

    def test_bar_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR, title="Sales",
            labels=["Q1", "Q2"],
            series=[ChartDataSeries(name="Rev", values=[100, 200])],
        )
        option = renderer._build_echarts_option(block)
        assert option["xAxis"]["data"] == ["Q1", "Q2"]
        assert option["series"][0]["type"] == "bar"

    def test_line_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.LINE,
            labels=["a", "b"],
            series=[ChartDataSeries(name="s", values=[1, 2])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "line"

    def test_pie_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.PIE,
            labels=["A", "B"],
            series=[ChartDataSeries(name="Share", values=[60, 40])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "pie"
        assert len(option["series"][0]["data"]) == 2

    def test_donut_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.DONUT,
            labels=["A", "B"],
            series=[ChartDataSeries(name="d", values=[30, 70])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["radius"] == ["40%", "70%"]

    def test_area_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.AREA,
            labels=["a"], series=[ChartDataSeries(name="s", values=[1])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "line"
        assert "areaStyle" in option["series"][0]

    def test_scatter_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.SCATTER,
            labels=["a"], series=[ChartDataSeries(name="s", values=[1])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "scatter"

    def test_radar_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.RADAR,
            labels=["a", "b"],
            series=[ChartDataSeries(name="s", values=[10, 20])],
        )
        option = renderer._build_echarts_option(block)
        assert "radar" in option
        assert option["series"][0]["type"] == "radar"

    def test_gauge_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.GAUGE,
            labels=[], series=[ChartDataSeries(name="Speed", values=[75])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "gauge"

    def test_funnel_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.FUNNEL,
            labels=["Visit", "Click"],
            series=[ChartDataSeries(name="f", values=[100, 50])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "funnel"

    def test_treemap_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.TREEMAP,
            labels=["A", "B"],
            series=[ChartDataSeries(name="t", values=[70, 30])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "treemap"

    def test_heatmap_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.HEATMAP,
            labels=["Mon", "Tue"],
            series=[ChartDataSeries(name="h", values=[5, 10])],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "heatmap"

    def test_waterfall_chart(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.WATERFALL,
            labels=["Start", "Growth", "Loss"],
            series=[ChartDataSeries(name="w", values=[100, 50, -30])],
        )
        option = renderer._build_echarts_option(block)
        assert len(option["series"]) == 2  # invisible base + visible bar

    def test_series_color(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.LINE,
            labels=["a"],
            series=[ChartDataSeries(name="s", values=[1], color="#ff0000")],
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["itemStyle"]["color"] == "#ff0000"

    def test_stacked(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR,
            labels=["a"], stacked=True,
            series=[
                ChartDataSeries(name="s1", values=[1]),
                ChartDataSeries(name="s2", values=[2]),
            ],
        )
        option = renderer._build_echarts_option(block)
        assert all(s.get("stack") == "total" for s in option["series"])

    def test_axis_labels(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR,
            labels=["a"],
            series=[ChartDataSeries(name="s", values=[1])],
            x_axis_label="X Label", y_axis_label="Y Label",
        )
        option = renderer._build_echarts_option(block)
        assert option["xAxis"]["name"] == "X Label"
        assert option["yAxis"]["name"] == "Y Label"

    def test_legend(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR,
            labels=["a"],
            series=[ChartDataSeries(name="Sales", values=[1])],
            show_legend=True,
        )
        option = renderer._build_echarts_option(block)
        assert "legend" in option
        assert "Sales" in option["legend"]["data"]


# ──────────────────────────────────────────────
# Document Structure Tests
# ──────────────────────────────────────────────

class TestDocumentStructure:
    """Tests for the full HTML document output."""

    def test_html5_doctype(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response)
        assert html.startswith("<!DOCTYPE html>")

    def test_html_contains_head_body(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response)
        assert "<head>" in html
        assert "<body>" in html
        assert "</html>" in html

    def test_css_variables(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response, theme="light")
        assert ":root" in html
        assert "--primary:" in html

    def test_responsive_breakpoints(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response)
        assert "@media (max-width: 600px)" in html

    def test_print_styles(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response)
        assert "@media print" in html

    def test_page_title_from_block(self, renderer):
        resp = InfographicResponse(blocks=[
            TitleBlock(type="title", title="My Report"),
        ])
        html = renderer.render_to_html(resp)
        assert "<title>My Report</title>" in html

    def test_page_title_default(self, renderer):
        resp = InfographicResponse(blocks=[
            SummaryBlock(type="summary", content="No title block"),
        ])
        html = renderer.render_to_html(resp)
        assert "<title>Infographic</title>" in html

    def test_echarts_js_included_when_charts_present(self, renderer):
        resp = InfographicResponse(blocks=[
            ChartBlock(
                type="chart", chart_type=ChartType.BAR,
                labels=["a"], series=[ChartDataSeries(name="s", values=[1])],
            ),
        ])
        html = renderer.render_to_html(resp)
        assert "<script>" in html

    def test_echarts_js_not_included_without_charts(self, renderer):
        resp = InfographicResponse(blocks=[
            TitleBlock(type="title", title="No Charts"),
        ])
        html = renderer.render_to_html(resp)
        # Should not include ECharts JS when no charts
        assert "echarts.init" not in html

    def test_dark_theme_css(self, renderer):
        resp = InfographicResponse(
            blocks=[TitleBlock(type="title", title="Dark")],
        )
        html = renderer.render_to_html(resp, theme="dark")
        assert "--neutral-text: #f1f5f9" in html  # light text


# ──────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────

class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_empty_blocks(self, renderer):
        resp = InfographicResponse(blocks=[])
        html = renderer.render_to_html(resp)
        assert "no data" in html.lower()

    def test_render_from_dict(self, renderer, basic_response):
        html = renderer.render_to_html(basic_response.model_dump())
        assert "<!DOCTYPE html>" in html

    def test_unknown_theme_fallback(self, renderer):
        resp = InfographicResponse(
            blocks=[TitleBlock(type="title", title="T")],
        )
        html = renderer.render_to_html(resp, theme="nonexistent")
        assert "<!DOCTYPE html>" in html  # Should not crash

    def test_xss_title(self, renderer):
        resp = InfographicResponse(blocks=[
            TitleBlock(type="title", title='<img src=x onerror="alert(1)">'),
        ])
        html = renderer.render_to_html(resp)
        assert 'onerror="alert(1)"' not in html

    def test_xss_table_cells(self, renderer):
        block = TableBlock(
            type="table", columns=["Col"],
            rows=[['<script>alert("xss")</script>']],
        )
        html = renderer._render_table(block)
        assert "<script>" not in html

    def test_xss_chart_title(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR,
            title='<script>alert(1)</script>',
            labels=["a"],
            series=[ChartDataSeries(name="s", values=[1])],
        )
        html = renderer._render_chart(block)
        assert "<script>alert" not in html

    def test_special_characters(self, renderer):
        block = TitleBlock(type="title", title='Tom & Jerry "Special" <Report>')
        html = renderer._render_title(block)
        assert "&amp;" in html
        assert "&lt;Report&gt;" in html

    def test_hero_card_no_trend(self, renderer):
        block = HeroCardBlock(type="hero_card", label="X", value="1")
        html = renderer._render_hero_card(block)
        assert "kpi-card" in html
        assert "kpi-trend" not in html

    def test_image_block_base64(self, renderer):
        block = ImageBlock(
            type="image", base64="iVBORw0KGgo=", alt="test image",
        )
        html = renderer._render_image(block)
        assert "data:image/png;base64," in html

    def test_quote_no_author(self, renderer):
        block = QuoteBlock(type="quote", text="Some quote")
        html = renderer._render_quote(block)
        assert "Some quote" in html
        assert "attribution" not in html

    def test_callout_no_title(self, renderer):
        block = CalloutBlock(type="callout", content="Just content")
        html = renderer._render_callout(block)
        assert "Just content" in html


# ──────────────────────────────────────────────
# Integration: Full Render
# ──────────────────────────────────────────────

class TestFullIntegration:
    """Integration tests with all 12 block types."""

    def test_full_render_produces_valid_html(self, renderer, full_infographic_response):
        html = renderer.render_to_html(full_infographic_response)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        # Verify key content from each block type
        assert "Full Test Report" in html  # title
        assert "kpi-grid" in html  # hero cards grouped
        assert "Executive Summary" in html  # summary
        assert "gradient" in html  # divider
        assert "echarts.init" in html  # charts
        assert "<table" in html  # table
        assert "<ol" in html  # ordered list
        assert "Milestone" in html  # callout
        assert "example.com/chart.png" in html  # image
        assert "Innovation" in html  # quote
        assert "Phase 1" in html  # timeline
        assert "Revenue Target" in html  # progress

    def test_render_to_html_standalone(self, renderer, basic_response):
        """render_to_html works outside renderer pipeline."""
        html = renderer.render_to_html(basic_response)
        assert isinstance(html, str)
        assert len(html) > 100

    def test_theme_applies(self, renderer, basic_response):
        for theme_name in ["light", "dark", "corporate"]:
            html = renderer.render_to_html(basic_response, theme=theme_name)
            assert ":root" in html
            # Each theme has different primary
            theme = theme_registry.get(theme_name)
            assert f"--primary: {theme.primary}" in html


# ──────────────────────────────────────────────
# Content Negotiation Tests
# ──────────────────────────────────────────────

class TestContentNegotiation:
    """Test content negotiation wiring in get_infographic().

    These test the structural wiring without requiring a live LLM.
    """

    def test_renderer_accepts_dict(self, renderer):
        """InfographicHTMLRenderer.render_to_html accepts raw dict."""
        data = {
            "blocks": [
                {"type": "title", "title": "Test"},
                {"type": "summary", "content": "Hello"},
            ]
        }
        html = renderer.render_to_html(data)
        assert "<!DOCTYPE html>" in html
        assert "Test" in html

    def test_renderer_preserves_structured_output(self, renderer, basic_response):
        """HTML rendering does not modify the InfographicResponse object."""
        original_blocks = len(basic_response.blocks)
        renderer.render_to_html(basic_response)
        assert len(basic_response.blocks) == original_blocks
