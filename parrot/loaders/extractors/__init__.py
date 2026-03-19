"""Structured data extraction for ontology ingestion and data pipelines."""
from .base import ExtractDataSource, ExtractedRecord, ExtractionResult
from .csv_source import CSVDataSource
from .json_source import JSONDataSource
from .records_source import RecordsDataSource
from .sql_source import SQLDataSource
from .api_source import APIDataSource
from .factory import DataSourceFactory

__all__ = [
    "ExtractDataSource",
    "ExtractedRecord",
    "ExtractionResult",
    "CSVDataSource",
    "JSONDataSource",
    "RecordsDataSource",
    "SQLDataSource",
    "APIDataSource",
    "DataSourceFactory",
]
