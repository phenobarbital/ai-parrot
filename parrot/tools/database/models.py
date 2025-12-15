# ============================================================================
# SCHEMA-CENTRIC DATA MODELS
# ============================================================================
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from pydantic import Field
import yaml

@dataclass
class SchemaMetadata:
    """Metadata for a single schema (client)."""
    database_name: str
    schema: str
    table_count: int
    view_count: int
    total_rows: Optional[int] = None
    last_analyzed: Optional[datetime] = None
    database_type: Optional[str] = Field(default='postgresql')
    tables: Dict[str, 'TableMetadata'] = field(default_factory=dict)
    views: Dict[str, 'TableMetadata'] = field(default_factory=dict)
    functions: List[Dict[str, Any]] = field(default_factory=list)

    def get_all_objects(self) -> Dict[str, 'TableMetadata']:
        """Get all tables and views."""
        return {**self.tables, **self.views}


@dataclass
class TableMetadata:
    """Enhanced table metadata for large-scale operations."""
    schema: str
    tablename: str
    table_type: str  # 'BASE TABLE', 'VIEW'
    full_name: str   # schema.table for easy reference
    comment: Optional[str] = None
    columns: List[Dict[str, Any]] = field(default_factory=list)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)
    indexes: List[Dict[str, Any]] = field(default_factory=list)
    row_count: Optional[int] = None
    sample_data: List[Dict[str, Any]] = field(default_factory=list)

    # Performance and usage metadata
    last_accessed: Optional[datetime] = None
    access_frequency: int = 0
    avg_query_time: Optional[float] = None

    def __post_init__(self):
        if not self.full_name:
            self.full_name = f'"{self.schema}"."{self.tablename}"'

    def to_yaml_context(self) -> str:
        """Convert to YAML context optimized for LLM consumption."""
        # Include only essential information to avoid token bloat
        essential_columns = self.columns[:20]  # Limit to first 20 columns

        data = {
            'table': self.full_name,
            'type': self.table_type,
            'description': self.comment or f"{self.table_type.lower()} in {self.schema} schema",
            'columns': [
                {
                    'name': col['name'],
                    'type': col['type'],
                    'nullable': col.get('nullable', True),
                    'description': col.get('comment')
                }
                for col in essential_columns
            ],
            'primary_keys': self.primary_keys,
            'row_count': self.row_count,
            'sample_values': self._get_sample_column_values()
        }

        if len(self.columns) > 20:
            data['note'] = f"Showing 20 of {len(self.columns)} columns. Use schema search tools for complete structure."

        return yaml.dump(data, default_flow_style=False, sort_keys=False)

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
