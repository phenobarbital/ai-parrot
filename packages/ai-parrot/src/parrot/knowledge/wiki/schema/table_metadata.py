"""Framework-free table-metadata model shared by the schema plane and ``parrot.bots.database``.

Kept free of ``parrot.bots`` / ``parrot.conf`` imports so the wiki CLI import chain stays light.
``parrot.bots.database.models`` re-exports these names, so existing import paths are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Literal, Optional

import yaml

class Completeness(IntEnum):
    """Completeness level of a cached TableMetadata entry.

    Ordered so ``meta.completeness >= required`` is the canonical check
    (higher value = strictly subsumes lower levels).
    """

    NAME_ONLY = 1  # Only schema + table name; no columns introspected
    WITH_COLUMNS = 2  # Columns present; indexes/FK/stats may be missing
    FULL = 3  # Fully introspected entry (columns, PKs, FKs, indexes)


MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "ddl", "unknown"]


@dataclass
class TableMetadata:
    """Enhanced table metadata for large-scale operations."""

    schema: str
    tablename: str
    table_type: str  # 'BASE TABLE', 'VIEW'
    full_name: str  # schema.table for easy reference
    comment: Optional[str] = None
    columns: List[Dict[str, Any]] = field(default_factory=list)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)
    indexes: List[Dict[str, Any]] = field(default_factory=list)
    row_count: Optional[int] = None
    sample_data: List[Dict[str, Any]] = field(default_factory=list)
    unique_constraints: List[List[str]] = field(default_factory=list)
    """Each inner list is one UNIQUE constraint's column set (ordered by ordinal_position)."""

    # Performance and usage metadata
    last_accessed: Optional[datetime] = None
    access_frequency: int = 0
    avg_query_time: Optional[float] = None

    # Cache completeness tracking (FEAT-178)
    completeness: Completeness = field(default=Completeness.FULL)
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    source: MetadataSource = field(default="unknown")

    def __post_init__(self):
        if not self.full_name:
            self.full_name = f'"{self.schema}"."{self.tablename}"'

    def satisfies(self, required: Completeness) -> bool:
        """Return True if this entry meets or exceeds *required* completeness."""
        return self.completeness >= required

    def to_yaml_context(self) -> str:
        """Convert to YAML context optimized for LLM consumption."""
        essential_columns = self.columns[:20]  # Limit to first 20 columns

        data: Dict[str, Any] = {
            "table": self.full_name,
            "type": self.table_type,
            "completeness": self.completeness.name,
            "loaded_at": self.loaded_at.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if self.completeness < Completeness.FULL:
            data["_warning"] = (
                f"{self.completeness.name} stub — call db_describe_table to load columns " "before generating SQL."
            )

        data["description"] = self.comment or f"{self.table_type.lower()} in {self.schema} schema"
        data["columns"] = [
            {
                "name": col["name"],
                "type": col["type"],
                "nullable": col.get("nullable", True),
                "description": col.get("comment"),
            }
            for col in essential_columns
        ]
        data["primary_keys"] = self.primary_keys
        data["row_count"] = self.row_count
        data["sample_values"] = self._get_sample_column_values()

        if len(self.columns) > 20:
            data["note"] = f"Showing 20 of {len(self.columns)} columns. Use schema search tools for complete structure."

        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize ``TableMetadata`` to a plain dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization or
            cache storage.
        """
        return {
            "schema": self.schema,
            "tablename": self.tablename,
            "table_type": self.table_type,
            "full_name": self.full_name,
            "comment": self.comment,
            "columns": self.columns,
            "primary_keys": self.primary_keys,
            "foreign_keys": self.foreign_keys,
            "indexes": self.indexes,
            "row_count": self.row_count,
            "unique_constraints": self.unique_constraints,
        }

    def _get_sample_column_values(self) -> Dict[str, List]:
        """Extract sample values per column for context."""
        if not self.sample_data:
            return {}

        sample_values = {}
        for row in self.sample_data[:3]:  # First 3 rows
            for col_name, value in row.items():
                if col_name not in sample_values:
                    sample_values[col_name] = []
                if value is not None and len(sample_values[col_name]) < 3:
                    sample_values[col_name].append(str(value))

        return sample_values
