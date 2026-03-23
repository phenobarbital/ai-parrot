"""Factory for resolving source names to ExtractDataSource implementations."""
from __future__ import annotations

from typing import Any

from .base import ExtractDataSource
from .csv_source import CSVDataSource
from .json_source import JSONDataSource
from .records_source import RecordsDataSource
from .sql_source import SQLDataSource


class DataSourceFactory:
    """Resolve source names to ExtractDataSource implementations.

    Resolution order:
        1. Check ``type`` key in source_config against built-in types.
        2. Check registered custom API sources.
        3. Raise UnknownDataSourceError.

    Built-in types: csv, json, sql, records.
    Custom API sources can be registered via ``register_api_source()``.
    """

    _builtin_types: dict[str, type[ExtractDataSource]] = {
        "csv": CSVDataSource,
        "json": JSONDataSource,
        "sql": SQLDataSource,
        "records": RecordsDataSource,
    }

    _api_registry: dict[str, type[ExtractDataSource]] = {}

    @classmethod
    def register_api_source(
        cls, name: str, source_cls: type[ExtractDataSource]
    ) -> None:
        """Register a custom API data source implementation.

        Args:
            name: Source type name (e.g. "workday", "jira").
            source_cls: ExtractDataSource subclass to use.
        """
        cls._api_registry[name] = source_cls

    def get(
        self, source_name: str, source_config: dict[str, Any] | None = None,
    ) -> ExtractDataSource:
        """Resolve a source name to an ExtractDataSource instance.

        Args:
            source_name: Name of the data source.
            source_config: Configuration dict for the source. The ``type`` key
                determines which implementation to use; falls back to
                ``source_name`` if ``type`` is not present.

        Returns:
            An instantiated ExtractDataSource.

        Raises:
            UnknownDataSourceError: If the source type cannot be resolved.
        """
        from parrot.knowledge.ontology.exceptions import UnknownDataSourceError

        cfg = source_config or {}
        source_type = cfg.get("type", source_name)

        if source_type in self._builtin_types:
            cls = self._builtin_types[source_type]
            return cls(name=source_name, config=cfg)

        if source_type in self._api_registry:
            cls = self._api_registry[source_type]
            return cls(name=source_name, config=cfg)

        available = sorted(
            set(self._builtin_types.keys()) | set(self._api_registry.keys())
        )
        raise UnknownDataSourceError(
            f"No extractor for source '{source_name}' (type='{source_type}'). "
            f"Available types: {', '.join(available)}"
        )
