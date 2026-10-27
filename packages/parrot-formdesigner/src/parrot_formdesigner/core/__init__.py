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
    FormDialect,
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
from .voice_answer import (
    VoiceAnswerEnvelope,
    VoiceEvidenceEnvelope,
    is_voice_envelope,
    unwrap_voice,
    wrap_voice,
)
from .audit_trail import (
    DEFAULT_MAX_BYTES,
    AuditDetail,
    AuditTrailConfig,
    CheckId,
    CheckOutcome,
    CheckRecord,
    FieldTrace,
    SkipReason,
    ValidationTrace,
)
from .public_access import (
    AvailabilityState,
    CompletionAction,
    PublicAccessConfig,
    RejectionReason,
    evaluate_open,
    normalize_key_value,
)
from .llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,
    implausible_fields,
)
from .voice import (
    FieldVoiceMeta,
    HandsFreeConfig,
    UiCue,
    VoiceFormConfig,
    field_voice_meta,
    is_sensitive,
    resolve_voice_config,
)

__all__ = [
    # Types
    "LocalizedString",
    "FieldType",
    # Voice answer envelope (FEAT-488)
    "VoiceAnswerEnvelope",
    "VoiceEvidenceEnvelope",
    "is_voice_envelope",
    "unwrap_voice",
    "wrap_voice",
    # Voice mode + LLM plausibility (FEAT-649)
    "HandsFreeConfig",
    "UiCue",
    "FieldVoiceMeta",
    "VoiceFormConfig",
    "is_sensitive",
    "field_voice_meta",
    "resolve_voice_config",
    "AuditDetail",
    "AuditTrailConfig",
    "CheckId",
    "CheckOutcome",
    "CheckRecord",
    "DEFAULT_MAX_BYTES",
    "FieldTrace",
    "SkipReason",
    "ValidationTrace",
    "LLMValidationConfig",
    # Public response controls (FEAT-730)
    "PublicAccessConfig",
    "CompletionAction",
    "AvailabilityState",
    "RejectionReason",
    "evaluate_open",
    "normalize_key_value",
    "PlausibilityVerdict",
    "PlausibilityReport",
    "llm_validation_enabled",
    "implausible_fields",
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
    "FormDialect",
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
