"""Tests for placeholder templating and loop bounds enforcement."""
import pytest

from parrot_tools.browsing.models import ActionParam
from parrot_tools.browsing.templating import (
    collect_placeholders,
    render_steps,
    render_value,
    resolve_params,
    validate_loop_bounds,
)


class TestResolveParams:
    def test_defaults_and_provided(self):
        declared = {
            "customer": ActionParam(description="x"),
            "currency": ActionParam(description="x", default="EUR"),
        }
        out = resolve_params(declared, {"customer": "ACME"})
        assert out == {"customer": "ACME", "currency": "EUR"}

    def test_missing_required_raises(self):
        declared = {"customer": ActionParam(description="x")}
        with pytest.raises(ValueError, match="customer"):
            resolve_params(declared, {})

    def test_optional_without_default_is_none(self):
        declared = {"note": ActionParam(description="x", required=False)}
        assert resolve_params(declared, {}) == {"note": None}

    def test_extra_provided_kept(self):
        out = resolve_params({}, {"extra": 1})
        assert out == {"extra": 1}


class TestRenderValue:
    def test_interpolation(self):
        assert render_value("Hola {{name}}!", {"name": "Ana"}) == "Hola Ana!"

    def test_exact_placeholder_preserves_type(self):
        assert render_value("{{items}}", {"items": [1, 2]}) == [1, 2]

    def test_unknown_placeholder_untouched(self):
        assert render_value("row {{index}}", {"name": "x"}) == "row {{index}}"

    def test_nested_structures(self):
        steps = [{"action": "fill", "value": "{{q}}", "meta": {"k": "{{q}}"}}]
        out = render_steps(steps, {"q": "abc"})
        assert out[0]["value"] == "abc"
        assert out[0]["meta"]["k"] == "abc"
        # Original untouched
        assert steps[0]["value"] == "{{q}}"


class TestCollectPlaceholders:
    def test_finds_names(self):
        steps = [
            {"action": "fill", "selector": "#u", "value": "{{username}}"},
            {"action": "fill", "selector": "#p", "value": "{{password}}"},
        ]
        assert collect_placeholders(steps) == {"username", "password"}

    def test_excludes_loop_reserved_and_value_name(self):
        steps = [
            {
                "action": "loop",
                "values": ["a", "b"],
                "value_name": "row",
                "actions": [
                    {"action": "fill", "selector": "#f{{index}}", "value": "{{row}}"},
                    {"action": "fill", "selector": "#g", "value": "{{city}}"},
                ],
            }
        ]
        assert collect_placeholders(steps) == {"city"}


class TestValidateLoopBounds:
    def test_strict_rejects_excess_iterations(self):
        steps = [{"action": "loop", "iterations": 500, "actions": []}]
        with pytest.raises(ValueError, match="exceeds"):
            validate_loop_bounds(steps, 50, strict=True)

    def test_strict_caps_missing_max_iterations(self):
        steps = [{"action": "loop", "iterations": 3, "actions": []}]
        out = validate_loop_bounds(steps, 50, strict=True)
        assert out[0]["max_iterations"] == 50

    def test_non_strict_clamps(self):
        steps = [
            {
                "action": "loop",
                "iterations": 500,
                "values": list(range(200)),
                "max_iterations": 1000,
                "actions": [],
            }
        ]
        out = validate_loop_bounds(steps, 50, strict=False)
        assert out[0]["iterations"] == 50
        assert len(out[0]["values"]) == 50
        assert out[0]["max_iterations"] == 50
        # Original untouched
        assert steps[0]["iterations"] == 500

    def test_nested_loops_checked(self):
        steps = [
            {
                "action": "conditional",
                "expected_value": "yes",
                "actions_if_true": [
                    {"action": "loop", "iterations": 999, "actions": []}
                ],
            }
        ]
        with pytest.raises(ValueError, match="actions_if_true"):
            validate_loop_bounds(steps, 50, strict=True)
