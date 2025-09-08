"""
Elasticsearch/DocumentDB Agent Implementation for AI-Parrot.

Concrete implementation of AbstractDbAgent for Elasticsearch
with support for document-based queries and aggregations.
"""

from typing import Dict, Any, List, Optional, Union
import asyncio
import json
from datetime import datetime
from urllib.parse import urlparse
from pydantic import Field
from elasticsearch import AsyncElasticsearch
from .abstract import (
    AbstractDBAgent,
    DatabaseSchema,
    TableMetadata,
    QueryGenerationArgs
)
from ...tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema


class ElasticsearchQueryArgs(AbstractToolArgsSchema):
    """Arguments for Elasticsearch query execution."""
    query: Union[str, Dict[str, Any]] = Field(description="Elasticsearch query (JSON or Query DSL)")
    index: Optional[str] = Field(default=None, description="Specific index to query")
    size: int = Field(default=100, description="Maximum number of documents to return")
    timeout: str = Field(default="30s", description="Query timeout")
    explain: bool = Field(default=False, description="Include query explanation")


class IndexMetadata:
    """Metadata for an Elasticsearch index (equivalent to a table)."""
    def __init__(
        self,
        name: str,
        mapping: Dict[str, Any],
        settings: Dict[str, Any],
        aliases: List[str] = None,
        doc_count: int = 0,
        size_in_bytes: int = 0,
        sample_documents: List[Dict[str, Any]] = None
    ):
        self.name = name
        self.mapping = mapping
        self.settings = settings
        self.aliases = aliases or []
        self.doc_count = doc_count
        self.size_in_bytes = size_in_bytes
        self.sample_documents = sample_documents or []


