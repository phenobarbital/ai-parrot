"""Layout/composer migration tests for InfographicHTMLRenderer (FEAT-493, TASK-2712)."""

import pytest
from parrot.models.infographic import theme_registry
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


def _resp(**overrides):
    payload = {
        "blocks": [
            {"type": "title", "title": "Q3 Report"},
            {"type": "hero_card", "label": "Revenue", "value": "$1.2M"},
        ],
    }
    payload.update(overrides)
    return payload


class TestInfographicLayouts:
    def test_default_layout_is_analytics(self):
        html = InfographicHTMLRenderer().render_to_html(_resp())
        assert 'data-layout="analytics"' in html

    def test_report_layout_still_reachable(self):
        html = InfographicHTMLRenderer().render_to_html(_resp(), layout="report")
        assert 'data-layout="report"' in html

    def test_unknown_layout_falls_back_to_analytics(self):
        html = InfographicHTMLRenderer().render_to_html(_resp(), layout="bogus")
        assert 'data-layout="analytics"' in html

    def test_unknown_layout_logs_a_warning(self, caplog):
        """Code review, FEAT-493: unknown-theme handling logged a warning two
        lines above this call site; unknown-layout silently fell back with
        no log at all. Both axes must warn-and-fall-back identically."""
        with caplog.at_level("WARNING"):
            InfographicHTMLRenderer().render_to_html(_resp(), layout="bogus")
        assert any("bogus" in record.message for record in caplog.records)

    def test_wrapper_carries_both_classes(self):
        """ds-page for the new layouts, container for report parity."""
        html = InfographicHTMLRenderer().render_to_html(_resp())
        assert 'class="ds-page container"' in html
        assert 'data-theme="light"' in html

    def test_no_base_css_constant(self):
        import parrot.outputs.formats.infographic_html as m

        assert not hasattr(m, "BASE_CSS")

    def test_theme_cfg_still_populated(self):
        renderer = InfographicHTMLRenderer()
        renderer.render_to_html(_resp(), theme="dark")
        assert renderer._theme_cfg is theme_registry.get("dark")

    def test_self_contained_no_import_no_external_link(self):
        html = InfographicHTMLRenderer().render_to_html(_resp(), layout="report")
        assert "@import" not in html
        assert "<link" not in html

    @pytest.mark.parametrize(
        "block_selector",
        [
            ".kpi-grid",
            ".kpi-card",
            ".chart-container",
            ".table-container",
            ".summary-block",
            ".bullet-list-block",
            ".image-block",
            "blockquote.quote-block",
            ".callout-block.info",
            ".callout-block.success",
            ".callout-block.warning",
            ".callout-block.error",
            ".callout-block.tip",
            "hr.divider",
            ".timeline-block",
            ".progress-block",
            ".empty-message",
            "footer.infographic-footer",
        ],
    )
    def test_every_block_selector_present(self, block_selector):
        """Every legacy block selector is reachable in the `report` layout's
        composed sheet — the layout that reproduces this renderer's
        previous appearance 1:1 (spec: "report reproduces the previous
        appearance")."""
        html = InfographicHTMLRenderer().render_to_html(_resp(), layout="report")
        assert block_selector in html
