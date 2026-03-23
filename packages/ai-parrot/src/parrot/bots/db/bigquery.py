"""
BigQuery Agent Implementation for AI-Parrot.

Concrete implementation of AbstractDBAgent for Google BigQuery
with support for SQL query language and BigQuery-specific features.
"""

from typing import Dict, Any, List, Optional, Union
import asyncio
from datetime import datetime
from pydantic import Field
from google.cloud import bigquery as bq
from google.oauth2 import service_account
from google.cloud.exceptions import NotFound
from navconfig import config

from .abstract import (
    AbstractDBAgent,
    DatabaseSchema,
    TableMetadata,
)
from ...tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema


class BigQueryQueryExecutionArgs(AbstractToolArgsSchema):
    """Arguments for BigQuery query execution."""
    query: str = Field(description="SQL query to execute")
    limit: Optional[int] = Field(
        default=1000, description="Maximum number of rows to return"
    )
    use_legacy_sql: bool = Field(
        default=False, description="Use legacy SQL instead of standard SQL"
    )


class DatasetMetadata:
    """Metadata for BigQuery datasets."""
    def __init__(
        self,
        dataset_id: str,
        project_id: str,
        location: str,
        tables: List[str],
        description: str = None
    ):
        self.dataset_id = dataset_id
        self.project_id = project_id
        self.location = location
        self.tables = tables
        self.description = description