class ElasticDbAgent(AbstractDBAgent):
    """
    Elasticsearch Agent for document database introspection and query generation.

    Supports Elasticsearch with Query DSL and aggregations.
    """

    def __init__(
        self,
        name: str = "ElasticsearchAgent",
        connection_string: str = None,
        username: str = None,
        password: str = None,
        api_key: str = None,
        cloud_id: str = None,
        max_sample_docs: int = 10,
        verify_certs: bool = True,
        **kwargs
    ):
        """
        Initialize Elasticsearch Agent.

        Args:
            name: Agent name
            connection_string: Elasticsearch URL (e.g., 'http://localhost:9200')
            username: Username for authentication
            password: Password for authentication
            api_key: API key for authentication (alternative to username/password)
            cloud_id: Elastic Cloud ID (for Elastic Cloud)
            max_sample_docs: Maximum sample documents per index
            verify_certs: Whether to verify SSL certificates
        """
        self.username = username
        self.password = password
        self.api_key = api_key
        self.cloud_id = cloud_id
        self.max_sample_docs = max_sample_docs
        self.verify_certs = verify_certs
        self.client: Optional[AsyncElasticsearch] = None
        self.indices_cache: Dict[str, IndexMetadata] = {}

        super().__init__(
            name=name,
            connection_string=connection_string,
            schema_name="elasticsearch",  # Elasticsearch doesn't have schemas like SQL
            **kwargs
        )

        # Add Elasticsearch-specific tools
        self._setup_elastic_tools()

    def _setup_elastic_tools(self):
        """Setup Elasticsearch-specific tools."""
        # Add query execution tool
        es_query_tool = ElasticsearchQueryTool(agent=self)
        self.add_tool(es_query_tool)

        # Add index exploration tool
        index_exploration_tool = IndexExplorationTool(agent=self)
        self.add_tool(index_exploration_tool)

        # Add aggregation tool
        aggregation_tool = AggregationTool(agent=self)
        self.add_tool(aggregation_tool)

    async def connect_database(self) -> None:
        """Connect to Elasticsearch using async client."""
        try:
            # Prepare connection parameters
            connection_params = {
                "verify_certs": self.verify_certs,
                "request_timeout": 30,
                "retry_on_timeout": True,
                "max_retries": 3
            }

            # Authentication setup
            if self.api_key:
                connection_params["api_key"] = self.api_key
            elif self.username and self.password:
                connection_params["basic_auth"] = (self.username, self.password)

            # Connection setup
            if self.cloud_id:
                connection_params["cloud_id"] = self.cloud_id
            elif self.connection_string:
                connection_params["hosts"] = [self.connection_string]
            else:
                raise ValueError("Either connection_string or cloud_id must be provided")

            # Create client
            self.client = AsyncElasticsearch(**connection_params)

            # Test connection
            cluster_info = await self.client.info()
            self.logger.info(f"Connected to Elasticsearch cluster: {cluster_info['cluster_name']}")

        except Exception as e:
            self.logger.error(f"Failed to connect to Elasticsearch: {e}")
            raise

    async def extract_schema_metadata(self) -> DatabaseSchema:
        """Extract schema metadata from Elasticsearch (indices, mappings, settings)."""
        if not self.client:
            await self.connect_database()

        try:
            # Get all indices
            indices_info = await self.client.indices.get(index="*", ignore_unavailable=True)

            # Get cluster stats for additional metadata
            cluster_stats = await self.client.cluster.stats()

            # Extract metadata for each index
            indices_metadata = []
            for index_name, index_info in indices_info.items():
                # Skip system indices by default
                if index_name.startswith('.') and not index_name.startswith('.custom'):
                    continue

                index_metadata = await self._extract_index_metadata(index_name, index_info)
                indices_metadata.append(index_metadata)

                # Cache for later use
                self.indices_cache[index_name] = index_metadata

            # Convert indices to TableMetadata format
            tables = self._convert_indices_to_tables(indices_metadata)

            schema_metadata = DatabaseSchema(
                database_name=cluster_stats["cluster_name"],
                database_type="elasticsearch",
                tables=tables,
                views=[],  # Elasticsearch doesn't have views, but could include index templates
                functions=[],  # Elasticsearch doesn't have stored functions
                procedures=[],  # Elasticsearch doesn't have stored procedures
                metadata={
                    "cluster_name": cluster_stats["cluster_name"],
                    "cluster_version": cluster_stats["nodes"]["versions"],
                    "total_indices": len(indices_metadata),
                    "total_documents": cluster_stats["indices"]["count"],
                    "total_size_bytes": cluster_stats["indices"]["store"]["size_in_bytes"],
                    "extraction_timestamp": datetime.now().isoformat()
                }
            )

            self.logger.info(f"Extracted metadata for {len(indices_metadata)} indices")

            return schema_metadata

        except Exception as e:
            self.logger.error(f"Failed to extract Elasticsearch schema metadata: {e}")
            raise

    async def _extract_index_metadata(
        self,
        index_name: str,
        index_info: Dict[str, Any]
    ) -> IndexMetadata:
        """Extract detailed metadata for a specific index."""
        try:
            # Get mapping
            mapping = index_info.get("mappings", {})

            # Get settings
            settings = index_info.get("settings", {})

            # Get aliases
            aliases = list(index_info.get("aliases", {}).keys())

            # Get index stats
            stats_response = await self.client.indices.stats(index=index_name)
            index_stats = stats_response["indices"].get(index_name, {})

            doc_count = index_stats.get("total", {}).get("docs", {}).get("count", 0)
            size_in_bytes = index_stats.get("total", {}).get("store", {}).get("size_in_bytes", 0)

            # Get sample documents
            sample_documents = await self._get_sample_documents(index_name)

            return IndexMetadata(
                name=index_name,
                mapping=mapping,
                settings=settings,
                aliases=aliases,
                doc_count=doc_count,
                size_in_bytes=size_in_bytes,
                sample_documents=sample_documents
            )

        except Exception as e:
            self.logger.warning(f"Could not extract metadata for index {index_name}: {e}")
            return IndexMetadata(
                name=index_name,
                mapping={},
                settings={},
                aliases=[],
                doc_count=0,
                size_in_bytes=0,
                sample_documents=[]
            )

    async def _get_sample_documents(self, index_name: str) -> List[Dict[str, Any]]:
        """Get sample documents from an index."""
        try:
            search_response = await self.client.search(
                index=index_name,
                body={
                    "query": {"match_all": {}},
                    "size": self.max_sample_docs
                }
            )

            documents = []
            for hit in search_response["hits"]["hits"]:
                doc = {
                    "_id": hit["_id"],
                    "_source": hit["_source"]
                }
                documents.append(doc)

            return documents

        except Exception as e:
            self.logger.warning(f"Could not get sample documents for {index_name}: {e}")
            return []

    def _convert_indices_to_tables(self, indices: List[IndexMetadata]) -> List[TableMetadata]:
        """Convert Elasticsearch indices to TableMetadata format."""
        tables = []

        for index in indices:
            # Extract field information from mapping
            columns = self._extract_fields_from_mapping(index.mapping)

            # Create table metadata
            table_metadata = TableMetadata(
                name=index.name,
                schema="elasticsearch",
                columns=columns,
                primary_keys=["_id"],  # Document ID is the primary key
                foreign_keys=[],  # Elasticsearch doesn't have foreign keys
                indexes=[],  # All fields are potentially indexed in Elasticsearch
                description=f"Elasticsearch index with {index.doc_count} documents ({index.size_in_bytes} bytes)",
                sample_data=[doc["_source"] for doc in index.sample_documents]
            )

            tables.append(table_metadata)

        return tables

    def _extract_fields_from_mapping(self, mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract field information from Elasticsearch mapping."""
        columns = []

        # Add standard Elasticsearch fields
        columns.append({
            "name": "_id",
            "type": "keyword",
            "nullable": False,
            "description": "Document ID"
        })

        columns.append({
            "name": "_source",
            "type": "object",
            "nullable": False,
            "description": "Document source"
        })

        # Extract fields from properties
        properties = mapping.get("properties", {})
        self._extract_properties_recursive(properties, columns)

        return columns

    def _extract_properties_recursive(
        self,
        properties: Dict[str, Any],
        columns: List[Dict[str, Any]],
        prefix: str = ""
    ):
        """Recursively extract properties from mapping."""
        for field_name, field_config in properties.items():
            full_field_name = f"{prefix}.{field_name}" if prefix else field_name

            field_type = field_config.get("type", "object")

            column_info = {
                "name": full_field_name,
                "type": field_type,
                "nullable": True,  # Most Elasticsearch fields are nullable
                "description": f"Elasticsearch field of type {field_type}"
            }

            # Add additional field properties
            if "analyzer" in field_config:
                column_info["analyzer"] = field_config["analyzer"]
            if "format" in field_config:
                column_info["format"] = field_config["format"]

            columns.append(column_info)

            # Handle nested objects and nested types
            if field_type in ["object", "nested"] and "properties" in field_config:
                self._extract_properties_recursive(
                    field_config["properties"],
                    columns,
                    full_field_name
                )

    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "search"
    ) -> Dict[str, Any]:
        """Generate Elasticsearch query from natural language."""
        try:
            # Get schema context for the query
            schema_context = await self._get_schema_context_for_query(
                natural_language_query, target_tables
            )

            # Build Elasticsearch query generation prompt
            prompt = self._build_es_query_prompt(
                natural_language_query=natural_language_query,
                schema_context=schema_context,
                query_type=query_type
            )

            # Generate query using LLM
            response = await self.llm_client.generate_response(
                prompt=prompt,
                model=self.model_name,
                temperature=0.1
            )

            # Extract and parse Elasticsearch query
            es_query = self._extract_es_query_from_response(response.output)

            # Validate query structure
            validation_result = self._validate_es_query(es_query)

            result = {
                "query": es_query,
                "query_type": query_type,
                "indices_used": target_tables or self._extract_indices_from_context(schema_context),
                "schema_context_used": len(schema_context),
                "validation": validation_result,
                "natural_language_input": natural_language_query
            }

            return result

        except Exception as e:
            self.logger.error(f"Failed to generate Elasticsearch query: {e}")
            raise

    def _build_es_query_prompt(
        self,
        natural_language_query: str,
        schema_context: List[Dict[str, Any]],
        query_type: str
    ) -> str:
        """Build prompt for Elasticsearch query generation."""
        prompt = f"""
You are an expert Elasticsearch developer.
Generate an Elasticsearch Query DSL based on the natural language request and the provided index schema information.

Natural Language Request: {natural_language_query}

Available Indices and Schema:
"""

        for i, context in enumerate(schema_context[:3], 1):
            prompt += f"\n{i}. {context.get('content', '')}\n"

        prompt += f"""

Elasticsearch Query DSL Guidelines:
1. Use proper Query DSL JSON structure
2. Common query types: match, term, bool, range, exists, wildcard, fuzzy
3. Use aggregations for analytics: terms, date_histogram, avg, sum, etc.
4. Use filters for exact matches and queries for scoring
5. Consider performance - use filters when possible
6. Return valid JSON that can be used directly with Elasticsearch
7. Do not include index name in the query body (it will be specified separately)

Query Type: {query_type}

Example structures:
- Search: {{"query": {{"match": {{"field": "value"}}}}, "size": 10}}
- Aggregation: {{"aggs": {{"my_agg": {{"terms": {{"field": "category"}}}}}}}}
- Complex: {{"query": {{"bool": {{"must": [...], "filter": [...]}}}}}}

Return only the JSON query without explanations:"""

        return prompt

    def _extract_es_query_from_response(self, response_text: str) -> Dict[str, Any]:
        """Extract and parse Elasticsearch query from LLM response."""
        try:
            # Remove markdown code blocks if present
            if "```json" in response_text:
                lines = response_text.split('\n')
                json_lines = []
                in_json_block = False

                for line in lines:
                    if line.strip().startswith("```json"):
                        in_json_block = True
                        continue
                    elif line.strip() == "```" and in_json_block:
                        break
                    elif in_json_block:
                        json_lines.append(line)

                json_text = '\n'.join(json_lines).strip()
            else:
                json_text = response_text.strip()

            # Parse JSON
            return json.loads(json_text)

        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse JSON from response: {e}")
            # Return a basic match_all query as fallback
            return {"query": {"match_all": {}}}

    def _validate_es_query(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Elasticsearch query structure."""
        try:
            if not isinstance(query, dict):
                return {
                    "valid": False,
                    "error": "Query must be a JSON object",
                    "message": "Invalid query structure"
                }

            # Basic structure validation
            valid_top_level_keys = [
                "query", "aggs", "aggregations", "size", "from",
                "sort", "_source", "highlight", "suggest"
            ]

            for key in query.keys():
                if key not in valid_top_level_keys:
                    return {
                        "valid": False,
                        "error": f"Invalid top-level key: {key}",
                        "message": "Query contains invalid keys"
                    }

            return {
                "valid": True,
                "error": None,
                "message": "Query structure is valid"
            }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "message": "Query validation error"
            }

    def _extract_indices_from_context(self, schema_context: List[Dict[str, Any]]) -> List[str]:
        """Extract index names from schema context."""
        indices = []
        for context in schema_context:
            if context.get("type") == "table" and context.get("name"):
                indices.append(context["name"])
        return indices

    async def execute_query(
        self,
        query: Union[str, Dict[str, Any]],
        index: Optional[str] = None,
        size: int = 100
    ) -> Dict[str, Any]:
        """Execute Elasticsearch query."""
        try:
            if not self.client:
                await self.connect_database()

            # Parse query if it's a string
            if isinstance(query, str):
                query = json.loads(query)

            # Set default size if not specified
            if "size" not in query:
                query["size"] = size

            # Determine target index
            target_index = index or "_all"

            # Execute search
            response = await self.client.search(
                index=target_index,
                body=query
            )

            # Process results
            hits = response["hits"]["hits"]
            documents = []

            for hit in hits:
                doc = {
                    "_index": hit["_index"],
                    "_id": hit["_id"],
                    "_score": hit.get("_score"),
                    **hit["_source"]
                }
                documents.append(doc)

            # Process aggregations if present
            aggregations = response.get("aggregations", {})

            result = {
                "success": True,
                "documents": documents,
                "total_hits": response["hits"]["total"]["value"],
                "max_score": response["hits"]["max_score"],
                "took_ms": response["took"],
                "aggregations": aggregations,
                "query": query,
                "target_index": target_index
            }

            return result

        except Exception as e:
            self.logger.error(f"Elasticsearch query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "target_index": index
            }

    async def close(self):
        """Close Elasticsearch client connection."""
        if self.client:
            await self.client.close()


