"""
QuerySource Tool for AI-Parrot

A tool that integrates QuerySource QS library to execute queries and return
structured data as pandas DataFrames or custom structured outputs.
"""
from typing import Dict, List, Any, Optional, Union, Type
from datetime import datetime, date, timedelta
import json
from pydantic import BaseModel, Field
import pandas as pd
from querysource.queries.qs import QS
from querysource.exceptions import DataNotFound  # pylint: disable=E0611
from .abstract import AbstractTool, ToolResult
from ..exceptions import ToolError  # pylint: disable=E0611


class QuerySourceInput(BaseModel):
    """Input schema for QuerySource tool."""

    query_slug: Optional[str] = Field(
        None,
        description="Slug identifier for pre-defined queries (e.g. 'epson_stores', 'sales_data')"
    )
    query: Optional[str] = Field(
        None,
        description="Raw SQL query string if no query_slug is provided (e.g. 'SELECT * FROM Account')"
    )
    conditions: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Query conditions including fields, filters, and group_by clauses"
    )
    additional_filters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional filters to apply to the query conditions"
    )
    driver: Optional[str] = Field(
        "db",
        description="Driver to use for the query (e.g. 'db', 'salesforce', 'pg', 'bigquery')"
    )
    return_format: Optional[str] = Field(
        "pandas",
        description="Return format: 'pandas', 'dict', 'json', or 'structured'"
    )
    structured_output_class: Optional[str] = Field(
        None,
        description="Name of the structured output class if return_format='structured'"
    )
    lazy: Optional[bool] = Field(
        True,
        description="Whether to use lazy loading for the query"
    )
    limit: Optional[int] = Field(
        None,
        description="Limit the number of rows returned by the query"
    )


