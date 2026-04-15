"""Unit tests for parrot.helpers.infographics façade functions."""
import pytest
from pydantic import ValidationError

from parrot.helpers.infographics import (
    get_template,
    get_theme,
    list_templates,
    list_themes,
    register_template,
    register_theme,
)
from parrot.models.infographic import ThemeConfig, theme_registry
from parrot.models.infographic_templates import (
    InfographicTemplate,
    infographic_registry,
)


@pytest.fixture
def cleanup_registries():
    """Remove test-registered templates/themes after each test."""
    yield
    for name in list(infographic_registry._templates.keys()):
        if name.startswith("test_"):
            del infographic_registry._templates[name]
    for name in list(theme_registry._themes.keys()):
        if name.startswith("test_"):
            del theme_registry._themes[name]


class TestListTemplates:
    def test_returns_sorted_names(self):
        names = list_templates()
        assert isinstance(names, list)
        assert names == sorted(names)
        assert "basic" in names

    def test_detailed_returns_dicts(self):
        detailed = list_templates(detailed=True)
        assert all("name" in d and "description" in d for d in detailed)

    def test_returns_all_builtins(self):
        names = list_templates()
        for expected in ["basic", "executive", "dashboard", "comparison", "timeline", "minimal"]:
            assert expected in names


class TestGetTemplate:
    def test_known_template(self):
        tpl = get_template("basic")
        assert isinstance(tpl, InfographicTemplate)
        assert tpl.name == "basic"

    def test_unknown_raises_keyerror(self):
        with pytest.raises(KeyError, match="not found"):
            get_template("does_not_exist")


class TestRegisterTemplate:
    def test_accepts_model_instance(self, cleanup_registries):
        tpl = InfographicTemplate(
            name="test_custom",
            description="Test template",
            block_specs=[],
        )
        out = register_template(tpl)
        assert out is tpl
        assert get_template("test_custom") is tpl

    def test_accepts_dict(self, cleanup_registries):
        out = register_template({
            "name": "test_custom_dict",
            "description": "From dict",
            "block_specs": [],
        })
        assert isinstance(out, InfographicTemplate)
        assert out.name == "test_custom_dict"

    def test_invalid_dict_raises_validation_error(self):
        with pytest.raises(ValidationError):
            register_template({"name": "test_bad"})  # missing description + block_specs


class TestListThemes:
    def test_returns_builtins(self):
        names = list_themes()
        assert set(["light", "dark", "corporate"]).issubset(set(names))

    def test_detailed_shape(self):
        detailed = list_themes(detailed=True)
        for entry in detailed:
            assert set(entry.keys()) == {"name", "primary", "neutral_bg", "body_bg"}


class TestThemeRegistryListDetailed:
    def test_method_exists_on_registry(self):
        assert hasattr(theme_registry, "list_themes_detailed")
        detailed = theme_registry.list_themes_detailed()
        assert isinstance(detailed, list)
        assert all("name" in d for d in detailed)

    def test_returns_three_builtins(self):
        detailed = theme_registry.list_themes_detailed()
        names = [d["name"] for d in detailed]
        assert "light" in names
        assert "dark" in names
        assert "corporate" in names


class TestRegisterTheme:
    def test_accepts_model(self, cleanup_registries):
        theme = ThemeConfig(name="test_sunset", primary="#ff6b35")
        out = register_theme(theme)
        assert out is theme
        assert get_theme("test_sunset") is theme

    def test_accepts_dict(self, cleanup_registries):
        out = register_theme({"name": "test_dict_theme"})
        assert isinstance(out, ThemeConfig)
        assert out.name == "test_dict_theme"
        assert out.primary == "#6366f1"  # default


class TestGetTheme:
    def test_known(self):
        t = get_theme("light")
        assert isinstance(t, ThemeConfig)

    def test_unknown_raises(self):
        with pytest.raises(KeyError):
            get_theme("no_such_theme")
