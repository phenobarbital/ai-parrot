"""
DatasetManager subpackage.

Provides:
- DatasetManager: A Toolkit and Data Catalog for PandasAgent
- DatasetEntry: Lifecycle wrapper around a DataSource
- DatasetInfo: Pydantic schema for dataset metadata exposed to LLM
- DataSource: Abstract base for all data source types
- CompositeDataSource / JoinSpec: Virtual JOIN datasets
- ComputedColumnDef: Post-materialization computed column definition
"""
from .tool import DatasetManager, DatasetEntry, DatasetInfo
from .computed import ComputedColumnDef
from .sources import (
    DataSource,
    InMemorySource,
    QuerySlugSource,
    MultiQuerySlugSource,
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
    "CompositeDataSource",
    "JoinSpec",
    "IcebergSource",
    "MongoSource",
    "DeltaTableSource",
    "ComputedColumnDef",
]
