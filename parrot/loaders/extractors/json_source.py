"""JSON data source for structured record extraction."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .base import ExtractDataSource, ExtractionResult


class JSONDataSource(ExtractDataSource):
    """Extract structured records from JSON files or arrays.

    Config:
        path: str — Path to JSON file.
        records_path: str | None — Dot-separated path to the array of records
            (e.g. "data.employees" for nested JSON). None means the root is
            the array.

    Args:
        name: Human-readable name for logging and reporting.
        config: Source-specific configuration.
    """

    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Parse JSON and extract records from the configured path.

        Args:
            fields: Optional field projection.
            filters: Optional key-value filters applied in-memory.

        Returns:
            ExtractionResult with JSON records.
        """
        path = self.config.get("path")
        if not path:
            return self._build_result(
                [], fields=fields, filters=filters,
                errors=["No 'path' configured for JSON source"],
            )

        records, errors = await asyncio.to_thread(self._read_json, path)
        return self._build_result(
            records, fields=fields, filters=filters, errors=errors,
        )

    async def list_fields(self) -> list[str]:
        """Load first record and return its keys.

        Returns:
            List of field names from the first record.
        """
        path = self.config.get("path")
        if not path:
            return []
        records, _ = await asyncio.to_thread(self._read_json, path)
        if records:
            return list(records[0].keys())
        return []

    def _read_json(self, path: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Synchronous JSON reading (run via asyncio.to_thread).

        Returns:
            Tuple of (records, errors).
        """
        file_path = Path(path)
        if not file_path.exists():
            return [], [f"JSON file not found: {path}"]

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return [], [f"Invalid JSON in {path}: {e}"]

        records_path = self.config.get("records_path")
        if records_path:
            for key in records_path.split("."):
                if isinstance(data, dict):
                    data = data.get(key)
                else:
                    return [], [
                        f"Cannot navigate '{records_path}': "
                        f"'{key}' not found in {type(data).__name__}"
                    ]
                if data is None:
                    return [], [f"Path '{records_path}' resolved to None"]

        if not isinstance(data, list):
            return [], [
                f"Expected a list at "
                f"{'root' if not records_path else records_path}, "
                f"got {type(data).__name__}"
            ]

        self.logger.debug("Read %d records from %s", len(data), path)
        return data, []
