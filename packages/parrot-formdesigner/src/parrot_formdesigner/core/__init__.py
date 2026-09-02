"""Core form models for parrot-formdesigner.

This package exposes all public symbols from the core form abstraction layer:
types, constraints, options, schema, style models, and lifecycle event models.
"""

from .auth import ApiKeyAuth, AuthConfig, BearerAuth, NoAuth
from .constraints import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    LogicGroup,
    FieldConstraints,
    PostDependency,
)
from .events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventContext,
    FormEventName,
    FormEventsConfig,
    VisitEventContext,
    VisitEventName,
)
from .options import FieldOption, OptionsSource
from .relations import EntityRef, RelationSpec
from .resolution import find_field_by_uid, resolve_answer, resolve_rule_references
from .schema import (
    BUILTIN_METADATA_SOURCE_NAMES,
    FormField,
    FormMetadataField,
    FormSchema,
    FormSection,
    FormSubsection,
    FormType,
    MetadataSource,
    RenderedForm,
    SectionItem,
    SubmitAction,
    UnknownFieldsPolicy,
    walk_fields,
)
from .style import (
    FieldSizeHint,
    FieldStyleHint,
    FormStyle,
    LayoutType,
    StyleSchema,
)
from .types import FieldType, LocalizedString
from .voice_answer import VoiceAnswerEnvelope

__all__ = [
    # Types
    "LocalizedString",
    "FieldType",
    # Voice answer envelope (FEAT-488)
    "VoiceAnswerEnvelope",
    # Auth
    "AuthConfig",
    "NoAuth",
    "BearerAuth",
    "ApiKeyAuth",
    # Constraints
    "FieldConstraints",
    "ConditionOperator",
    "FieldCondition",
    "LogicGroup",
    "DependencyRule",
    "DependencyOperation",
    "PostDependency",
    # Options
    "FieldOption",
    "OptionsSource",
    # Relations (FEAT-456)
    "EntityRef",
    "RelationSpec",
    # Resolution (FEAT-393, Module 3)
    "resolve_rule_references",
    "find_field_by_uid",
    "resolve_answer",
    # Schema
    "FormField",
    "FormSubsection",
    "SectionItem",
    "FormSection",
    "SubmitAction",
    "FormSchema",
    "FormType",
    "UnknownFieldsPolicy",
    "FormMetadataField",
    "MetadataSource",
    "BUILTIN_METADATA_SOURCE_NAMES",
    "RenderedForm",
    "walk_fields",
    # Style
    "LayoutType",
    "FieldSizeHint",
    "FieldStyleHint",
    "StyleSchema",
    "FormStyle",
    # Lifecycle events (FEAT-188)
    "FormEventName",
    "FormEventBinding",
    "FormEventsConfig",
    "FormEventContext",
    "EventResolution",
    "FormEventAbort",
    # Visit lifecycle events (FEAT-329)
    "VisitEventName",
    "VisitEventContext",
]
