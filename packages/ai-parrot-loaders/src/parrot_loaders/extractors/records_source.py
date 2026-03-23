"""In-memory records data source for structured record extraction."""
from __future__ import annotations

from typing import Any

from .base import ExtractDataSource, ExtractionResult


class RecordsDataSource(ExtractDataSource):
    """Wrap an in-memory list[dict] as a data source.

    Useful for:
        - Unit testing (pass test data directly).
        - Programmatic ingestion (data already in memory).
        - Chaining with other extractors (transform then re-extract).

    Args:
        name: Human-readable name for logging and reporting.
        records: The in-memory records to serve.
        config: Optional source-specific configuration.
    """

    def __init__(
        self,
        name: str,
        records: list[dict[str, Any]] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name, config=config)
        self._records = records or []

    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Return the in-memory records, optionally filtered/projected.

        Args:
            fields: Optional field projection.
            filters: Optional key-value filters.

        Returns:
            ExtractionResult wrapping the in-memory records.
        """
        return self._build_result(
            self._records, fields=fields, filters=filters,
        )

    async def list_fields(self) -> list[str]:
        """Return keys from first record, or empty list.

        Returns:
            List of field names.
        """
        if self._records:
            return list(self._records[0].keys())
        return []
