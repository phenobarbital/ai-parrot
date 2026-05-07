"""Universal Form Abstraction Layer for AI-Parrot.

This module is a backward-compatible re-export shim. All form functionality
has been moved to the `parrot-formdesigner` package (parrot_formdesigner.*).

Existing imports from parrot.forms continue to work unchanged.

Updated for FEAT-152: ``parrot_formdesigner`` no longer re-exports symbols
at the top level. We now import from the explicit submodules.
"""

# Re-export from parrot_formdesigner submodules for backward compatibility.
# No deprecation warnings per spec decision (non-production feature).
try:
    from parrot_formdesigner.core import (  # noqa: F401
        ApiKeyAuth,
        AuthConfig,
        BearerAuth,
        ConditionOperator,
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
        LayoutType,
        LocalizedString,
        NoAuth,
        OptionsSource,
        RenderedForm,
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
        ForwardResult,
        FormRegistry,
        FormStorage,
        FormSubmission,
        FormSubmissionStorage,
        FormValidator,
        PostgresFormStorage,
        SubmissionForwarder,
        ValidationResult,
    )
    from parrot_formdesigner.tools import (  # noqa: F401
        CreateFormTool,
        DatabaseFormTool,
        RequestFormTool,
        get_form_field_schema_snippets,
        list_supported_form_field_types,
    )
except ImportError:
    # parrot-formdesigner not installed — fall back to local definitions
    from .constraints import (  # noqa: F401
        ConditionOperator,
        DependencyRule,
        FieldCondition,
        FieldConstraints,
    )
    from .options import FieldOption, OptionsSource  # noqa: F401
    from .schema import FormField, FormSchema, FormSection, RenderedForm, SubmitAction  # noqa: F401
    from .style import FieldSizeHint, FieldStyleHint, LayoutType, StyleSchema  # noqa: F401
    from .types import FieldType, LocalizedString  # noqa: F401
    from .validators import FormValidator, ValidationResult  # noqa: F401
    from .extractors.pydantic import PydanticExtractor  # noqa: F401
    from .registry import FormRegistry, FormStorage  # noqa: F401
    from .cache import FormCache  # noqa: F401
    from .storage import PostgresFormStorage  # noqa: F401
    from .tools.request_form import RequestFormTool  # noqa: F401
    from .tools.create_form import CreateFormTool  # noqa: F401
    from .tools.database_form import DatabaseFormTool  # noqa: F401
