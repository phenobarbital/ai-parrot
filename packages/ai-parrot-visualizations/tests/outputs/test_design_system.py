"""Unit tests for the design-system composer (FEAT-493, TASK-2707)."""

import pytest
from parrot.models.infographic import theme_registry
from parrot.outputs.formats.assets.design_system import DesignSystem


class TestDesignSystem:
    def test_composes_default_pair(self):
        css = DesignSystem.stylesheet("light", "analytics")
        assert css.strip()
        assert "--content-width" in css  # tokens present
        assert ".kpi-card" in css  # components present
        assert ".ds-page" in css  # shell present

    def test_assets_packaged_and_non_empty(self):
        """Catches a package-data regression: every asset must load with content."""
        for layout in ("analytics",):
            assert len(DesignSystem.stylesheet("light", layout)) > 500

    def test_stylesheet_cached_per_pair(self):
        a = DesignSystem.stylesheet("light", "analytics")
        b = DesignSystem.stylesheet("light", "analytics")
        assert a is b

    def test_unknown_theme_falls_back_with_warning(self, caplog):
        with caplog.at_level("WARNING"):
            css = DesignSystem.stylesheet("no-such-theme", "analytics")
        assert css.strip()
        assert any("no-such-theme" in r.message for r in caplog.records)

    def test_unknown_layout_falls_back_with_warning(self, caplog):
        with caplog.at_level("WARNING"):
            css = DesignSystem.stylesheet("light", "no-such-layout")
        assert css.strip()
        assert caplog.records

    def test_layouts_disjoint_from_theme_names(self):
        """'corporate' is a THEME; layout names must never collide with themes."""
        assert not DesignSystem.LAYOUTS & set(theme_registry.list_themes())

    def test_no_external_references(self):
        css = DesignSystem.stylesheet("light", "analytics")
        assert "@import" not in css
        assert "url(http" not in css

    @pytest.mark.parametrize("theme", sorted(theme_registry.list_themes()))
    def test_every_theme_composes(self, theme):
        assert DesignSystem.stylesheet(theme, "analytics").strip()
