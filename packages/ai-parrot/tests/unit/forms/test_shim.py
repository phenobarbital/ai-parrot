"""Unit tests for the parrot.forms re-export shim (FEAT-393 TASK-2007).

The local fallback copies were removed — parrot.forms now re-exports
parrot_formdesigner.* directly, with a clear ImportError if that package
is absent. These tests verify identity (the shim yields the REAL classes,
not stale local duplicates) and that the public symbol surface is
unchanged from before this task.
"""

from __future__ import annotations

import parrot.forms as shim

# The exact symbol list re-exported by parrot.forms BEFORE this task
# (captured from the try-branch of the prior try/except shim) — must be
# unchanged after removing the fallback branch.
_EXPECTED_SYMBOLS = {
    "ApiKeyAuth",
    "AuthConfig",
    "BearerAuth",
    "ConditionOperator",
    "DependencyOperation",
    "DependencyRule",
    "FieldCondition",
    "FieldConstraints",
    "FieldOption",
    "FieldSizeHint",
    "FieldStyleHint",
    "FieldType",
    "FormField",
    "FormSchema",
    "FormSection",
    "FormStyle",
    "FormSubsection",
    "LayoutType",
    "LocalizedString",
    "NoAuth",
    "OptionsSource",
    "PostDependency",
    "RenderedForm",
    "SectionItem",
    "StyleSchema",
    "SubmitAction",
    "JSONSchemaExtractor",
    "PydanticExtractor",
    "ToolExtractor",
    "YAMLExtractor",
    "AdaptiveCardRenderer",
    "HTML5Renderer",
    "JsonSchemaRenderer",
    "FormCache",
    "ForwardResult",
    "FormRegistry",
    "FormStorage",
    "FormSubmission",
    "FormSubmissionStorage",
    "FormValidator",
    "PostgresFormStorage",
    "RuleEvaluator",
    "RuleResolution",
    "SubmissionForwarder",
    "ValidationResult",
    "CreateFormTool",
    "DatabaseFormTool",
    "RequestFormTool",
    "get_dependency_rule_snippets",
    "get_form_field_schema_snippets",
    "list_supported_form_field_types",
}


def test_shim_reexports_formdesigner_classes() -> None:
    """from parrot.forms import FormField yields the REAL parrot_formdesigner class."""
    from parrot.forms import FormField
    from parrot_formdesigner.core.schema import FormField as Real

    assert FormField is Real


def test_shim_reexports_are_identical_objects() -> None:
    """A representative symbol from each re-exported submodule is the same
    object as its parrot_formdesigner source — not a stale local copy."""
    import parrot_formdesigner.core as core
    import parrot_formdesigner.extractors as extractors
    import parrot_formdesigner.renderers as renderers
    import parrot_formdesigner.services as services
    import parrot_formdesigner.tools as tools

    assert shim.FormSchema is core.FormSchema
    assert shim.FieldType is core.FieldType
    assert shim.YAMLExtractor is extractors.YAMLExtractor
    assert shim.HTML5Renderer is renderers.HTML5Renderer
    assert shim.FormRegistry is services.FormRegistry
    assert shim.CreateFormTool is tools.CreateFormTool


def test_shim_symbol_surface_unchanged() -> None:
    """The public symbol surface of parrot.forms is unchanged by removing
    the legacy fallback branch (same names as the prior try-branch)."""
    actual = {name for name in dir(shim) if not name.startswith("_")}
    assert _EXPECTED_SYMBOLS <= actual
