"""Universal Form Abstraction Layer — thin re-export of parrot-formdesigner.

This module is a backward-compatible re-export shim. All form functionality
lives in the `parrot-formdesigner` package (parrot_formdesigner.*).

Existing imports from parrot.forms continue to work unchanged, as long as
`parrot-formdesigner` is installed.

FEAT-393 (TASK-2007): the local fallback copies (drifted duplicates of the
real parrot_formdesigner modules — e.g. the legacy FormField had no
post_depends, the legacy FormSchema was missing 8+ fields and
RenderWarning entirely) have been REMOVED. `parrot-formdesigner` is now a
hard dependency of this shim: if it is not installed, importing
`parrot.forms` raises a clear `ImportError` instead of silently falling
back to stale, superseded definitions.
"""

try:
    from parrot_formdesigner.core import (  # noqa: F401
        ApiKeyAuth,
        AuthConfig,
        BearerAuth,
        ConditionOperator,
        DependencyOperation,
        DependencyRule,
        FieldCondition,
        FieldConstraints,
        FieldOption,
        FieldSizeHint,
        FieldStyleHint,
        FieldType,
        FormField,
        FormSchema,
        FormSection,
        FormStyle,
        FormSubsection,
        LayoutType,
        LocalizedString,
        NoAuth,
        OptionsSource,
        PostDependency,
        RenderedForm,
        SectionItem,
        StyleSchema,
        SubmitAction,
    )
    from parrot_formdesigner.extractors import (  # noqa: F401
        JSONSchemaExtractor,
        PydanticExtractor,
        ToolExtractor,
        YAMLExtractor,
    )
    from parrot_formdesigner.renderers import (  # noqa: F401
        AdaptiveCardRenderer,
        HTML5Renderer,
        JsonSchemaRenderer,
    )
    from parrot_formdesigner.services import (  # noqa: F401
        FormCache,
        FormRegistry,
        FormStorage,
        FormSubmission,
        FormSubmissionStorage,
        FormValidator,
        ForwardResult,
        PostgresFormStorage,
        RuleEvaluator,
        RuleResolution,
        SubmissionForwarder,
        ValidationResult,
    )
    from parrot_formdesigner.tools import (  # noqa: F401
        CreateFormTool,
        DatabaseFormTool,
        RequestFormTool,
        get_dependency_rule_snippets,
        get_form_field_schema_snippets,
        list_supported_form_field_types,
    )
except ImportError as exc:
    raise ImportError(
        "parrot.forms requires the 'parrot-formdesigner' package: "
        "pip install parrot-formdesigner"
    ) from exc
