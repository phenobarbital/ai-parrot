"""DatasetManager common-field filtering sub-package (FEAT-225).

Public re-exports so callers can import from the package root:

    from parrot.tools.dataset_manager.filtering import (
        FilterKind,
        FilterOp,
        ValuesSource,
        FilterDefinition,
        FilterCondition,
        FilterResult,
    )
"""

from parrot.tools.dataset_manager.filtering.contracts import (
    FilterCondition,
    FilterDefinition,
    FilterKind,
    FilterOp,
    FilterResult,
    ValuesSource,
)

__all__ = [
    "FilterKind",
    "FilterOp",
    "ValuesSource",
    "FilterDefinition",
    "FilterCondition",
    "FilterResult",
]
