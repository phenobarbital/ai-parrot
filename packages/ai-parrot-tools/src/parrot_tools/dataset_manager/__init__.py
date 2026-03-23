"""Backward-compat re-export — canonical location is parrot.tools.dataset_manager."""
from parrot.tools.dataset_manager import (  # noqa: F401
    DatasetManager,
    DatasetEntry,
    DatasetInfo,
    DataSource,
    InMemorySource,
    QuerySlugSource,
    MultiQuerySlugSource,
    SQLQuerySource,
    TableSource,
    AirtableSource,
    SmartsheetSource,
)

__all__ = [
    "DatasetManager",
    "DatasetEntry",
    "DatasetInfo",
    "DataSource",
    "InMemorySource",
    "QuerySlugSource",
    "MultiQuerySlugSource",
    "SQLQuerySource",
    "TableSource",
    "AirtableSource",
    "SmartsheetSource",
]
