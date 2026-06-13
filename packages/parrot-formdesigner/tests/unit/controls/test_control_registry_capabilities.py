"""Tests for FEAT-234 TASK-1529: FieldControlMetadata capability fields and rule snippets."""

import pytest

from parrot_formdesigner.controls import (
    FieldControlMetadata,
    get_controls,
    register_field_control,
)
from parrot_formdesigner.core import DependencyRule, PostDependency
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools import get_dependency_rule_snippets


# ---------------------------------------------------------------------------
# FieldControlMetadata model-level tests
# ---------------------------------------------------------------------------


class TestFieldControlMetadataModel:
    def test_capability_fields_default_to_empty_list(self) -> None:
        """FieldControlMetadata with no capability fields still validates."""
        meta = FieldControlMetadata(
            type="custom_type",
            label="Custom",
            description="A custom control",
            category="advanced",
            icon="custom",
            snippet={},
            render_hint="input",
            supports_constraints=False,
        )
        assert meta.supported_operators == []
        assert meta.supported_effects == []
        assert meta.supported_operations == []

    def test_capability_fields_accept_string_lists(self) -> None:
        """Capability fields accept arbitrary string lists."""
        meta = FieldControlMetadata(
            type="my_type",
            label="My Type",
            description="desc",
            category="basic",
            icon="icon",
            snippet={},
            render_hint="input",
            supports_constraints=True,
            supported_operators=["eq", "neq"],
            supported_effects=["show", "hide"],
            supported_operations=["copy"],
        )
        assert "eq" in meta.supported_operators
        assert "show" in meta.supported_effects
        assert "copy" in meta.supported_operations

    def test_extra_fields_still_forbidden(self) -> None:
        """extra='forbid' still applies — unknown keys raise a ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FieldControlMetadata(
                type="x",
                label="x",
                description="x",
                category="basic",
                icon="x",
                snippet={},
                render_hint="input",
                supports_constraints=False,
                not_a_real_field="boom",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# register_field_control signature tests
# ---------------------------------------------------------------------------


class TestRegisterFieldControlSignature:
    def test_register_without_capability_fields_still_works(self) -> None:
        """register_field_control backward-compatible — no capability kwargs needed."""
        register_field_control(
            "compat_test",
            label="Compat Test",
            description="Should work without capability fields",
            category="advanced",
            icon="compat",
            snippet={},
            render_hint="input",
            supports_constraints=False,
        )
        controls = {c.type: c for c in get_controls()}
        assert "compat_test" in controls
        assert controls["compat_test"].supported_operators == []

    def test_register_with_capability_fields(self) -> None:
        """register_field_control accepts and stores capability fields."""
        register_field_control(
            "cap_test",
            label="Cap Test",
            description="With capability metadata",
            category="basic",
            icon="cap",
            snippet={},
            render_hint="input",
            supports_constraints=True,
            supported_operators=["eq", "gt"],
            supported_effects=["show"],
            supported_operations=["add"],
        )
        controls = {c.type: c for c in get_controls()}
        assert "cap_test" in controls
        assert controls["cap_test"].supported_operators == ["eq", "gt"]
        assert controls["cap_test"].supported_effects == ["show"]
        assert controls["cap_test"].supported_operations == ["add"]


# ---------------------------------------------------------------------------
# Built-in control capability tests
# ---------------------------------------------------------------------------


class TestBuiltinControlCapabilities:
    """All built-in FieldType controls are seeded in controls/builtin.py on import."""

    @pytest.fixture(autouse=True)
    def _import_builtin(self) -> None:  # noqa: PT004
        """Ensure builtin controls are seeded."""
        import parrot_formdesigner.controls.builtin  # noqa: F401

    def _get_by_type(self, field_type: FieldType) -> FieldControlMetadata:
        controls = {c.type: c for c in get_controls()}
        return controls[field_type.value]

    def test_all_builtin_controls_present(self) -> None:
        """Every FieldType value has a registered control."""
        registered = {c.type for c in get_controls()}
        for ft in FieldType:
            assert ft.value in registered, f"Missing control for FieldType.{ft.name}"

    def test_metadata_has_lists_not_none(self) -> None:
        """Capability fields are always lists (never None) for built-in controls."""
        for control in get_controls():
            assert isinstance(control.supported_operators, list), (
                f"{control.type}.supported_operators should be a list"
            )
            assert isinstance(control.supported_effects, list), (
                f"{control.type}.supported_effects should be a list"
            )
            assert isinstance(control.supported_operations, list), (
                f"{control.type}.supported_operations should be a list"
            )

    def test_numeric_control_has_arithmetic_operations(self) -> None:
        """NUMBER and INTEGER advertise arithmetic operations."""
        for ft in (FieldType.NUMBER, FieldType.INTEGER):
            meta = self._get_by_type(ft)
            arithmetic = {"add", "subtract", "multiply", "divide", "percent"}
            assert arithmetic.issubset(set(meta.supported_operations)), (
                f"{ft.value} should support arithmetic ops; got {meta.supported_operations}"
            )

    def test_numeric_control_has_comparison_operators(self) -> None:
        """NUMBER and INTEGER advertise gt/lt/gte/lte operators."""
        for ft in (FieldType.NUMBER, FieldType.INTEGER):
            meta = self._get_by_type(ft)
            assert "gt" in meta.supported_operators
            assert "lt" in meta.supported_operators
            assert "gte" in meta.supported_operators
            assert "lte" in meta.supported_operators

    def test_text_control_has_string_operations(self) -> None:
        """TEXT and TEXT_AREA advertise string operations (concat, format)."""
        for ft in (FieldType.TEXT, FieldType.TEXT_AREA):
            meta = self._get_by_type(ft)
            assert "concat" in meta.supported_operations or "format" in meta.supported_operations

    def test_text_control_does_not_have_arithmetic(self) -> None:
        """TEXT controls should NOT advertise arithmetic ops."""
        meta = self._get_by_type(FieldType.TEXT)
        arithmetic = {"add", "subtract", "multiply", "divide"}
        assert arithmetic.isdisjoint(set(meta.supported_operations)), (
            f"TEXT should not support arithmetic; got {meta.supported_operations}"
        )

    def test_container_controls_have_limited_effects(self) -> None:
        """GROUP and ARRAY containers only support show/hide effects."""
        for ft in (FieldType.GROUP, FieldType.ARRAY):
            meta = self._get_by_type(ft)
            assert "show" in meta.supported_effects
            assert "hide" in meta.supported_effects
            # Containers should NOT support require/disable/set etc.
            assert "require" not in meta.supported_effects
            assert "calc" not in meta.supported_effects

    def test_select_control_supports_reload_options(self) -> None:
        """SELECT supports reload_options effect."""
        meta = self._get_by_type(FieldType.SELECT)
        assert "reload_options" in meta.supported_operations or (
            "reload_options" in meta.supported_effects
        )

    def test_nps_likert_ranking_are_numeric(self) -> None:
        """Rating scale fields (NPS, LIKERT, RANKING) have numeric operators."""
        for ft in (FieldType.NPS, FieldType.LIKERT, FieldType.RANKING):
            meta = self._get_by_type(ft)
            assert "gt" in meta.supported_operators
            assert "add" in meta.supported_operations


# ---------------------------------------------------------------------------
# get_dependency_rule_snippets tests
# ---------------------------------------------------------------------------


class TestGetDependencyRuleSnippets:
    def test_returns_dict_with_expected_keys(self) -> None:
        snippets = get_dependency_rule_snippets()
        assert "depends_on" in snippets
        assert "post_depends" in snippets

    def test_depends_on_skeleton_constructs_valid_model(self) -> None:
        """The depends_on skeleton can bootstrap a real DependencyRule after substitution."""
        skel = get_dependency_rule_snippets()["depends_on"]
        # Replace placeholder values with real ones
        skel["conditions"][0]["field_id"] = "f1"
        skel["conditions"][0]["value"] = "yes"
        rule = DependencyRule(**skel)
        assert rule.logic == "and"
        assert rule.effect == "show"
        assert len(rule.conditions) == 1

    def test_post_depends_skeleton_show_constructs_valid_model(self) -> None:
        """The 'show' post_depends skeleton constructs a valid PostDependency."""
        show_skel = get_dependency_rule_snippets()["post_depends"][0]
        show_skel["target"] = "f2"
        show_skel["conditions"][0]["field_id"] = "f1"
        show_skel["conditions"][0]["value"] = "yes"
        post = PostDependency(**show_skel)
        assert post.effect == "show"
        assert post.target == "f2"

    def test_post_depends_skeleton_calc_constructs_valid_model(self) -> None:
        """The 'calc' post_depends skeleton constructs a valid PostDependency."""
        calc_skel = get_dependency_rule_snippets()["post_depends"][2]
        calc_skel["target"] = "total"
        calc_skel["operation"]["operands"] = ["price", "qty"]
        calc_skel["operation"]["target"] = "total"
        post = PostDependency(**calc_skel)
        assert post.effect == "calc"
        assert post.operation is not None
        assert post.operation.op == "add"

    def test_post_depends_cascade_clear_constructs_valid_model(self) -> None:
        """The 'cascade_clear' skeleton constructs a valid PostDependency."""
        skel = get_dependency_rule_snippets()["post_depends"][3]
        skel["target"] = "dependent_field"
        post = PostDependency(**skel)
        assert post.effect == "cascade_clear"

    def test_get_dependency_rule_snippets_returns_deep_copy(self) -> None:
        """Mutating one call's result does not affect subsequent calls."""
        s1 = get_dependency_rule_snippets()
        s1["depends_on"]["logic"] = "xor"
        s2 = get_dependency_rule_snippets()
        assert s2["depends_on"]["logic"] == "and"

    def test_post_depends_has_four_entries(self) -> None:
        """Exactly 4 skeletons are provided in post_depends."""
        snippets = get_dependency_rule_snippets()
        assert len(snippets["post_depends"]) == 4
