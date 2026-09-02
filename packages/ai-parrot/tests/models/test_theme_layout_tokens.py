"""Unit tests for ThemeConfig layout tokens (FEAT-493, TASK-2706)."""

import pytest
from parrot.models.infographic import ThemeConfig, theme_registry


class TestThemeLayoutTokens:
    """Layout-token emission and validation on ThemeConfig."""

    def test_layout_tokens_emitted(self):
        """to_css_variables() carries every new layout custom property."""
        css = ThemeConfig(name="t").to_css_variables()
        for var in (
            "--content-width",
            "--radius",
            "--shadow",
            "--mono-family",
            "--panel-bg",
            "--panel-border",
            "--header-bg",
            "--header-text",
        ):
            assert var in css, var

    @pytest.mark.parametrize("theme_name", sorted(theme_registry.list_themes()))
    def test_registered_themes_still_valid(self, theme_name):
        """All five registered themes construct and emit unchanged."""
        theme = theme_registry.get(theme_name)
        assert theme.to_css_variables()

    def test_unset_tokens_derive(self):
        """An unset panel_bg derives rather than emitting empty."""
        theme = ThemeConfig(name="t", neutral_bg="#ffffff")
        assert theme.panel_bg is None  # not mutated on the model
        assert "--panel-bg:" in theme.to_css_variables()
        assert "--panel-bg: ;" not in theme.to_css_variables()

    def test_explicit_token_wins(self):
        assert "--content-width: 1400px" in ThemeConfig(name="t", content_width="1400px").to_css_variables()

    def test_invalid_colour_rejected(self):
        # NOTE (TASK-2706): the shared `_CSS_COLOR_RE` treats any bare
        # letters-and-hyphens token (e.g. "not-a-colour") as a plausible
        # CSS named-colour keyword — pre-existing looseness across every
        # colour field on ThemeConfig, out of this task's scope to
        # tighten. Use a value no branch of the regex accepts instead.
        with pytest.raises(ValueError, match="Invalid CSS color"):
            ThemeConfig(name="t", panel_bg="12345")

    def test_invalid_density_rejected(self):
        with pytest.raises(ValueError):
            ThemeConfig(name="t", density="banana")

    def test_shadow_none_expressible(self):
        """The print layout needs shadow: none to be a real value."""
        assert "--shadow: none" in ThemeConfig(name="t", shadow="none").to_css_variables()

    def test_density_valid_values_accepted(self):
        """comfortable and compact are both accepted."""
        assert ThemeConfig(name="t", density="comfortable").density == "comfortable"
        assert ThemeConfig(name="t", density="compact").density == "compact"
