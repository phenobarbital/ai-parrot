"""
DatasetManager subpackage.

Provides:
- DatasetManager: A Toolkit and Data Catalog for PandasAgent
- DatasetEntry: Lifecycle wrapper around a DataSource
- DatasetInfo: Pydantic schema for dataset metadata exposed to LLM
- DataSource: Abstract base for all data source types
"""
from .tool import DatasetManager, DatasetEntry, DatasetInfo

__all__ = [
    "DatasetManager",
    "DatasetEntry",
    "DatasetInfo",
]
