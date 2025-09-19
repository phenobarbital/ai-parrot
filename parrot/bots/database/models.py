# ============================================================================
# SCHEMA-CENTRIC DATA MODELS
# ============================================================================
from __future__ import annotations
from typing import Dict, Any, List, Optional, Union
from enum import Enum, Flag, auto
from datetime import datetime
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
import yaml
import pandas as pd


class UserRole(str, Enum):
    """Define user roles with specific output preferences."""
    BUSINESS_USER = "business_user"      # Data only, no limits, minimal explanation
    DATA_ANALYST = "data_analyst"        # Explanations, samples, schema context
    DATA_SCIENTIST = "data_scientist"    # Schema context + DataFrame conversion (no limits)
    DATABASE_ADMIN = "database_admin"    # SQL, execution plans, performance, optimization, sample data
    DEVELOPER = "developer"              # SQL/schema, explanations, examples, no data
    QUERY_DEVELOPER = "query_developer"  # SQL/schema, execution plans, performance, optimization, no data

class OutputComponent(Flag):
    """Flags for different response components - allows combinations."""
    NONE = 0
    SQL_QUERY = auto()           # Generated or validated SQL query
    EXECUTION_PLAN = auto()      # EXPLAIN ANALYZE results with optimizations
    DATA_RESULTS = auto()        # Actual query results
    DOCUMENTATION = auto()       # Table/schema metadata and explanations
    EXAMPLES = auto()            # Usage examples and sample queries
    PERFORMANCE_METRICS = auto() # Performance analysis and index suggestions
    SCHEMA_CONTEXT = auto()      # Available tables, columns, relationships
    OPTIMIZATION_TIPS = auto()   # Query optimization suggestions
    SAMPLE_DATA = auto()         # Sample rows for understanding data format
    DATAFRAME_OUTPUT = auto()    # Convert results to pandas DataFrame

    # Convenience combinations
    BASIC_QUERY = SQL_QUERY | DATA_RESULTS
    FULL_ANALYSIS = SQL_QUERY | EXECUTION_PLAN | PERFORMANCE_METRICS | OPTIMIZATION_TIPS
    DEVELOPER_FOCUS = SQL_QUERY | DOCUMENTATION | EXAMPLES | SCHEMA_CONTEXT
    BUSINESS_FOCUS = DATA_RESULTS
    QUERY_DEVELOPER_FOCUS = SQL_QUERY | EXECUTION_PLAN | PERFORMANCE_METRICS | OPTIMIZATION_TIPS | SCHEMA_CONTEXT

class OutputFormat(str, Enum):
    """Defines the desired format of the response."""
    # Basic formats
    QUERY_ONLY = "query_only"                      # Just the Query, no execution
    DATA_ONLY = "data_only"                    # Just the results
    QUERY_AND_DATA = "query_and_data"          # Query + results
    EXPLANATION_ONLY = "explanation_only"
    DOCUMENTATION_ONLY = "documentation_only"

    # Combined formats
    QUERY_WITH_EXPLANATION = "query_with_explanation"
    QUERY_WITH_DOCS = "query_with_docs"
    FULL_ANALYSIS = "full_analysis"

    # Role-specific formats
    DEVELOPER_FORMAT = "developer_format"
    DBA_FORMAT = "dba_format"
    ANALYST_FORMAT = "analyst_format"
    BUSINESS_FORMAT = "business_format"

    # Special utilities
    EXPLAIN_PLAN = "explain_plan"
    PERFORMANCE_ANALYSIS = "performance_analysis"
    QUERY_OPTIMIZATION = "query_optimization"
    QUERY_DATA_EXPLANATION = "full_response"  # SQL + results + explanation + optimization tips


class QueryIntent(str, Enum):
    """Defines the user's query intents for comprehensive database operations."""
    SHOW_DATA = "show_data"                    # Retrieve and display data
    GENERATE_QUERY = "generate_query"          # Create SQL from natural language
    ANALYZE_DATA = "analyze_data"              # Data analysis and insights
    EXPLORE_SCHEMA = "explore_schema"          # Schema exploration and documentation
    VALIDATE_QUERY = "validate_query"          # Validate user-provided SQL
    OPTIMIZE_QUERY = "optimize_query"          # Performance optimization focus
    EXPLAIN_METADATA = "explain_metadata"      # Table/column documentation
    CREATE_EXAMPLES = "create_examples"        # Generate usage examples
    GENERATE_REPORT = "generate_report"        # Create a report from the query results

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
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


# ============================================================================
# ROLE-BASED COMPONENT PREFERENCES
# ============================================================================

