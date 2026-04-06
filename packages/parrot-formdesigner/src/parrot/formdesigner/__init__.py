"""parrot-formdesigner — Standalone form designer package for AI-Parrot.

Provides a complete form creation, rendering, validation, and HTTP serving system.
Can be used standalone or as a complement to ai-parrot.

Usage::

    from parrot.formdesigner import FormSchema, setup_form_routes
"""

from .version import __author__, __author_email__, __description__, __title__, __version__

from .core import (
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
from .extractors import (
    JSONSchemaExtractor,
    PydanticExtractor,
    ToolExtractor,
    YAMLExtractor,
)
from .handlers import FormAPIHandler, FormPageHandler, setup_form_routes
from .renderers import AdaptiveCardRenderer, HTML5Renderer, JsonSchemaRenderer
from .services import (
    FormCache,
    FormRegistry,
    FormStorage,
    FormValidator,
    PostgresFormStorage,
    ValidationResult,
)
from .tools import CreateFormTool, DatabaseFormTool, RequestFormTool

__all__ = [
    # core — types
    "LocalizedString",
    "FieldType",
    # core — auth
    "AuthConfig",
    "NoAuth",
    "BearerAuth",
    "ApiKeyAuth",
    # core — constraints
    "FieldConstraints",
    "ConditionOperator",
    "FieldCondition",
    "DependencyRule",
    # core — options
    "FieldOption",
    "OptionsSource",
    # core — schema
    "FormField",
    "FormSection",
    "SubmitAction",
    "FormSchema",
    "RenderedForm",
    # core — style
    "LayoutType",
    "FieldSizeHint",
    "FieldStyleHint",
    "StyleSchema",
    "FormStyle",
    # extractors
    "PydanticExtractor",
    "ToolExtractor",
    "YAMLExtractor",
    "JSONSchemaExtractor",
    # renderers
    "HTML5Renderer",
    "AdaptiveCardRenderer",
    "JsonSchemaRenderer",
    # services
    "FormValidator",
    "FormRegistry",
    "FormStorage",
    "FormCache",
    "PostgresFormStorage",
    "ValidationResult",
    # tools
    "CreateFormTool",
    "DatabaseFormTool",
    "RequestFormTool",
    # handlers
    "setup_form_routes",
    "FormAPIHandler",
    "FormPageHandler",
]
