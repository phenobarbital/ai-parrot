"""
DataSource implementations for DatasetManager.

Available source types:
- DataSource: Abstract base class (ABC)
- InMemorySource: Wraps an already-loaded pd.DataFrame
- QuerySlugSource: Wraps QuerySource slug (lazy, no schema prefetch by default)
- MultiQuerySlugSource: Wraps multiple QuerySource slugs
- SQLQuerySource: User-provided SQL with {param} interpolation
- TableSource: Table reference with INFORMATION_SCHEMA schema prefetch
- AirtableSource: Airtable table or view
- SmartsheetSource: Smartsheet sheet
- IcebergSource: Apache Iceberg table via asyncdb iceberg driver
- MongoSource: MongoDB/DocumentDB collection via asyncdb mongo driver
- DeltaTableSource: Delta Lake table via asyncdb delta driver (local, S3, GCS)
"""
from .base import DataSource
from .memory import InMemorySource
from .query_slug import MultiQuerySlugSource, QuerySlugSource
from .sql import SQLQuerySource
from .table import TableSource
from .airtable import AirtableSource
from .smartsheet import SmartsheetSource
from .iceberg import IcebergSource
from .mongo import MongoSource
from .deltatable import DeltaTableSource

__all__ = [
    "DataSource",
    "InMemorySource",
    "MultiQuerySlugSource",
    "QuerySlugSource",
    "SQLQuerySource",
    "TableSource",
    "AirtableSource",
    "SmartsheetSource",
    "IcebergSource",
    "MongoSource",
    "DeltaTableSource",
]
