"""Tests for browsing catalog models (SiteInfo / SiteAction)."""
import pytest

from parrot_tools.browsing.models import (
    ActionParam,
    ComposedRef,
    SiteAction,
    SiteInfo,
    slugify,
)


class TestSlugify:
    def test_basic(self):
        assert slugify("Hooba.es") == "hooba-es"

    def test_collapses_separators(self):
        assert slugify("Create   Invoice__Draft!") == "create-invoice-draft"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            slugify("///")


class TestSiteInfo:
    def test_slug_derived_from_domain(self):
        info = SiteInfo(base_url="https://app.hooba.es/portal")
        assert info.site == "app-hooba-es"
        assert info.domain == "app.hooba.es"

    def test_matches_alias_and_domain(self):
        info = SiteInfo(
            base_url="https://www.hooba.es",
            title="Hooba",
            aliases=["hooba"],
        )
        assert info.matches("hooba")
        assert info.matches("Hooba")
        assert info.matches("hooba.es")  # www-stripped domain
        assert info.matches("www.hooba.es")
        assert not info.matches("otrosite")


class TestSiteAction:
    def test_operation_requires_steps(self):
        with pytest.raises(ValueError, match="non-empty 'steps'"):
            SiteAction(name="login", description="x", kind="operation")

    def test_composite_requires_compose(self):
        with pytest.raises(ValueError, match="non-empty 'compose'"):
            SiteAction(name="flow", description="x", kind="composite")

    def test_composite_rejects_steps(self):
        with pytest.raises(ValueError, match="must not carry 'steps'"):
            SiteAction(
                name="flow",
                description="x",
                kind="composite",
                compose=[ComposedRef(action="login")],
                steps=[{"action": "navigate", "url": "https://x"}],
            )

    def test_operation_rejects_compose(self):
        with pytest.raises(ValueError, match="must not carry 'compose'"):
            SiteAction(
                name="op",
                description="x",
                kind="operation",
                steps=[{"action": "navigate", "url": "https://x"}],
                compose=[ComposedRef(action="login")],
            )

    def test_reserved_param_names_rejected(self):
        with pytest.raises(ValueError, match="reserved"):
            SiteAction(
                name="op",
                description="x",
                steps=[{"action": "navigate", "url": "https://x"}],
                params={"index": ActionParam(description="clash")},
            )

    def test_validate_steps_accepts_dsl(self):
        action = SiteAction(
            name="login",
            description="Log in",
            steps=[
                {"action": "navigate", "url": "https://hooba.es/login"},
                {"action": "fill", "selector": "#user", "value": "{{username}}"},
                {"action": "click", "selector": "#submit"},
            ],
            params={"username": ActionParam(description="User")},
        )
        action.validate_steps()  # must not raise

    def test_validate_steps_rejects_unknown_action(self):
        action = SiteAction(
            name="bad",
            description="x",
            steps=[{"action": "teleport", "url": "https://x"}],
        )
        with pytest.raises(ValueError, match="invalid step"):
            action.validate_steps()

    def test_names_are_slugified(self):
        action = SiteAction(
            name="Create Invoice Draft",
            description="x",
            steps=[{"action": "navigate", "url": "https://x"}],
            requires=["Log In"],
        )
        assert action.name == "create-invoice-draft"
        assert action.requires == ["log-in"]

    def test_summary_shape(self):
        action = SiteAction(
            name="login",
            description="Log in to the site",
            steps=[{"action": "navigate", "url": "https://x"}],
            params={"username": ActionParam(description="User", example="ana")},
            requires=[],
        )
        summary = action.summary()
        assert summary["name"] == "login"
        assert summary["kind"] == "operation"
        assert summary["params"]["username"]["example"] == "ana"