ROLE_COMPONENT_DEFAULTS: Dict[UserRole, OutputComponent] = {
    UserRole.BUSINESS_USER: (
        OutputComponent.DATA_RESULTS
    ),
    UserRole.DATA_ANALYST: (
        OutputComponent.SQL_QUERY |
        OutputComponent.DATA_RESULTS |
        OutputComponent.DOCUMENTATION |
        OutputComponent.SCHEMA_CONTEXT |
        OutputComponent.SAMPLE_DATA
    ),
    UserRole.DATA_SCIENTIST: (
        OutputComponent.SQL_QUERY |
        OutputComponent.DATAFRAME_OUTPUT |
        OutputComponent.SCHEMA_CONTEXT |
        OutputComponent.DOCUMENTATION |
        OutputComponent.DATA_RESULTS
    ),
    UserRole.DATABASE_ADMIN: (
        OutputComponent.SQL_QUERY |
        OutputComponent.EXECUTION_PLAN |
        OutputComponent.PERFORMANCE_METRICS |
        OutputComponent.OPTIMIZATION_TIPS |
        OutputComponent.SCHEMA_CONTEXT |
        OutputComponent.SAMPLE_DATA  # Limited samples, not full data
    ),
    UserRole.DEVELOPER: (
        OutputComponent.SQL_QUERY |
        OutputComponent.DOCUMENTATION |
        OutputComponent.EXAMPLES |
        OutputComponent.SCHEMA_CONTEXT
        # Note: No DATA_RESULTS for developers by default
    ),
    UserRole.QUERY_DEVELOPER: (
        OutputComponent.SQL_QUERY |
        OutputComponent.EXECUTION_PLAN |
        OutputComponent.PERFORMANCE_METRICS |
        OutputComponent.OPTIMIZATION_TIPS |
        OutputComponent.SCHEMA_CONTEXT
        # Note: No DATA_RESULTS for query developers by default
    )
}

@dataclass
class RouteDecision:
    """Query routing decision for schema-centric operations."""
    intent: QueryIntent
    components: OutputComponent
    user_role: UserRole
    primary_schema: str
    allowed_schemas: List[str]

    # Execution control
    needs_metadata_discovery: bool = True
    needs_query_generation: bool = True
    needs_execution: bool = True
    needs_plan_analysis: bool = False

    # Data handling
    data_limit: Optional[int] = 1000
    include_full_data: bool = False  # For business users who want all rows
    convert_to_dataframe: bool = False

    # Execution options
    execution_options: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8

# ============================================================================
# RESPONSE COMPONENTS
# ============================================================================

