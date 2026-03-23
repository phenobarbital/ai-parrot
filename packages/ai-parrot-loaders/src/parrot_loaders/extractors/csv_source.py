"""CSV data source for structured record extraction."""
from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Any

from .base import ExtractDataSource, ExtractionResult


class CSVDataSource(ExtractDataSource):
    """Extract structured records from CSV files.

    Config:
        path: str — Path to the CSV file.
        delimiter: str — Column delimiter (default: ',').
        encoding: str — File encoding (default: 'utf-8').
        skip_rows: int — Number of initial rows to skip (default: 0).

    Args:
        name: Human-readable name for logging and reporting.
        config: Source-specific configuration.
    """

    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Read CSV and return each row as an ExtractedRecord.

        Args:
            fields: Optional field projection (only these columns returned).
            filters: Optional key-value filters applied in-memory.

        Returns:
            ExtractionResult with CSV rows as records.
        """
        path = self.config.get("path")
        if not path:
            return self._build_result(
                [], fields=fields, filters=filters,
                errors=["No 'path' configured for CSV source"],
            )

        records = await asyncio.to_thread(self._read_csv, path)
        return self._build_result(records, fields=fields, filters=filters)

    async def list_fields(self) -> list[str]:
        """Read only the header row to get column names.

        Returns:
            List of column header strings.
        """
        path = self.config.get("path")
        if not path:
            return []
        return await asyncio.to_thread(self._read_header, path)

    def _read_csv(self, path: str) -> list[dict[str, Any]]:
        """Synchronous CSV reading (run via asyncio.to_thread)."""
        delimiter = self.config.get("delimiter", ",")
        encoding = self.config.get("encoding", "utf-8")
        skip_rows = self.config.get("skip_rows", 0)

        file_path = Path(path)
        if not file_path.exists():
            self.logger.error("CSV file not found: %s", path)
            return []

        records: list[dict[str, Any]] = []
        with open(file_path, newline="", encoding=encoding) as f:
            # Skip initial rows
            for _ in range(skip_rows):
                next(f, None)

            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                records.append(dict(row))

        self.logger.debug("Read %d records from %s", len(records), path)
        return records

    def _read_header(self, path: str) -> list[str]:
        """Read only the CSV header row."""
        delimiter = self.config.get("delimiter", ",")
        encoding = self.config.get("encoding", "utf-8")
        skip_rows = self.config.get("skip_rows", 0)

        file_path = Path(path)
        if not file_path.exists():
            return []

        with open(file_path, newline="", encoding=encoding) as f:
            for _ in range(skip_rows):
                next(f, None)
            reader = csv.DictReader(f, delimiter=delimiter)
            return list(reader.fieldnames or [])