class ElasticsearchQueryTool(AbstractTool):
    """Tool for executing Elasticsearch queries."""

    name = "execute_elasticsearch_query"
    description = "Execute Elasticsearch Query DSL against the cluster"
    args_schema = ElasticsearchQueryArgs

    def __init__(self, agent: ElasticDbAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        query: Union[str, Dict[str, Any]],
        index: Optional[str] = None,
        size: int = 100,
        timeout: str = "30s",
        explain: bool = False
    ) -> ToolResult:
        """Execute Elasticsearch query."""
        try:
            result = await self.agent.execute_query(query, index, size)

            if explain and result["success"]:
                # Add query explanation
                try:
                    if isinstance(query, str):
                        query_dict = json.loads(query)
                    else:
                        query_dict = query

                    explain_response = await self.agent.client.explain(
                        index=index or "_all",
                        id=result["documents"][0]["_id"] if result["documents"] else "dummy",
                        body={"query": query_dict.get("query", {"match_all": {}})}
                    )
                    result["explanation"] = explain_response
                except:
                    pass  # Explanation is optional

            return ToolResult(
                status="success" if result["success"] else "error",
                result=result,
                error=result.get("error"),
                metadata={
                    "query": str(query)[:500],  # Truncate for metadata
                    "index": index,
                    "size": size,
                    "timeout": timeout
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"query": str(query)[:500]}
            )