class QSourceTool(AbstractTool):
    """
    Tool for executing QuerySource queries and returning structured data.

    This tool can:
    - Execute queries using query slugs or raw SQL
    - Apply conditions, filters, and grouping
    - Return results as pandas DataFrames, dictionaries, or structured outputs
    - Handle multiple data sources through different drivers
    """

    name: str = "QSourceTool"
    description: str = (
        "Execute QuerySource queries to retrieve and analyze data. "
        "Supports query slugs, raw SQL, filtering, grouping, and multiple output formats. "
        "Use this tool to access database content, generate reports, and perform data analysis."
    )
    args_schema = QuerySourceInput

    def __init__(
        self,
        default_driver: str = "db",
        available_structured_outputs: Optional[Dict[str, Type[BaseModel]]] = None,
        **kwargs
    ):
        """
        Initialize QuerySource tool.

        Args:
            default_driver: Default driver to use for queries
            available_structured_outputs: Dict mapping class names to Pydantic models
            **kwargs: Additional arguments passed to AbstractTool
        """
        super().__init__(**kwargs)
        self.default_driver = default_driver
        self.available_structured_outputs = available_structured_outputs or {}

    def get_input_schema(self) -> Dict[str, Any]:
        """Return the input schema for this tool."""
        return QuerySourceInput.model_json_schema()

    def get_date_range(self, days_back: int = 30) -> Dict[str, str]:
        """Get date range for the last N days."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        return {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d")
        }

    def build_date_filter(
        self,
        date_field: str = "date",
        days_back: int = 30
    ) -> Dict[str, List[str]]:
        """Build a date filter for queries."""
        date_range = self.get_date_range(days_back)
        return {
            date_field: [date_range["start_date"], date_range["end_date"]]
        }

    def _is_empty(self, result: Union[List[Dict[str, Any]], pd.DataFrame, None]) -> bool:
        """
        Safely check if a query result is empty.
        Handles DataFrames, lists, dicts, and None values properly.
        """
        if result is None:
            return True
        elif isinstance(result, (list, dict, tuple)):
            return len(result) == 0
        elif isinstance(result, pd.DataFrame):
            return result.empty
        else:
            try:
                return not bool(result)
            except ValueError:
                # Handle any other "truth value is ambiguous" errors
                return hasattr(result, '__len__') and len(result) == 0

    def _get_row_count(self, result):
        """Safely get row count from any result type."""
        if result is None:
            return 0
        elif isinstance(result, pd.DataFrame):
            return len(result)
        elif isinstance(result, (list, tuple)):
            return len(result)
        elif isinstance(result, dict):
            return 1
        else:
            try:
                return len(result)
            except (TypeError, AttributeError):
                return 1

    async def _execute(
        self,
        query_slug: Optional[str] = None,
        query: Optional[str] = None,
        conditions: Optional[Dict[str, Any]] = None,
        additional_filters: Optional[Dict[str, Any]] = None,
        driver: Optional[str] = None,
        return_format: str = "json",
        structured_output_class: Optional[str] = None,
        lazy: bool = True,
        limit: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        """
        Execute a QuerySource query and return structured results.
        """
        # Validate input
        if not query_slug and not query:
            return ToolResult(
                status="error",
                result=None,
                error="Either query_slug or query must be provided.",
                metadata={}
            )
        # Set defaults
        driver = driver or self.default_driver
        conditions = conditions or {}
        filters = conditions.get('filter', {})

        # Add additional filters
        if additional_filters:
            filters.update(additional_filters)

        conditions['filter'] = filters
        if limit:
            conditions['querylimit'] = limit
        try:
            # Create QS instance
            if query_slug:
                qry = QS(
                    slug=query_slug,
                    lazy=lazy,
                    conditions=conditions,
                    driver=driver
                )
                self.logger.debug(
                    f"Created QS query with slug: {query_slug}"
                )
            else:
                qry = QS(
                    query=query,
                    lazy=lazy,
                    conditions=conditions,
                    driver=driver
                )
                self.logger.debug(
                    f"Created QS query with raw SQL"
                )

            # Log query details
            self.logger.debug(
                f"Query conditions: {conditions}"
            )
            self.logger.debug(
                f"Using driver: {driver}"
            )

            # Build provider and execute query
            await qry.build_provider()
            result = None
            try:
                if return_format == 'pandas':
                    result, error = await qry.query(output_format='pandas')
                else:
                    result, error = await qry.query()
                if error:
                    raise ToolError(f"Query execution error: {error}")
            except DataNotFound as e:
                self.logger.error(f"Data not found: {str(e)}")
                return ToolResult(
                    status="empty",
                    result=None,
                    error=f"Data not found: {str(e)}",
                    metadata={
                        "query_slug": query_slug,
                        "driver": driver,
                        "conditions": conditions,
                        "return_format": return_format
                    }
                )
            except Exception as e:
                self.logger.error(
                    f"Query execution failed: {str(e)}"
                )
                return ToolResult(
                    status="error",
                    result=None,
                    error=f"Query execution failed: {str(e)}",
                    metadata={
                        "query_slug": query_slug,
                        "driver": driver,
                        "conditions": conditions,
                        "return_format": return_format,
                    }
                )


            if self._is_empty(result):
                return ToolResult(
                    status="empty",
                    result=None,
                    error="No data returned from query",
                    metadata={
                        "query_slug": query_slug,
                        "driver": driver,
                        "conditions": conditions,
                        "row_count": 0,
                        "return_format": return_format
                    }
                )

            # Process results based on return format
            processed_result = await self._process_results(
                result,
                return_format,
                structured_output_class
            )

            # Create metadata
            metadata = {
                "query_slug": query_slug,
                "raw_query": query if not query_slug else None,
                "driver": driver,
                "row_count": self._get_row_count(result),
                "return_format": return_format,
                "conditions": conditions
            }

            if return_format == "pandas" and isinstance(processed_result, pd.DataFrame):
                metadata.update({
                    "columns": list(processed_result.columns),
                    "shape": processed_result.shape,
                    "dtypes": processed_result.dtypes.to_dict()
                })

            return ToolResult(
                status="success",
                result=processed_result,
                error=None,
                metadata=metadata,
            )
        except Exception as e:
            self.logger.error(
                f"QuerySource tool execution failed: {str(e)}"
            )
            return ToolResult(
                status="error",
                result=None,
                error=f"QuerySource tool execution failed: {str(e)}",
                metadata={
                    "query_slug": query_slug,
                    "driver": driver,
                    "conditions": conditions,
                    "return_format": return_format
                }
            )

    async def _process_results(
        self,
        result: List[Dict[str, Any]],
        return_format: str,
        structured_output_class: Optional[str] = None
    ) -> Any:
        """
        Process query results based on the requested return format.
        """
        if return_format == "dict":
            return result

        elif return_format == "json":
            return json.dumps(result, default=self._json_serializer, indent=2)

        elif return_format == "pandas":
            # Convert to pandas DataFrame
            if self._is_empty(result):
                return pd.DataFrame()
            if isinstance(result, pd.DataFrame):
                return result

            # Ensure result is a list of dictionaries
            if isinstance(result, dict):
                result = [result]

            # Convert to DataFrame
            df = pd.DataFrame(result)

            # Convert datetime strings to datetime objects if possible
            for col in df.columns:
                if df[col].dtype == 'object':
                    try:
                        # Try to convert to datetime
                        df[col] = pd.to_datetime(df[col], errors='ignore')
                    except:
                        pass

            return df

        elif return_format == "structured":
            if not structured_output_class:
                raise ValueError(
                    "structured_output_class must be provided when return_format='structured'"
                )

            if structured_output_class not in self.available_structured_outputs:
                raise ValueError(
                    f"Unknown structured output class: {structured_output_class}"
                )

            output_class = self.available_structured_outputs[structured_output_class]

            # Convert list of dicts to list of structured objects
            structured_results = []
            for item in result:
                try:
                    structured_item = output_class(**dict(item))
                    structured_results.append(structured_item)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to convert item to {structured_output_class}: {e}"
                    )
                    # Keep original dict if conversion fails
                    structured_results.append(item)

            return structured_results

        else:
            raise ValueError(f"Unknown return_format: {return_format}")

    def _json_serializer(self, obj):
        """Custom JSON serializer for datetime objects."""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def add_structured_output(self, name: str, model_class: Type[BaseModel]):
        """Add a structured output class that can be used for result conversion."""
        self.available_structured_outputs[name] = model_class
        self.logger.info(f"Added structured output class: {name}")

    def list_available_outputs(self) -> List[str]:
        """List available structured output classes."""
        return list(self.available_structured_outputs.keys())

    async def execute_with_date_range(
        self,
        query_slug: str,
        date_field: str = "date",
        days_back: int = 30,
        additional_filters: Optional[Dict] = None,
        **kwargs
    ) -> ToolResult:
        """Execute query with automatic date range filtering."""

        conditions = kwargs.get('conditions', {})
        filters = conditions.get('filter', {})

        # Add date filter
        date_filter = self.build_date_filter(date_field, days_back)
        filters.update(date_filter)

        # Add additional filters
        if additional_filters:
            filters.update(additional_filters)

        conditions['filter'] = filters
        kwargs['conditions'] = conditions

        return await self._execute(query_slug=query_slug, **kwargs)
