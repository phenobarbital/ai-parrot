"""
InfluxDB Agent Implementation for AI-Parrot.

Concrete implementation of AbstractDbAgent for InfluxDB
with support for Flux query language and time-series data analysis.
"""

from typing import Dict, Any, List, Optional, Union
import asyncio
import re
from urllib.parse import urlparse
from datetime import datetime
from pydantic import Field
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point
from influxdb_client.client.write_api import SYNCHRONOUS

from .abstract import (
    AbstractDBAgent,
    DatabaseSchema,
    TableMetadata,
    QueryGenerationArgs
)
from ...tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema


class FluxQueryExecutionArgs(AbstractToolArgsSchema):
    """Arguments for Flux query execution."""
    query: str = Field(description="Flux query to execute")
    limit: Optional[int] = Field(
        default=1000, description="Maximum number of records to return")
    timeout: int = Field(default=30, description="Query timeout in seconds")


class InfluxMeasurementMetadata:
    """Metadata for InfluxDB measurements (equivalent to tables)."""
    def __init__(
        self,
        name: str,
        bucket: str,
        tags: List[str],
        fields: List[Dict[str, str]],
        time_range: Dict[str, Any],
        sample_records: List[Dict[str, Any]] = None
    ):
        self.name = name
        self.bucket = bucket
        self.tags = tags
        self.fields = fields
        self.time_range = time_range
        self.sample_records = sample_records or []