@dataclass
class DatabaseResponse:
    """Component-based database response."""
    query: Optional[str] = None
    data: Optional[Union[List[Dict], pd.DataFrame]] = None
    execution_plan: Optional[str] = None
    documentation: Optional[str] = None
    examples: Optional[List[str]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    schema_context: Optional[str] = None
    optimization_tips: Optional[List[str]] = None
    sample_data: Optional[List[Dict]] = None
    is_documentation: bool = False  # True if response is primarily documentation

    # Metadata
    row_count: int = 0
    execution_time_ms: float = 0.0
    components_included: OutputComponent = OutputComponent.NONE

    def to_markdown(self) -> str:
        """Convert response to markdown format."""
        sections = []

        if self.query and OutputComponent.SQL_QUERY in self.components_included:
            sections.append(f"## SQL Query\n\n```sql\n{self.query}\n```")

        if self.execution_plan and OutputComponent.EXECUTION_PLAN in self.components_included:
            sections.append(f"## Execution Plan\n\n```\n{self.execution_plan}\n```")

        if self.documentation and OutputComponent.DOCUMENTATION in self.components_included:
            sections.append(f"## Documentation\n\n{self.documentation}")

        if self.examples and OutputComponent.EXAMPLES in self.components_included:
            examples_text = "\n".join([f"```sql\n{ex}\n```" for ex in self.examples])
            sections.append(f"## Usage Examples\n\n{examples_text}")

        if self.performance_metrics and OutputComponent.PERFORMANCE_METRICS in self.components_included:
            metrics_text = "\n".join([f"- **{k}**: {v}" for k, v in self.performance_metrics.items()])
            sections.append(f"## Performance Metrics\n\n{metrics_text}")

        if self.optimization_tips and OutputComponent.OPTIMIZATION_TIPS in self.components_included:
            tips_text = "\n".join([f"- {tip}" for tip in self.optimization_tips])
            sections.append(f"## Optimization Tips\n\n{tips_text}")

        if self.schema_context and OutputComponent.SCHEMA_CONTEXT in self.components_included:
            sections.append(f"## Schema Context\n\n{self.schema_context}")

        if self.data is not None and OutputComponent.DATA_RESULTS in self.components_included:
            if isinstance(self.data, pd.DataFrame):
                sections.append(f"## Data Results (DataFrame)\n\n{self.data.head(10).to_markdown()}")
                if len(self.data) > 10:
                    sections.append(f"*Showing first 10 of {len(self.data)} rows*")
            else:
                sections.append(f"## Data Results\n\n{self.row_count} rows returned")

        if self.sample_data and OutputComponent.SAMPLE_DATA in self.components_included:
            sections.append("## Sample Data\n\n*First few rows for reference*")

        return "\n\n".join(sections)

    def to_json(self) -> str:
        """Convert DatabaseResponse to JSON format."""

        # Convert components to list of strings for JSON serialization
        components_list = [comp.name for comp in OutputComponent if comp in self.components_included]

        # Prepare data for JSON serialization
        response_dict = {
            "query": self.query,
            "documentation": self.documentation,
            "examples": self.examples or [],
            "schema_context": self.schema_context,
            "execution_plan": self.execution_plan,
            "optimization_tips": self.optimization_tips or [],
            "performance_metrics": self.performance_metrics or {},
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "components_included": components_list,
            "sample_data": self.sample_data or []
        }

        # Handle data serialization
        if self.data is not None:
            if isinstance(self.data, pd.DataFrame):
                response_dict["data"] = {
                    "type": "dataframe",
                    "shape": list(self.data.shape),
                    "columns": list(self.data.columns),
                    "dtypes": self.data.dtypes.astype(str).to_dict(),
                    "data": self.data.to_dict('records')  # Convert to list of dicts
                }
            elif isinstance(self.data, list):
                response_dict["data"] = {
                    "type": "list",
                    "count": len(self.data),
                    "data": self.data
                }
            else:
                response_dict["data"] = {
                    "type": str(type(self.data).__name__),
                    "data": str(self.data)
                }
        else:
            response_dict["data"] = None

        return json_encoder(response_dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for programmatic access."""
        return json_decoder(self.to_json())

    def has_component(self, component: OutputComponent) -> bool:
        """Check if response includes a specific component."""
        return component in self.components_included

    def get_data_summary(self) -> Dict[str, Any]:
        """Get summary information about the data."""
        summary = {
            "has_data": self.data is not None,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "data_type": None
        }

        if self.data is not None:
            if isinstance(self.data, pd.DataFrame):
                summary.update({
                    "data_type": "DataFrame",
                    "shape": list(self.data.shape),
                    "columns": list(self.data.columns),
                    "memory_usage": self.data.memory_usage(deep=True).sum()
                })
            elif isinstance(self.data, list):
                summary.update({
                    "data_type": "list",
                    "count": len(self.data)
                })

        return summary

# ============================================================================
# COMPONENT CONFIGURATION HELPERS
# ============================================================================

def get_default_components(user_role: UserRole) -> OutputComponent:
    """Get default output components for a user role."""
    return ROLE_COMPONENT_DEFAULTS.get(user_role, OutputComponent.BASIC_QUERY)

def customize_components(
    base_role: UserRole,
    add: Optional[OutputComponent] = None,
    remove: Optional[OutputComponent] = None
) -> OutputComponent:
    """Customize output components based on base role."""
    components = get_default_components(base_role)

    if add:
        components |= add

    if remove:
        components &= ~remove

    return components

def components_from_string(components_str: str) -> OutputComponent:
    """Parse components from comma-separated string."""
    component_map = {
        'sql': OutputComponent.SQL_QUERY,
        'plan': OutputComponent.EXECUTION_PLAN,
        'data': OutputComponent.DATA_RESULTS,
        'docs': OutputComponent.DOCUMENTATION,
        'examples': OutputComponent.EXAMPLES,
        'performance': OutputComponent.PERFORMANCE_METRICS,
        'schema': OutputComponent.SCHEMA_CONTEXT,
        'optimize': OutputComponent.OPTIMIZATION_TIPS,
        'samples': OutputComponent.SAMPLE_DATA,
        'dataframe': OutputComponent.DATAFRAME_OUTPUT
    }

    result = OutputComponent.NONE
    for comp in components_str.lower().split(','):
        comp = comp.strip()
        if comp in component_map:
            result |= component_map[comp]

    return result

# ============================================================================
# INTENT-TO-COMPONENT MAPPING
# ============================================================================

INTENT_COMPONENT_MAPPING: Dict[QueryIntent, OutputComponent] = {
    QueryIntent.SHOW_DATA: OutputComponent.DATA_RESULTS | OutputComponent.SAMPLE_DATA,
    QueryIntent.GENERATE_QUERY: OutputComponent.SQL_QUERY | OutputComponent.DOCUMENTATION,
    QueryIntent.ANALYZE_DATA: OutputComponent.SQL_QUERY | OutputComponent.DATA_RESULTS | OutputComponent.DOCUMENTATION,
    QueryIntent.EXPLORE_SCHEMA: OutputComponent.DOCUMENTATION | OutputComponent.SCHEMA_CONTEXT | OutputComponent.EXAMPLES,
    QueryIntent.VALIDATE_QUERY: OutputComponent.SQL_QUERY | OutputComponent.DOCUMENTATION | OutputComponent.OPTIMIZATION_TIPS,
    QueryIntent.OPTIMIZE_QUERY: OutputComponent.FULL_ANALYSIS,
    QueryIntent.EXPLAIN_METADATA: OutputComponent.DOCUMENTATION | OutputComponent.SCHEMA_CONTEXT | OutputComponent.EXAMPLES,
    QueryIntent.CREATE_EXAMPLES: OutputComponent.EXAMPLES | OutputComponent.SCHEMA_CONTEXT
}
