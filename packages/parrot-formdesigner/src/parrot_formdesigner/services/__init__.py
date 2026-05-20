"""Form services for parrot-formdesigner.

Provides validation, registry, caching, and storage for FormSchema objects.
"""

from .cache import FormCache
from .csrf import (
    _clear_csrf_store_for_tests,
    issue_form_csrf_token,
    validate_form_csrf_token,
)
from .event_dispatcher import apply_schema_overrides, dispatch
from .event_registry import (
    _clear_event_registry_for_tests,
    get_form_event,
    list_form_events,
    register_form_event,
)
from .forwarder import ForwardResult, SubmissionForwarder
from .metadata_callbacks import MetadataCallbackInput, MetadataCallbackOutput
from .metadata_enricher import MetadataResolutionError, enrich_submission
from .registry import FormRegistry, FormStorage
from .storage import PostgresFormStorage
from .submissions import (
    CORE_METADATA_COLUMNS,
    FormSubmission,
    FormSubmissionStorage,
)
from .validators import FormValidator, ValidationResult

__all__ = [
    "CORE_METADATA_COLUMNS",
    "FormCache",
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
    "SubmissionForwarder",
    "ValidationResult",
    "enrich_submission",
    # Lifecycle event registry (FEAT-188)
    "register_form_event",
    "get_form_event",
    "list_form_events",
    "_clear_event_registry_for_tests",
    # Lifecycle event dispatcher (FEAT-188)
    "dispatch",
    "apply_schema_overrides",
    # CSRF helpers for remote events endpoint (FEAT-188)
    "issue_form_csrf_token",
    "validate_form_csrf_token",
    "_clear_csrf_store_for_tests",
]
