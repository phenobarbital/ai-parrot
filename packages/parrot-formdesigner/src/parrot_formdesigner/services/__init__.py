"""Form services for parrot-formdesigner.

Provides validation, registry, caching, and storage for FormSchema objects.
"""

from .cache import FormCache
from .csrf import (
    issue_form_csrf_token,
    validate_form_csrf_token,
)
from .event_dispatcher import apply_schema_overrides, dispatch, dispatch_visit
from .event_registry import (
    get_form_event,
    list_form_events,
    register_form_event,
)
from .form_version import FormVersionService, VersionMeta
from .forwarder import ForwardResult, SubmissionForwarder
from .metadata_callbacks import MetadataCallbackInput, MetadataCallbackOutput
from .metadata_enricher import MetadataResolutionError, enrich_submission
from .question_bank import QuestionBankService, ReusableField, ReusableFieldRef
from .registry import FormRegistry, FormStorage
from .storage import PostgresFormStorage
from .submissions import (
    CORE_METADATA_COLUMNS,
    FormSubmission,
    FormSubmissionStorage,
)
from .rule_evaluator import RuleEvaluator, RuleResolution
from .validators import FormValidator, ValidationResult

__all__ = [
    "CORE_METADATA_COLUMNS",
    "FormCache",
    "FormVersionService",
    "ForwardResult",
    "FormRegistry",
    "FormStorage",
    "FormSubmission",
    "FormSubmissionStorage",
    "FormValidator",
    "MetadataCallbackInput",
    "MetadataCallbackOutput",
    "MetadataResolutionError",
    "PostgresFormStorage",
    "QuestionBankService",
    "ReusableField",
    "ReusableFieldRef",
    "SubmissionForwarder",
    "ValidationResult",
    "VersionMeta",
    "enrich_submission",
    # Lifecycle event registry (FEAT-188)
    "register_form_event",
    "get_form_event",
    "list_form_events",
    # Lifecycle event dispatcher (FEAT-188)
    "dispatch",
    "apply_schema_overrides",
    # Visit lifecycle dispatcher (FEAT-329)
    "dispatch_visit",
    # CSRF helpers for remote events endpoint (FEAT-188)
    "issue_form_csrf_token",
    "validate_form_csrf_token",
    # Rule evaluator (FEAT-234)
    "RuleEvaluator",
    "RuleResolution",
]
