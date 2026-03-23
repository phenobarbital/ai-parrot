"""Exceptions for the ExtractDataSource framework.

Re-exports from the ontology exceptions module for convenience.
"""
from parrot.knowledge.ontology.exceptions import (
    DataSourceValidationError,
    UnknownDataSourceError,
)

__all__ = [
    "DataSourceValidationError",
    "UnknownDataSourceError",
]
