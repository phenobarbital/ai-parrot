"""
DocumentDB Agent Implementation for AI-Parrot.

Concrete implementation of AbstractDBAgent for AWS DocumentDB
(MongoDB-compatible) with support for MQL query language.
"""

from typing import Dict, Any, List, Optional, Union
import asyncio
import json
from datetime import datetime
from pydantic import Field
from asyncdb import AsyncDB
from navconfig import config, BASE_DIR

from .abstract import (
    AbstractDBAgent,
    DatabaseSchema,
    TableMetadata,
)
from ...tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema


class CollectionQueryExecutionArgs(AbstractToolArgsSchema):
    """Arguments for DocumentDB collection query execution."""
    collection_name: str = Field(description="Collection name to query")
    query: Dict[str, Any] = Field(
        default_factory=dict, description="MongoDB query filter"
    )
    limit: Optional[int] = Field(
        default=100, description="Maximum number of documents to return"
    )
    projection: Optional[Dict[str, int]] = Field(
        default=None, description="Fields to include/exclude in results"
    )


class CollectionMetadata:
    """Metadata for DocumentDB collections."""
    def __init__(
        self,
        name: str,
        database: str,
        document_count: int,
        fields: List[Dict[str, str]],
        sample_documents: List[Dict[str, Any]] = None,
        indexes: List[Dict[str, Any]] = None
    ):
        self.name = name
        self.database = database
        self.document_count = document_count
        self.fields = fields
        self.sample_documents = sample_documents or []
        self.indexes = indexes or []


