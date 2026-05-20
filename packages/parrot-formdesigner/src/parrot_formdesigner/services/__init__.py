"""Form services for parrot-formdesigner.

Provides validation, registry, caching, and storage for FormSchema objects.
"""

from .cache import FormCache
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
]
