"""Abstract base class and data models for structured data extraction.

ExtractDataSource provides a generic contract for extracting structured records
(list[dict]) from various data sources (CSV, JSON, SQL, APIs, in-memory).
Unlike AI-Parrot's Loaders (which produce text chunks for RAG), extractors
produce structured records for ontology graph ingestion, data pipelines, and ETL.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ExtractedRecord(BaseModel):
    """A single extracted record with its raw data and metadata.

    Args:
        data: Field values from the source (column→value mapping).
        metadata: Provenance info (source name, extraction timestamp, etc.).
    """

    data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Result of an extraction operation.

    Args:
        records: The extracted records.
        total: Total number of records extracted.
        errors: Error messages encountered during extraction.
        warnings: Warning messages (non-fatal issues).
        source_name: Human-readable name of the data source.
        extracted_at: Timestamp when extraction completed.
    """

    records: list[ExtractedRecord]
    total: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_name: str
    extracted_at: datetime


class ExtractDataSource(ABC):
    """Abstract base class for structured data extraction.

    Subclasses implement extract() and list_fields() for a specific data
    source type (CSV, JSON, SQL, API, etc.). All implementations must be
    async-first.

    Args:
        name: Human-readable name for logging and reporting.
        config: Source-specific configuration (paths, credentials, etc.).
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(
            f"Parrot.Extractors.{self.__class__.__name__}"
        )

    @abstractmethod
    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Extract structured records from the data source.

        Args:
            fields: Optional list of fields to extract (None = all fields).
                Allows the caller to request only the fields defined in the
                ontology entity, reducing memory and processing.
            filters: Optional key-value filters to pre-filter records at source.
                For CSV/JSON this filters in-memory after loading.
                For API/SQL sources this translates to query parameters.

        Returns:
            ExtractionResult with the list of ExtractedRecord instances.
        """
        ...

    @abstractmethod
    async def list_fields(self) -> list[str]:
        """Return the available field names from this data source.

        Used during ontology validation to check that entity properties
        and discovery rules reference fields that actually exist in the source.

        Returns:
            List of field/column names available in the source.
        """
        ...

    async def validate(
        self, expected_fields: list[str] | None = None
    ) -> bool:
        """Validate that the source is accessible and has the expected schema.

        Args:
            expected_fields: If provided, checks that all these fields exist
                in the source. Used during ontology build to catch
                YAML-to-source mismatches early.

        Returns:
            True if validation passes.

        Raises:
            DataSourceValidationError: With details on what's wrong.
        """
        from parrot.knowledge.ontology.exceptions import DataSourceValidationError

        available = await self.list_fields()
        if expected_fields:
            missing = set(expected_fields) - set(available)
            if missing:
                raise DataSourceValidationError(
                    f"Source '{self.name}' missing expected fields: {missing}. "
                    f"Available: {available}"
                )
        return True

    def _apply_filters(
        self, records: list[dict[str, Any]], filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Apply key-value filters to a list of records in-memory.

        Args:
            records: Raw records to filter.
            filters: Key-value pairs; a record passes if all keys match.

        Returns:
            Filtered list of records.
        """
        if not filters:
            return records
        result = []
        for record in records:
            if all(record.get(k) == v for k, v in filters.items()):
                result.append(record)
        return result

    def _project_fields(
        self, records: list[dict[str, Any]], fields: list[str]
    ) -> list[dict[str, Any]]:
        """Project records to only include the specified fields.

        Args:
            records: Raw records to project.
            fields: Field names to keep.

        Returns:
            Projected list of records (only requested keys).
        """
        if not fields:
            return records
        field_set = set(fields)
        return [
            {k: v for k, v in record.items() if k in field_set}
            for record in records
        ]

    def _build_result(
        self,
        records: list[dict[str, Any]],
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> ExtractionResult:
        """Build an ExtractionResult from raw records with optional filtering/projection.

        Args:
            records: Raw records from the source.
            fields: Optional field projection.
            filters: Optional key-value filters.
            errors: Error messages to include.
            warnings: Warning messages to include.

        Returns:
            ExtractionResult with filtered/projected ExtractedRecords.
        """
        filtered = self._apply_filters(records, filters) if filters else records
        projected = self._project_fields(filtered, fields) if fields else filtered
        return ExtractionResult(
            records=[
                ExtractedRecord(
                    data=r,
                    metadata={"source": self.name},
                )
                for r in projected
            ],
            total=len(projected),
            errors=errors or [],
            warnings=warnings or [],
            source_name=self.name,
            extracted_at=datetime.now(timezone.utc),
        )