class DocumentDBAgent(AbstractDBAgent):
    """
    DocumentDB Agent for document database introspection and MQL query generation.

    Supports AWS DocumentDB (MongoDB-compatible) with MongoDB Query Language (MQL).
    """

    def __init__(
        self,
        name: str = "DocumentDBAgent",
        host: str = None,
        port: int = 27017,
        database: str = None,
        username: str = None,
        password: str = None,
        credentials: Union[str, Dict[str, Any]] = None,
        ssl: bool = True,
        tls_ca_file: str = None,
        max_sample_documents: int = 10,
        **kwargs
    ):
        """
        Initialize DocumentDB Agent.

        Args:
            name: Agent name
            host: DocumentDB hostname
            port: DocumentDB port (default: 27017)
            database: Database name
            username: Username for authentication
            password: Password for authentication
            credentials: Credentials dict or connection string (overrides individual params)
            ssl: Enable SSL/TLS connection (default: True)
            tls_ca_file: Path to TLS CA certificate file
            max_sample_documents: Maximum sample documents per collection
        """
        self.host = host
        self.port = port
        self.database_name = database
        self.username = username
        self.password = password
        self.ssl = ssl
        self.tls_ca_file = tls_ca_file
        self.max_sample_documents = max_sample_documents
        self.db_connection: Optional[Any] = None
        self.collections_cache: Dict[str, CollectionMetadata] = {}

        # Get default credentials if not provided
        if not credentials and not all([host, database]):
            credentials = self._get_default_credentials()

        super().__init__(
            name=name,
            credentials=credentials,
            schema_name=database,
            **kwargs
        )

        # Add DocumentDB-specific tools
        self._setup_documentdb_tools()

    def _get_default_credentials(self) -> Dict[str, Any]:
        """Get default credentials from config (similar to DatabaseQueryTool)."""
        return {
            'driver': 'mongo',
            'host': config.get('DOCUMENTDB_HOSTNAME', fallback='localhost'),
            'port': config.get('DOCUMENTDB_PORT', fallback=27017),
            'database': config.get('DOCUMENTDB_DATABASE', fallback='test'),
            'username': config.get('DOCUMENTDB_USERNAME'),
            'password': config.get('DOCUMENTDB_PASSWORD'),
            'tlsCAFile': config.get('DOCUMENTDB_TLS_CA_FILE') or BASE_DIR.joinpath('env', "global-bundle.pem"),
            'ssl': config.get('DOCUMENTDB_USE_SSL', fallback=True),
            'collection_name': config.get('DOCUMENTDB_COLLECTION', fallback='mycollection'),
            'dbtype': 'documentdb'
        }

    def _setup_documentdb_tools(self):
        """Setup DocumentDB-specific tools."""
        # Add collection query execution tool
        collection_query_tool = CollectionQueryExecutionTool(agent=self)
        self.tool_manager.register_tool(collection_query_tool)

        # Add collection exploration tool
        collection_exploration_tool = CollectionExplorationTool(agent=self)
        self.tool_manager.register_tool(collection_exploration_tool)

    async def connect_database(self) -> None:
        """Connect to DocumentDB using AsyncDB with mongo driver."""
        # Parse credentials
        if isinstance(self.credentials, dict):
            creds = self.credentials.copy()
            self.host = creds.get('host', self.host)
            self.port = creds.get('port', self.port)
            self.database_name = creds.get('database', self.database_name)
            self.username = creds.get('username', self.username)
            self.password = creds.get('password', self.password)
            self.ssl = creds.get('ssl', self.ssl)
            self.tls_ca_file = creds.get('tlsCAFile', self.tls_ca_file)

        if not self.host:
            raise ValueError("DocumentDB host is required")
        if not self.database_name:
            raise ValueError("DocumentDB database name is required")

        try:
            # Build connection parameters for AsyncDB
            params = {
                'host': self.host,
                'port': self.port,
                'database': self.database_name,
                'dbtype': 'documentdb'
            }

            if self.username:
                params['username'] = self.username
            if self.password:
                params['password'] = self.password
            if self.ssl:
                params['ssl'] = self.ssl
            if self.tls_ca_file:
                params['tlsCAFile'] = str(self.tls_ca_file)

            # Create AsyncDB instance
            self.db = AsyncDB('mongo', params=params)
            
            # Test connection
            async with await self.db.connection() as conn:
                await conn.use(self.database_name)
                # Simple ping to verify connection
                result = await conn.execute({"ping": 1})
                
            self.logger.info(
                f"Successfully connected to DocumentDB at {self.host}:{self.port}"
            )

        except Exception as e:
            self.logger.error(f"Failed to connect to DocumentDB: {e}")
            raise

    async def extract_schema_metadata(self) -> DatabaseSchema:
        """Extract schema metadata from DocumentDB (collections, fields, documents)."""
        if not self.db:
            await self.connect_database()

        try:
            async with await self.db.connection() as conn:
                await conn.use(self.database_name)
                
                # Get list of collections
                collections_result = await conn.execute({"listCollections": 1})
                collection_names = [
                    col['name'] for col in collections_result.get('cursor', {}).get('firstBatch', [])
                    if not col['name'].startswith('system.')
                ]

                # Extract metadata for each collection
                all_collections = []
                for collection_name in collection_names:
                    collection_metadata = await self._extract_collection_metadata(
                        conn, collection_name
                    )
                    all_collections.append(collection_metadata)

                    # Cache for later use
                    cache_key = f"{self.database_name}.{collection_name}"
                    self.collections_cache[cache_key] = collection_metadata

                # Convert collections to TableMetadata format
                tables = self._convert_collections_to_tables(all_collections)

                schema_metadata = DatabaseSchema(
                    database_name=self.database_name,
                    database_type="documentdb",
                    tables=tables,
                    views=[],  # DocumentDB doesn't have traditional views
                    functions=[],
                    procedures=[],
                    metadata={
                        "collections_analyzed": len(all_collections),
                        "extraction_timestamp": datetime.now().isoformat(),
                        "host": self.host,
                        "port": self.port
                    }
                )

                self.logger.info(
                    f"Extracted metadata for {len(all_collections)} collections from {self.database_name}"
                )

                return schema_metadata

        except Exception as e:
            self.logger.error(f"Failed to extract DocumentDB schema metadata: {e}")
            raise

    async def _extract_collection_metadata(
        self,
        conn: Any,
        collection_name: str
    ) -> CollectionMetadata:
        """Extract detailed metadata for a specific collection."""
        try:
            # Get document count
            count_result = await conn.count(collection_name, {})
            document_count = count_result if isinstance(count_result, int) else 0

            # Get sample documents to infer schema
            sample_docs = await conn.fetch(
                collection_name,
                {},
                limit=self.max_sample_documents
            )

            # Infer fields from sample documents
            fields = self._infer_fields_from_documents(sample_docs)

            # Get indexes
            indexes = []
            try:
                indexes_cursor = await conn.execute({
                    "listIndexes": collection_name
                })
                indexes = list(indexes_cursor.get('cursor', {}).get('firstBatch', []))
            except Exception as e:
                self.logger.warning(f"Could not get indexes for {collection_name}: {e}")

            return CollectionMetadata(
                name=collection_name,
                database=self.database_name,
                document_count=document_count,
                fields=fields,
                sample_documents=sample_docs[:5] if sample_docs else [],
                indexes=indexes
            )

        except Exception as e:
            self.logger.warning(
                f"Could not extract metadata for collection {collection_name}: {e}"
            )
            return CollectionMetadata(
                name=collection_name,
                database=self.database_name,
                document_count=0,
                fields=[],
                sample_documents=[],
                indexes=[]
            )

    def _infer_fields_from_documents(
        self,
        documents: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """Infer field schema from sample documents."""
        if not documents:
            return []

        # Collect all fields and their types
        field_types = {}
        for doc in documents:
            for key, value in doc.items():
                if key not in field_types:
                    field_types[key] = set()
                field_types[key].add(type(value).__name__)

        # Create field list
        fields = []
        for field_name, types in sorted(field_types.items()):
            type_str = ' | '.join(sorted(types))
            fields.append({
                "name": field_name,
                "type": type_str
            })

        return fields

    def _convert_collections_to_tables(
        self,
        collections: List[CollectionMetadata]
    ) -> List[TableMetadata]:
        """Convert DocumentDB collections to TableMetadata format."""
        tables = []

        for collection in collections:
            # Create columns list from fields
            columns = []
            for field in collection.fields:
                columns.append({
                    "name": field["name"],
                    "type": field["type"],
                    "nullable": True,  # MongoDB fields are generally nullable
                    "description": f"Field: {field['name']}"
                })

            # Create table metadata
            table_metadata = TableMetadata(
                name=collection.name,
                schema=self.database_name,
                columns=columns,
                primary_keys=["_id"],  # MongoDB always has _id
                foreign_keys=[],  # DocumentDB doesn't enforce foreign keys
                indexes=[idx.get('name', '') for idx in collection.indexes],
                description=f"DocumentDB collection with {collection.document_count} documents",
                sample_data=collection.sample_documents
            )

            tables.append(table_metadata)

        return tables

    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "find"
    ) -> Dict[str, Any]:
        """Generate MongoDB query from natural language."""
        try:
            # Get schema context for the query
            schema_context = []
            if self.schema_metadata:
                # Filter collections based on target_tables
                collections_to_use = self.schema_metadata.tables
                if target_tables:
                    collections_to_use = [
                        t for t in collections_to_use if t.name in target_tables
                    ]
                
                for table in collections_to_use[:3]:  # Limit to top 3
                    schema_context.append({
                        'collection': table.name,
                        'fields': [col['name'] for col in table.columns],
                        'sample_count': len(table.sample_data)
                    })

            # Build MQL query generation prompt
            prompt = self._build_mql_query_prompt(
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

            # Extract MQL query from response
            mql_query = self._extract_mql_from_response(response.output or response.response)

            result = {
                "query": mql_query,
                "query_type": "mql",
                "collections_used": target_tables or [],
                "schema_context_used": len(schema_context),
                "natural_language_input": natural_language_query
            }

            return result

        except Exception as e:
            self.logger.error(f"Failed to generate MQL query: {e}")
            raise

    def _build_mql_query_prompt(
        self,
        natural_language_query: str,
        schema_context: List[Dict[str, Any]]
    ) -> str:
        """Build prompt for MQL query generation."""
        prompt = f"""
You are an expert MongoDB/DocumentDB query developer.
Generate a MongoDB query based on the natural language request and the provided schema information.

Natural Language Request: {natural_language_query}

Available Collections and Schema:
"""
        for i, context in enumerate(schema_context, 1):
            prompt += f"\n{i}. Collection: {context['collection']}\n"
            prompt += f"   Fields: {', '.join(context['fields'])}\n"

        prompt += """

MongoDB Query Guidelines:
1. Use standard MongoDB query syntax
2. Return query as a JSON object
3. Use the find command structure: {"find": "collection_name", "filter": {...}, "limit": N}
4. Common operators: $eq, $ne, $gt, $lt, $gte, $lte, $in, $nin, $and, $or, $not
5. For text search use $regex or $text
6. Include projection to limit returned fields if needed
7. Return only the MongoDB query as valid JSON without explanations

Example query structure:
{
    "find": "users",
    "filter": {"age": {"$gte": 18}, "status": "active"},
    "limit": 10,
    "sort": {"created_at": -1}
}

MongoDB Query (JSON only):"""

        return prompt

    def _extract_mql_from_response(self, response_text: str) -> Dict[str, Any]:
        """Extract MQL query from LLM response."""
        # Remove markdown code blocks if present
        if "```" in response_text:
            lines = response_text.split('\n')
            json_lines = []
            in_code_block = False

            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                elif in_code_block or (line.strip().startswith('{') or json_lines):
                    json_lines.append(line)

            response_text = '\n'.join(json_lines).strip()

        # Parse JSON
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract first JSON object
            import re
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                return json.loads(match.group())
            else:
                return {"filter": {}}

    async def execute_query(
        self,
        query: Union[str, Dict[str, Any]],
        limit: Optional[int] = 100
    ) -> Dict[str, Any]:
        """Execute MongoDB query against DocumentDB."""
        try:
            if not self.db:
                await self.connect_database()

            # Parse query if string
            if isinstance(query, str):
                query = json.loads(query)

            async with await self.db.connection() as conn:
                await conn.use(self.database_name)

                # Extract query components
                collection_name = query.get('find') or query.get('collection')
                filter_query = query.get('filter', {})
                query_limit = query.get('limit', limit)
                projection = query.get('projection')
                sort = query.get('sort')

                if not collection_name:
                    raise ValueError("Query must specify a collection name")

                # Execute query
                results = await conn.fetch(
                    collection_name,
                    filter_query,
                    limit=query_limit
                )

                return {
                    "success": True,
                    "data": results,
                    "record_count": len(results),
                    "query": query,
                    "collection": collection_name
                }

        except Exception as e:
            self.logger.error(f"DocumentDB query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }

    async def close(self):
        """Close DocumentDB connection."""
        if self.db:
            await self.db.close()


class CollectionQueryExecutionTool(AbstractTool):
    """Tool for executing queries against DocumentDB collections."""

    name = "execute_documentdb_query"
    description = "Execute MongoDB queries against the DocumentDB database"
    args_schema = CollectionQueryExecutionArgs

    def __init__(self, agent: DocumentDBAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        collection_name: str,
        query: Dict[str, Any] = None,
        limit: Optional[int] = 100,
        projection: Optional[Dict[str, int]] = None
    ) -> ToolResult:
        """Execute collection query."""
        try:
            # Build query object
            full_query = {
                "find": collection_name,
                "filter": query or {},
                "limit": limit
            }
            if projection:
                full_query["projection"] = projection

            result = await self.agent.execute_query(full_query, limit)

            return ToolResult(
                status="success" if result["success"] else "error",
                result=result,
                error=result.get("error"),
                metadata={
                    "collection": collection_name,
                    "limit": limit
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"collection": collection_name}
            )


class CollectionExplorationTool(AbstractTool):
    """Tool for exploring DocumentDB collections and their metadata."""

    name = "explore_collections"
    description = "Explore available collections and fields in DocumentDB"

    class ExplorationArgs(AbstractToolArgsSchema):
        """Exploration arguments schema."""
        collection: Optional[str] = Field(
            default=None, description="Specific collection to explore"
        )
        show_sample_data: bool = Field(
            default=True, description="Include sample data in results"
        )

    args_schema = ExplorationArgs

    def __init__(self, agent: DocumentDBAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        collection: Optional[str] = None,
        show_sample_data: bool = True
    ) -> ToolResult:
        """Explore collections in DocumentDB."""
        try:
            if not self.agent.schema_metadata:
                await self.agent.extract_schema_metadata()

            exploration_result = {
                "collections": [],
                "total_collections": 0
            }

            # Filter by collection if specified
            tables_to_explore = self.agent.schema_metadata.tables
            if collection:
                tables_to_explore = [t for t in tables_to_explore if t.name == collection]

            for table in tables_to_explore:
                collection_info = {
                    "name": table.name,
                    "document_count": table.description,
                    "fields": [col['name'] for col in table.columns],
                    "indexes": table.indexes
                }

                if show_sample_data and table.sample_data:
                    collection_info["sample_documents"] = table.sample_data[:3]

                exploration_result["collections"].append(collection_info)

            exploration_result["total_collections"] = len(exploration_result["collections"])

            return ToolResult(
                status="success",
                result=exploration_result,
                metadata={
                    "database": self.agent.database_name,
                    "collection_filter": collection
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e)
            )
