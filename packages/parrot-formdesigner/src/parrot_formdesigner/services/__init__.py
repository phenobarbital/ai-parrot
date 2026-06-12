"""Form services for parrot-formdesigner.

Provides validation, registry, caching, and storage for FormSchema objects.
Also exports the FEAT-301 conditional logic evaluation infrastructure.
"""

from .cache import FormCache
from .csrf import (
    issue_form_csrf_token,
    validate_form_csrf_token,
)
from .event_dispatcher import apply_schema_overrides, dispatch
from .event_registry import (
    get_form_event,
    list_form_events,
    register_form_event,
)
from .form_version import FormVersionService, VersionMeta
from .forwarder import ForwardResult, SubmissionForwarder
from .logic_graph import CyclicDependencyError, LogicGraph
from .metadata_callbacks import MetadataCallbackInput, MetadataCallbackOutput
from .metadata_enricher import MetadataResolutionError, enrich_submission
from .question_bank import QuestionBankService, ReusableField, ReusableFieldRef
from .registry import FormRegistry, FormStorage
from .rule_evaluator import (
    EffectResult,
    EvaluationContext,
    EvaluationResult,
    RuleEvaluator,
)
from .storage import PostgresFormStorage
from .submissions import (
    CORE_METADATA_COLUMNS,
    FormSubmission,
    FormSubmissionStorage,
)
from .validators import FormValidator, ValidationResult

__all__ = [
    "CORE_METADATA_COLUMNS",
    "CyclicDependencyError",
    "EffectResult",
    "EvaluationContext",
    "EvaluationResult",
    "FormCache",
    "FormVersionService",
    "ForwardResult",
    "FormRegistry",
    "FormStorage",
    "FormSubmission",
    "FormSubmissionStorage",
    "FormValidator",
    "LogicGraph",
    "MetadataCallbackInput",
    "MetadataCallbackOutput",
    "MetadataResolutionError",
    "PostgresFormStorage",
    "QuestionBankService",
    "ReusableField",
    "ReusableFieldRef",
    "RuleEvaluator",
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
    # CSRF helpers for remote events endpoint (FEAT-188)
    "issue_form_csrf_token",
    "validate_form_csrf_token",
]