class InfluxDBAgent(AbstractDBAgent):
    """
    InfluxDB Agent for time-series database introspection and Flux query generation.

    Supports InfluxDB 2.x with Flux query language.
    """

    def __init__(
        self,
        name: str = "InfluxDBAgent",
        connection_string: str = None,
        token: str = None,
        org: str = None,
        bucket: str = None,
        max_sample_records: int = 10,
        default_time_range: str = "-30d",
        **kwargs
    ):
        """
        Initialize InfluxDB Agent.

        Args:
            name: Agent name
            connection_string: InfluxDB URL (e.g., 'http://localhost:8086')
            token: InfluxDB authentication token
            org: InfluxDB organization
            bucket: Default bucket name (can be overridden)
            max_sample_records: Maximum sample records per measurement
            default_time_range: Default time range for queries (e.g., '-30d', '-1h')
        """
        self.token = token
        self.org = org
        self.bucket = bucket
        self.max_sample_records = max_sample_records
        self.default_time_range = default_time_range
        self.client: Optional[InfluxDBClientAsync] = None
        self.measurements_cache: Dict[str, InfluxMeasurementMetadata] = {}

        super().__init__(
            name=name,
            connection_string=connection_string,
            schema_name=bucket,  # Use bucket as schema equivalent
            **kwargs
        )

        # Add InfluxDB-specific tools
        self._setup_influx_tools()

    def _setup_influx_tools(self):
        """Setup InfluxDB-specific tools."""
        # Add Flux query execution tool
        flux_execution_tool = FluxQueryExecutionTool(agent=self)
        self.tool_manager.register_tool(flux_execution_tool)

        # Add measurement exploration tool
        measurement_tool = MeasurementExplorationTool(agent=self)
        self.tool_manager.register_tool(measurement_tool)

    async def connect_database(self) -> None:
        """Connect to InfluxDB using async client."""
        if not self.connection_string:
            raise ValueError("InfluxDB URL is required")
        if not self.token:
            raise ValueError("InfluxDB token is required")
        if not self.org:
            raise ValueError("InfluxDB organization is required")

        try:
            self.client = InfluxDBClientAsync(
                url=self.connection_string,
                token=self.token,
                org=self.org,
                timeout=30000  # 30 seconds timeout
            )

            # Test connection by getting org info
            orgs_api = self.client.organizations_api()
            orgs = await orgs_api.find_organizations()

            if not any(org.name == self.org for org in orgs):
                raise ValueError(f"Organization '{self.org}' not found")

            self.logger.info(f"Successfully connected to InfluxDB at {self.connection_string}")

        except Exception as e:
            self.logger.error(f"Failed to connect to InfluxDB: {e}")
            raise

    async def extract_schema_metadata(self) -> DatabaseSchema:
        """Extract schema metadata from InfluxDB (buckets, measurements, fields, tags)."""
        if not self.client:
            await self.connect_database()

        try:
            # Get all buckets if no specific bucket is set
            buckets_to_analyze = []
            if self.bucket:
                buckets_to_analyze = [self.bucket]
            else:
                buckets_api = self.client.buckets_api()
                buckets = await buckets_api.find_buckets()
                buckets_to_analyze = [bucket.name for bucket in buckets if not bucket.name.startswith('_')]

            # Extract measurements from each bucket
            all_measurements = []
            for bucket_name in buckets_to_analyze:
                measurements = await self._extract_measurements_from_bucket(bucket_name)
                all_measurements.extend(measurements)

            # Convert measurements to TableMetadata format
            tables = self._convert_measurements_to_tables(all_measurements)

            schema_metadata = DatabaseSchema(
                database_name=self.org,
                database_type="influxdb",
                tables=tables,
                views=[],  # InfluxDB doesn't have views
                functions=[],  # InfluxDB doesn't have stored functions
                procedures=[],  # InfluxDB doesn't have stored procedures
                metadata={
                    "buckets_analyzed": buckets_to_analyze,
                    "total_measurements": len(all_measurements),
                    "extraction_timestamp": datetime.now().isoformat(),
                    "time_range_analyzed": self.default_time_range
                }
            )

            self.logger.info(
                f"Extracted metadata for {len(all_measurements)} measurements from {len(buckets_to_analyze)} buckets"
            )

            return schema_metadata

        except Exception as e:
            self.logger.error(f"Failed to extract InfluxDB schema metadata: {e}")
            raise

    async def _extract_measurements_from_bucket(self, bucket_name: str) -> List[InfluxMeasurementMetadata]:
        """Extract all measurements from a specific bucket."""
        query_api = self.client.query_api()

        # Query to get all measurements in the bucket
        measurements_query = f'''
            import "influxdata/influxdb/schema"
            schema.measurements(bucket: "{bucket_name}")
        '''

        try:
            result = await query_api.query(measurements_query)
            measurements_data = []

            for table in result:
                for record in table.records:
                    measurement_name = record.get_value()
                    if measurement_name:
                        # Get detailed metadata for this measurement
                        measurement_metadata = await self._extract_measurement_metadata(
                            bucket_name, measurement_name
                        )
                        measurements_data.append(measurement_metadata)

                        # Cache for later use
                        cache_key = f"{bucket_name}.{measurement_name}"
                        self.measurements_cache[cache_key] = measurement_metadata

            return measurements_data

        except Exception as e:
            self.logger.warning(f"Could not extract measurements from bucket {bucket_name}: {e}")
            return []

    async def _extract_measurement_metadata(
        self,
        bucket_name: str,
        measurement_name: str
    ) -> InfluxMeasurementMetadata:
        """Extract detailed metadata for a specific measurement."""
        query_api = self.client.query_api()

        try:
            # Get tag keys
            tags_query = f'''
                import "influxdata/influxdb/schema"
                schema.tagKeys(
                    bucket: "{bucket_name}",
                    predicate: (r) => r._measurement == "{measurement_name}",
                    start: {self.default_time_range}
                )
            '''

            tags_result = await query_api.query(tags_query)
            tags = []
            for table in tags_result:
                for record in table.records:
                    tag_key = record.get_value()
                    if tag_key:
                        tags.append(tag_key)

            # Get field keys and types
            fields_query = f'''
                import "influxdata/influxdb/schema"
                schema.fieldKeys(
                    bucket: "{bucket_name}",
                    predicate: (r) => r._measurement == "{measurement_name}",
                    start: {self.default_time_range}
                )
            '''

            fields_result = await query_api.query(fields_query)
            fields = []
            for table in fields_result:
                for record in table.records:
                    field_key = record.get_value()
                    if field_key:
                        # Try to determine field type by sampling
                        field_type = await self._determine_field_type(
                            bucket_name, measurement_name, field_key
                        )
                        fields.append({
                            "name": field_key,
                            "type": field_type
                        })

            # Get time range for this measurement
            time_range = await self._get_measurement_time_range(bucket_name, measurement_name)

            # Get sample records
            sample_records = await self._get_sample_records(bucket_name, measurement_name)

            return InfluxMeasurementMetadata(
                name=measurement_name,
                bucket=bucket_name,
                tags=tags,
                fields=fields,
                time_range=time_range,
                sample_records=sample_records
            )

        except Exception as e:
            self.logger.warning(
                f"Could not extract metadata for measurement {measurement_name}: {e}"
            )
            return InfluxMeasurementMetadata(
                name=measurement_name,
                bucket=bucket_name,
                tags=[],
                fields=[],
                time_range={},
                sample_records=[]
            )

    async def _determine_field_type(
        self,
        bucket_name: str,
        measurement_name: str,
        field_key: str
    ) -> str:
        """Determine the data type of a field by sampling."""
        query_api = self.client.query_api()

        type_query = f'''
            from(bucket: "{bucket_name}")
                |> range(start: {self.default_time_range})
                |> filter(fn: (r) => r._measurement == "{measurement_name}")
                |> filter(fn: (r) => r._field == "{field_key}")
                |> limit(n: 1)
        '''

        try:
            result = await query_api.query(type_query)
            for table in result:
                for record in table.records:
                    value = record.get_value()
                    if isinstance(value, bool):
                        return "boolean"
                    elif isinstance(value, int):
                        return "integer"
                    elif isinstance(value, float):
                        return "float"
                    elif isinstance(value, str):
                        return "string"
                    else:
                        return "unknown"
        except:
            pass

        return "unknown"

    async def _get_measurement_time_range(
        self,
        bucket_name: str,
        measurement_name: str
    ) -> Dict[str, Any]:
        """Get the time range for a measurement."""
        query_api = self.client.query_api()

        # Get earliest and latest timestamps
        range_query = f'''
            data = from(bucket: "{bucket_name}")
                |> range(start: {self.default_time_range})
                |> filter(fn: (r) => r._measurement == "{measurement_name}")

            earliest = data |> first() |> keep(columns: ["_time"]) |> set(key: "stat", value: "earliest")
            latest = data |> last() |> keep(columns: ["_time"]) |> set(key: "stat", value: "latest")

            union(tables: [earliest, latest])
        '''

        try:
            result = await query_api.query(range_query)
            time_range = {}

            for table in result:
                for record in table.records:
                    stat = record.values.get("stat")
                    time_value = record.get_time()
                    if stat and time_value:
                        time_range[stat] = time_value.isoformat()

            return time_range

        except Exception as e:
            self.logger.warning(f"Could not get time range for {measurement_name}: {e}")
            return {}

    async def _get_sample_records(
        self,
        bucket_name: str,
        measurement_name: str
    ) -> List[Dict[str, Any]]:
        """Get sample records from a measurement."""
        query_api = self.client.query_api()

        sample_query = f'''
            from(bucket: "{bucket_name}")
                |> range(start: {self.default_time_range})
                |> filter(fn: (r) => r._measurement == "{measurement_name}")
                |> limit(n: {self.max_sample_records})
        '''

        try:
            result = await query_api.query(sample_query)
            sample_records = []

            for table in result:
                for record in table.records:
                    record_dict = {
                        "_time": record.get_time().isoformat() if record.get_time() else None,
                        "_measurement": record.get_measurement(),
                        "_field": record.get_field(),
                        "_value": record.get_value()
                    }
                    # Add tag values
                    for key, value in record.values.items():
                        if not key.startswith('_') and key not in ['result', 'table']:
                            record_dict[key] = value

                    sample_records.append(record_dict)

            return sample_records[:self.max_sample_records]

        except Exception as e:
            self.logger.warning(f"Could not get sample records for {measurement_name}: {e}")
            return []

    def _convert_measurements_to_tables(
        self,
        measurements: List[InfluxMeasurementMetadata]
    ) -> List[TableMetadata]:
        """Convert InfluxDB measurements to TableMetadata format."""
        tables = []

        for measurement in measurements:
            # Create columns list combining fields and tags
            columns = []

            # Add time column (always present in InfluxDB)
            columns.append({
                "name": "_time",
                "type": "timestamp",
                "nullable": False,
                "description": "Timestamp of the data point"
            })

            # Add measurement column
            columns.append({
                "name": "_measurement",
                "type": "string",
                "nullable": False,
                "description": "Measurement name"
            })

            # Add field columns
            for field in measurement.fields:
                columns.append({
                    "name": field["name"],
                    "type": field["type"],
                    "nullable": True,
                    "description": f"Field: {field['name']}"
                })

            # Add tag columns
            for tag in measurement.tags:
                columns.append({
                    "name": tag,
                    "type": "string",
                    "nullable": True,
                    "description": f"Tag: {tag}"
                })

            # Create table metadata
            table_metadata = TableMetadata(
                name=measurement.name,
                schema=measurement.bucket,
                columns=columns,
                primary_keys=["_time"],  # Time is essentially the primary key
                foreign_keys=[],  # InfluxDB doesn't have foreign keys
                indexes=[],  # InfluxDB handles indexing automatically
                description=f"InfluxDB measurement in bucket '{measurement.bucket}'",
                sample_data=measurement.sample_records
            )

            tables.append(table_metadata)

        return tables

    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT"
    ) -> Dict[str, Any]:
        """Generate Flux query from natural language."""
        try:
            # Get schema context for the query
            schema_context = await self._get_schema_context_for_query(
                natural_language_query, target_tables
            )

            # Build Flux query generation prompt
            prompt = self._build_flux_query_prompt(
                natural_language_query=natural_language_query,
                schema_context=schema_context,
                default_time_range=self.default_time_range
            )

            # Generate query using LLM
            response = await self.llm_client.generate_response(
                prompt=prompt,
                model=self.model_name,
                temperature=0.1
            )

            # Extract Flux query from response
            flux_query = self._extract_flux_from_response(response.output)

            # Validate query syntax (basic validation)
            validation_result = await self._validate_flux_syntax(flux_query)

            result = {
                "query": flux_query,
                "query_type": "flux",
                "measurements_used": self._extract_measurements_from_query(flux_query),
                "schema_context_used": len(schema_context),
                "validation": validation_result,
                "natural_language_input": natural_language_query,
                "default_time_range": self.default_time_range
            }

            return result

        except Exception as e:
            self.logger.error(f"Failed to generate Flux query: {e}")
            raise

    def _build_flux_query_prompt(
        self,
        natural_language_query: str,
        schema_context: List[Dict[str, Any]],
        default_time_range: str
    ) -> str:
        """Build prompt for Flux query generation."""
        prompt = f"""
You are an expert InfluxDB Flux query developer.
Generate a Flux query based on the natural language request and the provided schema information.

Natural Language Request: {natural_language_query}

Available Measurements and Schema:
"""

        for i, context in enumerate(schema_context[:3], 1):
            prompt += f"\n{i}. {context.get('content', '')}\n"

        prompt += f"""

InfluxDB Flux Query Guidelines:
1. Always start with from(bucket: "bucket_name")
2. Use range() to specify time range (default: {default_time_range})
3. Use filter() to specify measurements and field conditions
4. Use aggregation functions like mean(), sum(), count(), etc. for time-series analysis
5. Use group() to group by tags or time windows
6. Use window() for time-based aggregations
7. Use |> (pipe) operator to chain operations
8. Return only the Flux query without explanations or markdown formatting

Example Flux query structure:
```
from(bucket: "my_bucket")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "measurement_name")
    |> filter(fn: (r) => r._field == "field_name")
    |> aggregateWindow(every: 5m, fn: mean)
```

Default time range: {default_time_range}

Flux Query:"""

        return prompt

    def _extract_flux_from_response(self, response_text: str) -> str:
        """Extract Flux query from LLM response."""
        # Remove markdown code blocks if present
        if "```" in response_text:
            lines = response_text.split('\n')
            flux_lines = []
            in_code_block = False

            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                elif in_code_block:
                    flux_lines.append(line)

            return '\n'.join(flux_lines).strip()
        else:
            return response_text.strip()

    def _extract_measurements_from_query(self, query: str) -> List[str]:
        """Extract measurement names from Flux query."""
        # Find measurement names in filter expressions
        pattern = r'r\._measurement\s*==\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern, query)

        return list(set(matches))

    async def _validate_flux_syntax(self, query: str) -> Dict[str, Any]:
        """Validate Flux query syntax."""
        try:
            # Basic validation - check for required components
            if not query.strip():
                return {
                    "valid": False,
                    "error": "Empty query",
                    "message": "Query cannot be empty"
                }

            if "from(bucket:" not in query:
                return {
                    "valid": False,
                    "error": "Missing from() function",
                    "message": "Flux query must start with from(bucket:...)"
                }

            # Try to execute a dry run if possible
            if self.client:
                query_api = self.client.query_api()
                # We could add a limit to make it safe
                test_query = f"{query} |> limit(n: 1)"
                try:
                    await query_api.query(test_query)
                    return {
                        "valid": True,
                        "error": None,
                        "message": "Query syntax is valid"
                    }
                except Exception as e:
                    return {
                        "valid": False,
                        "error": str(e),
                        "message": "Query syntax validation failed"
                    }

            return {
                "valid": True,
                "error": None,
                "message": "Basic syntax validation passed"
            }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "message": "Query validation error"
            }

    async def execute_query(self, query: str, limit: Optional[int] = 1000) -> Dict[str, Any]:
        """Execute Flux query against InfluxDB."""
        try:
            if not self.client:
                await self.connect_database()

            query_api = self.client.query_api()

            # Add limit if specified and not already present
            if limit and "limit(n:" not in query:
                query = f"{query} |> limit(n: {limit})"

            # Execute query
            result = await query_api.query(query)

            # Process results
            records = []
            columns = set()

            for table in result:
                for record in table.records:
                    record_dict = {}

                    # Add standard InfluxDB columns
                    if record.get_time():
                        record_dict["_time"] = record.get_time().isoformat()
                    if record.get_measurement():
                        record_dict["_measurement"] = record.get_measurement()
                    if record.get_field():
                        record_dict["_field"] = record.get_field()
                    if record.get_value() is not None:
                        record_dict["_value"] = record.get_value()

                    # Add all other values (tags, etc.)
                    for key, value in record.values.items():
                        if key not in ['result', 'table'] and not key.startswith('_start') and not key.startswith('_stop'):
                            record_dict[key] = value

                    records.append(record_dict)
                    columns.update(record_dict.keys())

            return {
                "success": True,
                "data": records,
                "columns": list(columns),
                "record_count": len(records),
                "query": query
            }

        except Exception as e:
            self.logger.error(f"Flux query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }

    async def close(self):
        """Close InfluxDB client connection."""
        if self.client:
            await self.client.close()


class FluxQueryExecutionTool(AbstractTool):
    """Tool for executing Flux queries against InfluxDB."""

    name = "execute_flux_query"
    description = "Execute Flux queries against the InfluxDB database"
    args_schema = FluxQueryExecutionArgs

    def __init__(self, agent: InfluxDBAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        query: str,
        limit: Optional[int] = 1000,
        timeout: int = 30
    ) -> ToolResult:
        """Execute Flux query."""
        try:
            result = await self.agent.execute_query(query, limit)

            return ToolResult(
                status="success" if result["success"] else "error",
                result=result,
                error=result.get("error"),
                metadata={
                    "query": query,
                    "limit": limit,
                    "timeout": timeout
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"query": query}
            )


class MeasurementExplorationTool(AbstractTool):
    """Tool for exploring InfluxDB measurements and their metadata."""

    name = "explore_measurements"
    description = "Explore available measurements, fields, and tags in InfluxDB"

    class ExplorationArgs(AbstractToolArgsSchema):
        """Exploration arguments schema."""
        bucket: Optional[str] = Field(default=None, description="Bucket to explore (optional)")
        measurement: Optional[str] = Field(default=None, description="Specific measurement to explore")
        show_sample_data: bool = Field(default=True, description="Include sample data in results")

    args_schema = ExplorationArgs

    def __init__(self, agent: InfluxDBAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        bucket: Optional[str] = None,
        measurement: Optional[str] = None,
        show_sample_data: bool = True
    ) -> ToolResult:
        """Explore measurements in InfluxDB."""
        try:
            if not self.agent.schema_metadata:
                await self.agent.extract_schema_metadata()

            exploration_result = {
                "buckets": [],
                "measurements": [],
                "total_measurements": 0
            }

            # Filter by bucket if specified
            tables_to_explore = self.agent.schema_metadata.tables
            if bucket:
                tables_to_explore = [t for t in tables_to_explore if t.schema == bucket]

            # Filter by measurement if specified
            if measurement:
                tables_to_explore = [t for t in tables_to_explore if t.name == measurement]

            # Get unique buckets
            buckets = list(set(t.schema for t in tables_to_explore))
            exploration_result["buckets"] = buckets

            # Build measurement details
            for table in tables_to_explore:
                measurement_info = {
                    "name": table.name,
                    "bucket": table.schema,
                    "description": table.description,
                    "fields": [col for col in table.columns if col["description"] and col["description"].startswith("Field:")],
                    "tags": [col for col in table.columns if col["description"] and col["description"].startswith("Tag:")],
                    "total_columns": len(table.columns)
                }

                if show_sample_data and table.sample_data:
                    measurement_info["sample_data"] = table.sample_data[:5]  # Limit sample data

                exploration_result["measurements"].append(measurement_info)

            exploration_result["total_measurements"] = len(exploration_result["measurements"])

            return ToolResult(
                status="success",
                result=exploration_result,
                metadata={
                    "bucket_filter": bucket,
                    "measurement_filter": measurement,
                    "show_sample_data": show_sample_data
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "bucket": bucket,
                    "measurement": measurement
                }
            )


# Factory function for creating InfluxDB agents
def create_influxdb_agent(
    url: str,
    token: str,
    org: str,
    bucket: str = None,
    **kwargs
) -> InfluxDBAgent:
    """
    Factory function to create InfluxDB agents.

    Args:
        url: InfluxDB URL (e.g., 'http://localhost:8086')
        token: InfluxDB authentication token
        org: InfluxDB organization
        bucket: Default bucket name (optional)
        **kwargs: Additional arguments for the agent

    Returns:
        Configured InfluxDBAgent instance
    """
    return InfluxDBAgent(
        connection_string=url,
        token=token,
        org=org,
        bucket=bucket,
        **kwargs
    )


# Example usage
"""
# Create InfluxDB agent
influx_agent = create_influxdb_agent(
    url='http://localhost:8086',
    token='your-influxdb-token',
    org='your-org',
    bucket='your-bucket'
)

# Initialize schema
await influx_agent.initialize_schema()

# Generate query from natural language
result = await influx_agent.generate_query(
    "Show me the average temperature over the last hour grouped by location"
)

# Execute the generated query
execution_result = await influx_agent.execute_query(result['query'])

# Explore available measurements
exploration_tool = MeasurementExplorationTool(agent=influx_agent)
exploration_result = await exploration_tool._arun(bucket='my_bucket')
"""