class IndexExplorationTool(AbstractTool):
    """Tool for exploring Elasticsearch indices and their structure."""

    name = "explore_indices"
    description = "Explore available indices, mappings, and document structure"

    class IndexExplorationArgs(AbstractToolArgsSchema):
        """Arguments for index exploration."""
        index_pattern: Optional[str] = Field(default="*", description="Index pattern to explore")
        include_mappings: bool = Field(default=True, description="Include field mappings")
        include_sample_docs: bool = Field(default=True, description="Include sample documents")
        include_stats: bool = Field(default=True, description="Include index statistics")

    args_schema = IndexExplorationArgs

    def __init__(self, agent: ElasticDbAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        index_pattern: str = "*",
        include_mappings: bool = True,
        include_sample_docs: bool = True,
        include_stats: bool = True
    ) -> ToolResult:
        """Explore Elasticsearch indices."""
        try:
            if not self.agent.client:
                await self.agent.connect_database()

            # Get indices matching pattern
            indices_response = await self.agent.client.indices.get(
                index=index_pattern,
                ignore_unavailable=True
            )

            exploration_result = {
                "indices": [],
                "total_indices": len(indices_response),
                "pattern": index_pattern
            }

            for index_name, index_info in indices_response.items():
                index_data = {
                    "name": index_name,
                    "aliases": list(index_info.get("aliases", {}).keys())
                }

                if include_mappings:
                    index_data["mappings"] = index_info.get("mappings", {})

                    # Extract field summary
                    properties = index_info.get("mappings", {}).get("properties", {})
                    index_data["field_count"] = len(properties)
                    index_data["field_types"] = self._get_field_type_summary(properties)

                if include_stats:
                    try:
                        stats_response = await self.agent.client.indices.stats(index=index_name)
                        index_stats = stats_response["indices"].get(index_name, {})
                        index_data["stats"] = {
                            "doc_count": index_stats.get("total", {}).get("docs", {}).get("count", 0),
                            "size_bytes": index_stats.get("total", {}).get("store", {}).get("size_in_bytes", 0),
                            "primary_shards": index_stats.get("primaries", {}).get("docs", {}).get("count", 0)
                        }
                    except:
                        index_data["stats"] = {"error": "Could not retrieve stats"}

                if include_sample_docs:
                    try:
                        sample_response = await self.agent.client.search(
                            index=index_name,
                            body={"query": {"match_all": {}}, "size": 3}
                        )
                        index_data["sample_documents"] = [
                            hit["_source"] for hit in sample_response["hits"]["hits"]
                        ]
                    except:
                        index_data["sample_documents"] = []

                exploration_result["indices"].append(index_data)

            return ToolResult(
                status="success",
                result=exploration_result,
                metadata={
                    "index_pattern": index_pattern,
                    "include_mappings": include_mappings,
                    "include_sample_docs": include_sample_docs,
                    "include_stats": include_stats
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"index_pattern": index_pattern}
            )

    def _get_field_type_summary(self, properties: Dict[str, Any]) -> Dict[str, int]:
        """Get summary of field types in the mapping."""
        type_counts = {}

        def count_types_recursive(props):
            for field_name, field_config in props.items():
                field_type = field_config.get("type", "object")
                type_counts[field_type] = type_counts.get(field_type, 0) + 1

                if field_type in ["object", "nested"] and "properties" in field_config:
                    count_types_recursive(field_config["properties"])

        count_types_recursive(properties)
        return type_counts


