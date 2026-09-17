"""QuerysourceToolkit — tenant-scoped QuerySource query-slug and MultiQuery tools (FEAT-558)."""

from .errors import (
    InvalidConditionsError,
    QuerysourceToolkitError,
    RawSqlForbiddenError,
    SlugNotFoundError,
    TenantDeniedError,
    WriteDisabledError,
)
from .models import (
    ComponentDoc,
    DialectReference,
    ExecutionResult,
    MultiQueryResult,
    PipelineValidation,
    SavedSlug,
    SlugDetail,
    SlugSummary,
)
from .toolkit import QuerysourceToolkit

__all__ = [
    "QuerysourceToolkit",
    "ComponentDoc",
    "DialectReference",
    "ExecutionResult",
    "MultiQueryResult",
    "PipelineValidation",
    "SavedSlug",
    "SlugDetail",
    "SlugSummary",
    "QuerysourceToolkitError",
    "InvalidConditionsError",
    "RawSqlForbiddenError",
    "SlugNotFoundError",
    "TenantDeniedError",
    "WriteDisabledError",
]
