"""Core form models for parrot-formdesigner.

This package exposes all public symbols from the core form abstraction layer:
types, constraints, options, schema, and style models.
"""

from .auth import ApiKeyAuth, AuthConfig, BearerAuth, NoAuth
from .constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
)
from .options import FieldOption, OptionsSource
from .schema import (
    BUILTIN_METADATA_SOURCE_NAMES,
    FormField,
    FormMetadataField,
    FormSchema,
    FormSection,
    FormSubsection,
    MetadataSource,
    RenderedForm,
    SectionItem,
    SubmitAction,
)
from .style import (
    FieldSizeHint,
    FieldStyleHint,
    FormStyle,
    LayoutType,
    StyleSchema,
)
from .types import FieldType, LocalizedString

__all__ = [
    # Types
    "LocalizedString",
    "FieldType",
    # Auth
    "AuthConfig",
    "NoAuth",
    "BearerAuth",
    "ApiKeyAuth",
    # Constraints
    "FieldConstraints",
    "ConditionOperator",
    "FieldCondition",
    "DependencyRule",
    # Options
    "FieldOption",
    "OptionsSource",
    # Schema
    "FormField",
    "FormSubsection",
    "SectionItem",
    "FormSection",
    "SubmitAction",
    "FormSchema",
    "FormMetadataField",
    "MetadataSource",
    "BUILTIN_METADATA_SOURCE_NAMES",
    "RenderedForm",
    # Style
    "LayoutType",
    "FieldSizeHint",
    "FieldStyleHint",
    "StyleSchema",
    "FormStyle",
]
