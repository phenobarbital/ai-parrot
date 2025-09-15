# ============================================================================
# SCHEMA-CENTRIC DATA MODELS
# ============================================================================
from __future__ import annotations
from typing import Dict, Any, List, Optional
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import yaml


class UserRole(str, Enum):
    """Defines user roles for access control and query tailoring."""
    DATA_ANALYST = "data_analyst"
    BUSINESS_USER = "business_user"
    DATABASE_ADMIN = "database_admin"
    DEVELOPER = "developer"


class QueryIntent(str, Enum):
    """Defines the user's intent for the query."""
    SHOW_DATA = "show_data"           # "Show me users" -> data retrieval
    GENERATE_QUERY = "generate_query" # "Get username and job_code" -> query generation
    ANALYZE_DATA = "analyze_data"     # "analyze sales trends" -> analysis
    VALIDATE_QUERY = "validate_query" # User provides SQL to check
    EXPLORE_SCHEMA = "explore_schema" # "what tables exist" -> schema exploration


class ReturnFormat(str, Enum):
    """Defines the desired format of the response."""
    DATA_ONLY = "data_only"                    # Just the results
    QUERY_AND_DATA = "query_and_data"         # SQL + results
    QUERY_DATA_EXPLANATION = "full_response"  # SQL + results + explanation
    QUERY_ONLY = "query_only"                 # Just SQL, no execution


@dataclass
class SchemaMetadata:
    """Metadata for a single schema (client)."""
    schema_name: str
    database_name: str
    table_count: int
    view_count: int
    total_rows: Optional[int] = None
    last_analyzed: Optional[datetime] = None
    tables: Dict[str, 'TableMetadata'] = field(default_factory=dict)
    views: Dict[str, 'TableMetadata'] = field(default_factory=dict)

    def get_all_objects(self) -> Dict[str, 'TableMetadata']:
        """Get all tables and views."""
        return {**self.tables, **self.views}


@dataclass
class TableMetadata:
    """Enhanced table metadata for large-scale operations."""
    schema_name: str
    table_name: str
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
            self.full_name = f'"{self.schema_name}"."{self.table_name}"'

    def to_yaml_context(self) -> str:
        """Convert to YAML context optimized for LLM consumption."""
        # Include only essential information to avoid token bloat
        essential_columns = self.columns[:10]  # Limit to first 10 columns

        data = {
            'table': self.full_name,
            'type': self.table_type,
            'description': self.comment or f"{self.table_type.lower()} in {self.schema_name} schema",
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

        if len(self.columns) > 10:
            data['note'] = f"Showing 10 of {len(self.columns)} columns. Use schema tools for complete structure."

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


class QueryExecutionRequest(BaseModel):
    """Structured input for query execution."""
    sql_query: str
    limit: Optional[int] = 1000
    timeout: int = 30
    explain_analyze: bool = False
    dry_run: bool = False
    schema_name: str


class QueryExecutionResponse(BaseModel):
    """Structured output from query execution."""
    success: bool
    data: Optional[Any] = None
    row_count: int = 0
    execution_time_ms: float
    columns: List[str] = Field(default_factory=list)
    query_plan: Optional[str] = None
    error_message: Optional[str] = None
    schema_used: str


@dataclass
class RouteDecision:
    """Query routing decision for schema-centric operations."""
    intent: QueryIntent
    return_format: ReturnFormat
    primary_schema: str
    allowed_schemas: List[str]
    needs_metadata_discovery: bool = True
    needs_query_generation: bool = True
    needs_execution: bool = True
    execution_options: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8