class AggregationTool(AbstractTool):
    """Tool for running Elasticsearch aggregations and analytics."""

    name = "run_aggregation"
    description = "Run aggregations for analytics and data insights"

    class AggregationArgs(AbstractToolArgsSchema):
        """Arguments for running Elasticsearch aggregations."""
        index: str = Field(description="Index to run aggregation against")
        aggregation_type: str = Field(description="Type of aggregation (terms, date_histogram, avg, sum, etc.)")
        field: str = Field(description="Field to aggregate on")
        size: int = Field(default=10, description="Number of buckets/results to return")
        query_filter: Optional[Dict[str, Any]] = Field(default=None, description="Optional query to filter data")

    args_schema = AggregationArgs

    def __init__(self, agent: ElasticDbAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        index: str,
        aggregation_type: str,
        field: str,
        size: int = 10,
        query_filter: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        """Run aggregation query."""
        try:
            # Build aggregation query
            agg_body = self._build_aggregation_query(
                aggregation_type, field, size, query_filter
            )

            result = await self.agent.execute_query(agg_body, index)

            if result["success"]:
                # Extract and format aggregation results
                agg_results = self._format_aggregation_results(
                    result["aggregations"], aggregation_type
                )
                result["formatted_aggregations"] = agg_results

            return ToolResult(
                status="success" if result["success"] else "error",
                result=result,
                error=result.get("error"),
                metadata={
                    "index": index,
                    "aggregation_type": aggregation_type,
                    "field": field,
                    "size": size
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "index": index,
                    "aggregation_type": aggregation_type,
                    "field": field
                }
            )

    def _build_aggregation_query(
        self,
        agg_type: str,
        field: str,
        size: int,
        query_filter: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build aggregation query based on type."""
        # Base query structure
        query_body = {
            "size": 0,  # We only want aggregation results, not documents
            "aggs": {
                "main_agg": {}
            }
        }

        # Add query filter if provided
        if query_filter:
            query_body["query"] = query_filter

        # Build aggregation based on type
        if agg_type == "terms":
            query_body["aggs"]["main_agg"] = {
                "terms": {
                    "field": field,
                    "size": size
                }
            }
        elif agg_type == "date_histogram":
            query_body["aggs"]["main_agg"] = {
                "date_histogram": {
                    "field": field,
                    "calendar_interval": "day"
                }
            }
        elif agg_type in ["avg", "sum", "min", "max"]:
            query_body["aggs"]["main_agg"] = {
                agg_type: {
                    "field": field
                }
            }
        elif agg_type == "cardinality":
            query_body["aggs"]["main_agg"] = {
                "cardinality": {
                    "field": field
                }
            }
        else:
            # Default to terms aggregation
            query_body["aggs"]["main_agg"] = {
                "terms": {
                    "field": field,
                    "size": size
                }
            }

        return query_body

    def _format_aggregation_results(
        self,
        aggregations: Dict[str, Any],
        agg_type: str
    ) -> Dict[str, Any]:
        """Format aggregation results for better readability."""
        if "main_agg" not in aggregations:
            return {}

        main_agg = aggregations["main_agg"]

        if agg_type == "terms":
            return {
                "buckets": main_agg.get("buckets", []),
                "total_buckets": len(main_agg.get("buckets", [])),
                "sum_other_doc_count": main_agg.get("sum_other_doc_count", 0)
            }
        elif agg_type == "date_histogram":
            return {
                "buckets": main_agg.get("buckets", []),
                "total_buckets": len(main_agg.get("buckets", []))
            }
        elif agg_type in ["avg", "sum", "min", "max", "cardinality"]:
            return {
                "value": main_agg.get("value"),
                "value_as_string": main_agg.get("value_as_string")
            }
        else:
            return main_agg


# Factory function for creating Elasticsearch agents
def create_elasticsearch_agent(
    url: str = None,
    username: str = None,
    password: str = None,
    api_key: str = None,
    cloud_id: str = None,
    **kwargs
) -> ElasticDbAgent:
    """
    Factory function to create Elasticsearch agents.

    Args:
        url: Elasticsearch URL (e.g., 'http://localhost:9200')
        username: Username for authentication
        password: Password for authentication
        api_key: API key for authentication
        cloud_id: Elastic Cloud ID
        **kwargs: Additional arguments for the agent

    Returns:
        Configured ElasticDbAgent instance
    """
    return ElasticDbAgent(
        connection_string=url,
        username=username,
        password=password,
        api_key=api_key,
        cloud_id=cloud_id,
        **kwargs
    )


# Example usage
"""
# Create Elasticsearch agent with username/password
es_agent = create_elasticsearch_agent(
    url='http://localhost:9200',
    username='elastic',
    password='your-password'
)

# Or with API key
es_agent = create_elasticsearch_agent(
    url='http://localhost:9200',
    api_key='your-api-key'
)

# Or with Elastic Cloud
es_agent = create_elasticsearch_agent(
    cloud_id='your-cloud-id',
    api_key='your-api-key'
)

# Initialize schema
await es_agent.initialize_schema()

# Generate query from natural language
result = await es_agent.generate_query(
    "Find all documents where status is active and created in the last 30 days"
)

# Execute the generated query
execution_result = await es_agent.execute_query(result['query'])

# Run aggregations
agg_tool = AggregationTool(agent=es_agent)
agg_result = await agg_tool._arun(
    index='my-index',
    aggregation_type='terms',
    field='category.keyword',
    size=10
)

# Explore indices
exploration_tool = IndexExplorationTool(agent=es_agent)
exploration_result = await exploration_tool._arun(index_pattern='log-*')
"""
