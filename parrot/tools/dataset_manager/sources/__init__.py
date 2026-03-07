"""
DataSource implementations for DatasetManager.

Available source types:
- DataSource: Abstract base class (ABC)
- InMemorySource: Wraps an already-loaded pd.DataFrame
- QuerySlugSource: Wraps QuerySource slug (lazy, no schema prefetch by default)
- MultiQuerySlugSource: Wraps multiple QuerySource slugs
- SQLQuerySource: User-provided SQL with {param} interpolation
- TableSource: Table reference with INFORMATION_SCHEMA schema prefetch
"""
from .base import DataSource
from .memory import InMemorySource
from .query_slug import MultiQuerySlugSource, QuerySlugSource
from .sql import SQLQuerySource
from .table import TableSource

__all__ = [
    "DataSource",
    "InMemorySource",
    "MultiQuerySlugSource",
    "QuerySlugSource",
    "SQLQuerySource",
    "TableSource",
]
