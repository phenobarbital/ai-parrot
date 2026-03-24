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
  (requires asyncdb[iceberg] extra)
- MongoSource: MongoDB/DocumentDB collection via asyncdb mongo driver
  (requires asyncdb[mongo] extra)
- DeltaTableSource: Delta Lake table via asyncdb delta driver (local, S3, GCS)
  (requires asyncdb[delta] extra)
"""
import logging as _logging

from .base import DataSource
from .memory import InMemorySource
from .query_slug import MultiQuerySlugSource, QuerySlugSource
from .sql import SQLQuerySource
from .table import TableSource
from .airtable import AirtableSource
from .smartsheet import SmartsheetSource

_logger = _logging.getLogger(__name__)

# Optional extras — imported lazily so missing asyncdb extras or pyarrow
# do not break the core sources package.
try:
    from .iceberg import IcebergSource
except ImportError as _e:  # pragma: no cover
    _logger.debug(
        "IcebergSource not available (install asyncdb[iceberg]): %s", _e
    )
    IcebergSource = None  # type: ignore[assignment,misc]

try:
    from .mongo import MongoSource
except ImportError as _e:  # pragma: no cover
    _logger.debug(
        "MongoSource not available (install asyncdb[mongo]): %s", _e
    )
    MongoSource = None  # type: ignore[assignment,misc]

try:
    from .deltatable import DeltaTableSource
except ImportError as _e:  # pragma: no cover
    _logger.debug(
        "DeltaTableSource not available (install asyncdb[delta]): %s", _e
    )
    DeltaTableSource = None  # type: ignore[assignment,misc]

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
