"""Tests for placeholder templating and loop bounds enforcement."""
import pytest

from parrot_tools.browsing.models import ActionParam
from parrot_tools.browsing.templating import (
    collect_placeholders,
    collect_value_placeholders,
    find_literal_credentials,
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

    def test_value_name_scoped_to_its_loop_subtree(self):
        # "row" is a loop value_name INSIDE the loop, but it is also used
        # as a placeholder OUTSIDE the loop — that outer use is a real
        # undeclared parameter and must be reported.
        steps = [
            {
                "action": "loop",
                "values": ["a"],
                "value_name": "row",
                "actions": [
                    {"action": "fill", "selector": "#f", "value": "{{row}}"}
                ],
            },
            {"action": "fill", "selector": "#g", "value": "{{row}}"},
        ]
        assert collect_placeholders(steps) == {"row"}


class TestCollectValuePlaceholders:
    def test_nested_values(self):
        params = {"customer": "{{customer}}", "meta": {"x": ["{{other}}"]}}
        assert collect_value_placeholders(params) == {"customer", "other"}


class TestFindLiteralCredentials:
    def test_flags_literal_password(self):
        steps = [{"action": "authenticate", "password": "secret123"}]
        warnings = find_literal_credentials(steps)
        assert len(warnings) == 1
        assert "secret123" not in warnings[0]

    def test_flags_nested_authenticate(self):
        steps = [
            {
                "action": "loop",
                "iterations": 1,
                "actions": [
                    {"action": "authenticate", "password": "secret123"}
                ],
            }
        ]
        assert len(find_literal_credentials(steps)) == 1

    def test_broker_based_auth_is_clean(self):
        steps = [
            {"action": "authenticate", "credential_provider": "hooba"}
        ]
        assert find_literal_credentials(steps) == []


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

    def test_strict_rejects_non_positive_cap(self):
        steps = [
            {"action": "loop", "iterations": 1, "max_iterations": 0,
             "actions": []}
        ]
        with pytest.raises(ValueError, match="must be >= 1"):
            validate_loop_bounds(steps, 50, strict=True)

    def test_non_strict_clamps_non_positive_cap_to_one(self):
        steps = [
            {"action": "loop", "iterations": 1, "max_iterations": -3,
             "actions": []}
        ]
        out = validate_loop_bounds(steps, 50, strict=False)
        assert out[0]["max_iterations"] == 1

    def test_author_supplied_tighter_cap_is_kept(self):
        steps = [
            {"action": "loop", "iterations": 2, "max_iterations": 5,
             "actions": []}
        ]
        out = validate_loop_bounds(steps, 50, strict=True)
        assert out[0]["max_iterations"] == 5

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