class BigQueryAgent(AbstractDBAgent):
    """
    BigQuery Agent for data warehouse introspection and SQL query generation.

    Supports Google BigQuery with standard SQL and BigQuery-specific features.
    """

    def __init__(
        self,
        name: str = "BigQueryAgent",
        project_id: str = None,
        credentials_file: str = None,
        credentials: Union[str, Dict[str, Any]] = None,
        dataset: str = None,
        location: str = "US",
        max_sample_rows: int = 10,
        **kwargs
    ):
        """
        Initialize BigQuery Agent.

        Args:
            name: Agent name
            project_id: Google Cloud project ID
            credentials_file: Path to service account credentials JSON file
            credentials: Credentials dict or connection string (overrides individual params)
            dataset: Default dataset name
            location: BigQuery location/region (default: US)
            max_sample_rows: Maximum sample rows per table
        """
        self.project_id = project_id
        self.credentials_file = credentials_file
        self.dataset = dataset
        self.location = location
        self.max_sample_rows = max_sample_rows
        self.client: Optional[bq.Client] = None
        self.credentials_obj = None
        self.datasets_cache: Dict[str, DatasetMetadata] = {}

        # Get default credentials if not provided
        if not credentials and not all([project_id, credentials_file]):
            credentials = self._get_default_credentials()

        super().__init__(
            name=name,
            credentials=credentials,
            schema_name=dataset,
            **kwargs
        )

        # Add BigQuery-specific tools
        self._setup_bigquery_tools()

    def _get_default_credentials(self) -> Dict[str, Any]:
        """Get default credentials from config (similar to DatabaseQueryTool)."""
        return {
            'credentials_file': config.get('GOOGLE_APPLICATION_CREDENTIALS'),
            'project_id': config.get('GOOGLE_CLOUD_PROJECT'),
        }

    def _setup_bigquery_tools(self):
        """Setup BigQuery-specific tools."""
        # Add query execution tool
        query_execution_tool = BigQueryQueryExecutionTool(agent=self)
        self.tool_manager.register_tool(query_execution_tool)

        # Add dataset exploration tool
        dataset_exploration_tool = DatasetExplorationTool(agent=self)
        self.tool_manager.register_tool(dataset_exploration_tool)

    async def connect_database(self) -> None:
        """Connect to BigQuery using service account credentials."""
        # Parse credentials
        if isinstance(self.credentials, dict):
            creds = self.credentials.copy()
            self.project_id = creds.get('project_id', self.project_id)
            self.credentials_file = creds.get('credentials_file', self.credentials_file)
            self.dataset = creds.get('dataset', self.dataset)

        try:
            # Initialize BigQuery client
            if self.credentials_file:
                self.credentials_obj = service_account.Credentials.from_service_account_file(
                    self.credentials_file
                )
                if not self.project_id:
                    self.project_id = self.credentials_obj.project_id
                
                self.client = bq.Client(
                    credentials=self.credentials_obj,
                    project=self.project_id
                )
            else:
                # Use application default credentials
                if not self.project_id:
                    raise ValueError("BigQuery project_id is required")
                self.client = bq.Client(project=self.project_id)

            # Test connection by listing datasets (limit to 1)
            datasets = list(self.client.list_datasets(max_results=1))
            
            self.logger.info(
                f"Successfully connected to BigQuery project: {self.project_id}"
            )

        except Exception as e:
            self.logger.error(f"Failed to connect to BigQuery: {e}")
            raise

    async def extract_schema_metadata(self) -> DatabaseSchema:
        """Extract schema metadata from BigQuery (datasets, tables, columns)."""
        if not self.client:
            await self.connect_database()

        try:
            # Get datasets to analyze
            datasets_to_analyze = []
            if self.dataset:
                datasets_to_analyze = [self.dataset]
            else:
                # List all datasets in the project
                datasets = self.client.list_datasets()
                datasets_to_analyze = [dataset.dataset_id for dataset in datasets]

            # Extract tables from each dataset
            all_tables = []
            for dataset_id in datasets_to_analyze:
                tables = await self._extract_tables_from_dataset(dataset_id)
                all_tables.extend(tables)

            schema_metadata = DatabaseSchema(
                database_name=self.project_id,
                database_type="bigquery",
                tables=all_tables,
                views=[],  # Views are included in tables
                functions=[],
                procedures=[],
                metadata={
                    "datasets_analyzed": datasets_to_analyze,
                    "total_tables": len(all_tables),
                    "extraction_timestamp": datetime.now().isoformat(),
                    "location": self.location
                }
            )

            self.logger.info(
                f"Extracted metadata for {len(all_tables)} tables from {len(datasets_to_analyze)} datasets"
            )

            return schema_metadata

        except Exception as e:
            self.logger.error(f"Failed to extract BigQuery schema metadata: {e}")
            raise

    async def _extract_tables_from_dataset(
        self,
        dataset_id: str
    ) -> List[TableMetadata]:
        """Extract all tables from a specific dataset."""
        try:
            dataset_ref = f"{self.project_id}.{dataset_id}"
            tables = self.client.list_tables(dataset_ref)

            table_metadata_list = []
            for table in tables:
                # Get full table details
                table_ref = self.client.get_table(table.reference)
                
                # Extract table metadata
                table_metadata = await self._extract_table_metadata(
                    dataset_id, table_ref
                )
                table_metadata_list.append(table_metadata)

            return table_metadata_list

        except NotFound:
            self.logger.warning(f"Dataset {dataset_id} not found")
            return []
        except Exception as e:
            self.logger.warning(f"Could not extract tables from dataset {dataset_id}: {e}")
            return []

    async def _extract_table_metadata(
        self,
        dataset_id: str,
        table: bq.Table
    ) -> TableMetadata:
        """Extract detailed metadata for a specific table."""
        try:
            # Extract columns
            columns = []
            for field in table.schema:
                columns.append({
                    "name": field.name,
                    "type": field.field_type,
                    "nullable": field.mode != "REQUIRED",
                    "description": field.description or ""
                })

            # Get sample data
            sample_data = []
            try:
                query = f"""
                    SELECT * 
                    FROM `{self.project_id}.{dataset_id}.{table.table_id}` 
                    LIMIT {self.max_sample_rows}
                """
                query_job = self.client.query(query)
                results = query_job.result()
                
                for row in results:
                    sample_data.append(dict(row))
                    
            except Exception as e:
                self.logger.debug(f"Could not get sample data for {table.table_id}: {e}")

            # Determine if it's a view
            is_view = table.table_type == "VIEW"

            return TableMetadata(
                name=table.table_id,
                schema=dataset_id,
                columns=columns,
                primary_keys=[],  # BigQuery doesn't enforce primary keys
                foreign_keys=[],  # BigQuery doesn't enforce foreign keys
                indexes=[],  # BigQuery handles indexing automatically
                description=table.description or f"BigQuery {'view' if is_view else 'table'} in dataset {dataset_id}",
                sample_data=sample_data
            )

        except Exception as e:
            self.logger.warning(
                f"Could not extract metadata for table {table.table_id}: {e}"
            )
            return TableMetadata(
                name=table.table_id,
                schema=dataset_id,
                columns=[],
                primary_keys=[],
                foreign_keys=[],
                indexes=[],
                description="",
                sample_data=[]
            )

    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT"
    ) -> Dict[str, Any]:
        """Generate BigQuery SQL from natural language."""
        try:
            # Get schema context for the query
            schema_context = []
            if self.schema_metadata:
                # Filter tables based on target_tables
                tables_to_use = self.schema_metadata.tables
                if target_tables:
                    tables_to_use = [
                        t for t in tables_to_use if t.name in target_tables
                    ]
                
                for table in tables_to_use[:5]:  # Limit to top 5
                    schema_context.append({
                        'table': f"{table.schema}.{table.name}",
                        'columns': [
                            {'name': col['name'], 'type': col['type']}
                            for col in table.columns
                        ],
                        'sample_count': len(table.sample_data)
                    })

            # Build SQL query generation prompt
            prompt = self._build_sql_query_prompt(
                natural_language_query=natural_language_query,
                schema_context=schema_context
            )

            # Generate query using LLM
            async with self._llm as client:
                response = await client.ask(
                    prompt=prompt,
                    model=self._llm_model,
                    temperature=0.1
                )

            # Extract SQL query from response
            sql_query = self._extract_sql_from_response(response.output or response.response)

            result = {
                "query": sql_query,
                "query_type": "sql",
                "tables_used": target_tables or [],
                "schema_context_used": len(schema_context),
                "natural_language_input": natural_language_query
            }

            return result

        except Exception as e:
            self.logger.error(f"Failed to generate SQL query: {e}")
            raise

    def _build_sql_query_prompt(
        self,
        natural_language_query: str,
        schema_context: List[Dict[str, Any]]
    ) -> str:
        """Build prompt for SQL query generation."""
        prompt = f"""
You are an expert BigQuery SQL developer.
Generate a BigQuery SQL query based on the natural language request and the provided schema information.

Natural Language Request: {natural_language_query}

Available Tables and Schema:
"""
        for i, context in enumerate(schema_context, 1):
            prompt += f"\n{i}. Table: {context['table']}\n"
            prompt += "   Columns:\n"
            for col in context['columns'][:10]:  # Limit columns shown
                prompt += f"     - {col['name']} ({col['type']})\n"

        prompt += f"""

BigQuery SQL Guidelines:
1. Use standard SQL syntax (not legacy SQL)
2. Fully qualify table names: `project.dataset.table`
3. Use backticks for table/column names with special characters
4. Common BigQuery functions: STRING_AGG, ARRAY_AGG, APPROX_COUNT_DISTINCT
5. Use STRUCT and ARRAY types when appropriate
6. For date/time: CURRENT_TIMESTAMP(), DATE_SUB(), TIMESTAMP_DIFF()
7. Use WITH clauses (CTEs) for complex queries
8. Return only the SQL query without explanations or markdown formatting

Project ID: {self.project_id}

SQL Query:"""

        return prompt

    def _extract_sql_from_response(self, response_text: str) -> str:
        """Extract SQL query from LLM response."""
        # Remove markdown code blocks if present
        if "```" in response_text:
            lines = response_text.split('\n')
            sql_lines = []
            in_code_block = False

            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                elif in_code_block:
                    sql_lines.append(line)

            return '\n'.join(sql_lines).strip()
        else:
            return response_text.strip()

    async def execute_query(
        self,
        query: str,
        limit: Optional[int] = 1000
    ) -> Dict[str, Any]:
        """Execute SQL query against BigQuery."""
        try:
            if not self.client:
                await self.connect_database()

            # Add limit if not present
            query_upper = query.upper().strip()
            if limit and 'LIMIT' not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {limit}"

            # Configure query job
            job_config = bq.QueryJobConfig()
            job_config.use_legacy_sql = False

            # Execute query
            query_job = self.client.query(query, job_config=job_config)
            results = query_job.result()

            # Process results
            rows = []
            columns = []
            
            if results.schema:
                columns = [field.name for field in results.schema]
                
            for row in results:
                rows.append(dict(row))

            return {
                "success": True,
                "data": rows,
                "columns": columns,
                "record_count": len(rows),
                "query": query,
                "total_bytes_processed": query_job.total_bytes_processed,
                "total_bytes_billed": query_job.total_bytes_billed
            }

        except Exception as e:
            self.logger.error(f"BigQuery query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }

    async def close(self):
        """Close BigQuery client connection."""
        if self.client:
            self.client.close()


class BigQueryQueryExecutionTool(AbstractTool):
    """Tool for executing SQL queries against BigQuery."""

    name = "execute_bigquery_query"
    description = "Execute SQL queries against Google BigQuery"
    args_schema = BigQueryQueryExecutionArgs

    def __init__(self, agent: BigQueryAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        query: str,
        limit: Optional[int] = 1000,
        use_legacy_sql: bool = False
    ) -> ToolResult:
        """Execute BigQuery query."""
        try:
            result = await self.agent.execute_query(query, limit)

            return ToolResult(
                status="success" if result["success"] else "error",
                result=result,
                error=result.get("error"),
                metadata={
                    "query": query,
                    "limit": limit,
                    "bytes_processed": result.get("total_bytes_processed"),
                    "bytes_billed": result.get("total_bytes_billed")
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"query": query}
            )


class DatasetExplorationTool(AbstractTool):
    """Tool for exploring BigQuery datasets and tables."""

    name = "explore_bigquery_datasets"
    description = "Explore available datasets and tables in BigQuery"

    class ExplorationArgs(AbstractToolArgsSchema):
        """Exploration arguments schema."""
        dataset: Optional[str] = Field(
            default=None, description="Specific dataset to explore"
        )
        table: Optional[str] = Field(
            default=None, description="Specific table to explore"
        )
        show_sample_data: bool = Field(
            default=True, description="Include sample data in results"
        )

    args_schema = ExplorationArgs

    def __init__(self, agent: BigQueryAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        dataset: Optional[str] = None,
        table: Optional[str] = None,
        show_sample_data: bool = True
    ) -> ToolResult:
        """Explore datasets/tables in BigQuery."""
        try:
            if not self.agent.schema_metadata:
                await self.agent.extract_schema_metadata()

            exploration_result = {
                "datasets": [],
                "tables": [],
                "total_tables": 0
            }

            # Filter tables
            tables_to_explore = self.agent.schema_metadata.tables
            if dataset:
                tables_to_explore = [t for t in tables_to_explore if t.schema == dataset]
            if table:
                tables_to_explore = [t for t in tables_to_explore if t.name == table]

            # Get unique datasets
            datasets = list(set(t.schema for t in tables_to_explore))
            exploration_result["datasets"] = datasets

            # Build table information
            for tbl in tables_to_explore:
                table_info = {
                    "name": tbl.name,
                    "dataset": tbl.schema,
                    "full_name": f"{tbl.schema}.{tbl.name}",
                    "columns": [
                        {'name': col['name'], 'type': col['type']}
                        for col in tbl.columns
                    ],
                    "description": tbl.description
                }

                if show_sample_data and tbl.sample_data:
                    table_info["sample_data"] = tbl.sample_data[:3]

                exploration_result["tables"].append(table_info)

            exploration_result["total_tables"] = len(exploration_result["tables"])

            return ToolResult(
                status="success",
                result=exploration_result,
                metadata={
                    "project": self.agent.project_id,
                    "dataset_filter": dataset,
                    "table_filter": table
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e)
            )
