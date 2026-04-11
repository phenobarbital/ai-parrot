"""Backward-compat re-export — canonical location is parrot.tools.dataset_manager.sources."""
from parrot.tools.dataset_manager.sources import (  # noqa: F401
    DataSource,
    InMemorySource,
    MultiQuerySlugSource,
    QuerySlugSource,
    SQLQuerySource,
    TableSource,
    AirtableSource,
    SmartsheetSource,
    CompositeDataSource,
    JoinSpec,
    IcebergSource,
    MongoSource,
    DeltaTableSource,
)

__all__ = [
    "DataSource",
    "InMemorySource",
    "MultiQuerySlugSource",
    "QuerySlugSource",
    "SQLQuerySource",
    "TableSource",
    "AirtableSource",
    "SmartsheetSource",
    "CompositeDataSource",
    "JoinSpec",
    "IcebergSource",
    "MongoSource",
    "DeltaTableSource",
]
