"""
ArangoDB Vector Search Tool for AI-Parrot Framework.

Provides comprehensive search capabilities including:
- Vector similarity search
- Full-text search (BM25)
- Hybrid search (combining vector + text)
- Graph traversal and context enrichment
"""
from typing import Any, Dict, List, Optional, Union
from enum import Enum
import asyncio
import inspect
from pydantic import BaseModel, Field
from asyncdb import AsyncDB
from navconfig import config
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from parrot.tools.abstract import AbstractTool, ToolResult


class SearchType(str, Enum):
    """Supported search types."""
    VECTOR = "vector"
    FULLTEXT = "fulltext"
    HYBRID = "hybrid"
    GRAPH_TRAVERSE = "graph_traverse"


class ArangoSearchArgs(BaseModel):
    """Arguments schema for ArangoDB search operations."""

    # Common arguments
    search_type: SearchType = Field(
        default=SearchType.VECTOR,
        description="Type of search to perform: vector, fulltext, hybrid, or graph_traverse"
    )

    # Collection/View arguments
    view_name: str = Field(
        description="ArangoSearch view name for search operations"
    )
    collection: Optional[str] = Field(
        default=None,
        description="Collection name (required for vector search)"
    )

    # Query arguments
    query_text: Optional[str] = Field(
        default=None,
        description="Text query for full-text or hybrid search"
    )
    query_vector: Optional[List[float]] = Field(
        default=None,
        description="Query embedding vector for vector or hybrid search"
    )

    # Search parameters
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of results to return"
    )
    score_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum score threshold for results"
    )

    # Vector search specific
    vector_field: str = Field(
        default="embedding",
        description="Field name containing embeddings"
    )

    # Full-text search specific
    text_fields: Optional[List[str]] = Field(
        default=None,
        description="Fields to search for full-text queries"
    )
    analyzer: str = Field(
        default="text_en",
        description="Text analyzer for full-text search"
    )

    # Hybrid search specific
    text_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight for text score in hybrid search"
    )
    vector_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight for vector similarity in hybrid search"
    )

    # Filter conditions
    filter_conditions: Optional[List[str]] = Field(
        default=None,
        description="Additional AQL filter conditions"
    )

    # Graph-specific arguments
    graph_name: Optional[str] = Field(
        default=None,
        description="Graph name for graph operations"
    )
    start_vertex: Optional[str] = Field(
        default=None,
        description="Starting vertex for graph traversal"
    )
    include_graph_context: bool = Field(
        default=False,
        description="Include neighboring nodes in results"
    )
    max_depth: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum depth for graph traversal"
    )
    relation_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by specific relationship types"
    )


class ArangoDBSearchTool(AbstractTool):
    """
    ArangoDB Vector Search Tool.

    Provides unified search capabilities across vector, full-text, and graph data.
    Supports:
    - Semantic vector search
    - BM25 full-text search
    - Hybrid search combining both approaches
    - Graph-enhanced search with relationship context
    """

    name = "arangodb_search"
    description = """Search ArangoDB using vector similarity, full-text, or hybrid approaches.
    Can also traverse graph relationships to enrich results with context."""
    args_schema = ArangoSearchArgs

    def __init__(
        self,
        connection_params: Optional[Dict[str, Any]] = None,
        default_database: str = "_system",
        default_view: Optional[str] = None,
        default_graph: Optional[str] = None,
        embedding_function: Optional[callable] = None,
        **kwargs
    ):
        """
        Initialize ArangoDB search tool.

        Args:
            connection_params: Connection parameters for ArangoDB
            default_database: Default database name
            default_view: Default ArangoSearch view name
            default_graph: Default graph name for graph operations
            embedding_function: Function to generate embeddings from text
        """
        super().__init__(**kwargs)

        self.connection_params = connection_params or {
            "host": config.get('ARANGODB_HOST', 'localhost'),
            "port": config.get('ARANGODB_PORT', 8529),
            "username": config.get('ARANGODB_USERNAME', 'root'),
            "password": config.get('ARANGODB_PASSWORD', '12345678'),
            "database": config.get('ARANGODB_DATABASE', default_database),
        }

        self.default_database = default_database
        self.default_view = default_view
        self.default_graph = default_graph
        self.embedding_function = embedding_function

        # ArangoDB connection (lazy initialization)
        self._db: Optional[AsyncDB] = None

    async def _get_connection(self) -> AsyncDB:
        """Get or create ArangoDB connection."""
        if self._db is None:
            self._db = AsyncDB("arangodb", params=self.connection_params)
        return self._db

    async def _execute(
        self,
        search_type: SearchType = SearchType.VECTOR,
        view_name: Optional[str] = None,
        collection: Optional[str] = None,
        query_text: Optional[str] = None,
        query_vector: Optional[List[float]] = None,
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        vector_field: str = "embedding",
        text_fields: Optional[List[str]] = None,
        analyzer: str = "text_en",
        text_weight: float = 0.5,
        vector_weight: float = 0.5,
        filter_conditions: Optional[List[str]] = None,
        graph_name: Optional[str] = None,
        start_vertex: Optional[str] = None,
        include_graph_context: bool = False,
        max_depth: int = 2,
        relation_types: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        """
        Execute the search operation.

        Returns:
            ToolResult containing search results and metadata
        """
        try:
            db = self._get_connection()

            # Use defaults if not provided
            view_name = view_name or self.default_view
            graph_name = graph_name or self.default_graph

            # Validate required parameters
            if not view_name and search_type != SearchType.GRAPH_TRAVERSE:
                return ToolResult(
                    status="error",
                    result=None,
                    error="view_name is required for search operations"
                )

            # Generate embedding if needed and function provided
            if search_type in [SearchType.VECTOR, SearchType.HYBRID]:
                if query_vector is None and query_text and self.embedding_function:
                    self.logger.info("Generating embedding from query text")
                    query_vector = await self._generate_embedding(query_text)

                if query_vector is None:
                    return ToolResult(
                        status="error",
                        result=None,
                        error="query_vector is required for vector/hybrid search"
                    )

            # Execute appropriate search
            results = []
            metadata = {
                "search_type": search_type.value,
                "top_k": top_k,
                "view_name": view_name,
                "collection": collection
            }

            async with await db.connection() as conn:  # pylint: disable=E1101 # noqa

                if search_type == SearchType.VECTOR:
                    results = await self._vector_search(
                        conn, view_name, collection, query_vector,
                        vector_field, top_k, score_threshold, filter_conditions
                    )
                    metadata["vector_dimension"] = len(query_vector)

                elif search_type == SearchType.FULLTEXT:
                    results = await self._fulltext_search(
                        conn, view_name, query_text,
                        text_fields, analyzer, top_k, score_threshold
                    )
                    metadata["analyzer"] = analyzer
                    metadata["text_fields"] = text_fields

                elif search_type == SearchType.HYBRID:
                    results = await self._hybrid_search(
                        conn, view_name, collection, query_text, query_vector,
                        text_fields, vector_field, text_weight, vector_weight,
                        analyzer, top_k, filter_conditions
                    )
                    metadata["text_weight"] = text_weight
                    metadata["vector_weight"] = vector_weight

                elif search_type == SearchType.GRAPH_TRAVERSE:
                    if not start_vertex:
                        return ToolResult(
                            status="error",
                            result=None,
                            error="start_vertex is required for graph traversal"
                        )
                    results = await self._graph_traverse(
                        conn, start_vertex, graph_name,
                        max_depth, relation_types, top_k
                    )
                    metadata["graph_name"] = graph_name
                    metadata["max_depth"] = max_depth

                # Enrich with graph context if requested
                if include_graph_context and graph_name and results:
                    results = await self._enrich_with_graph_context(
                        conn, results, graph_name, max_depth, relation_types
                    )
                    metadata["graph_context_included"] = True

                metadata["results_count"] = len(results)

                return ToolResult(
                    status="success",
                    result=results,
                    metadata=metadata
                )

        except Exception as e:
            self.logger.error(f"ArangoDB search error: {e}", exc_info=True)
            return ToolResult(
                status="error",
                result=None,
                error=str(e)
            )

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding from text using the configured function."""
        if self.embedding_function is None:
            raise ValueError("No embedding function configured")

        # Handle both sync and async embedding functions
        if inspect.iscoroutinefunction(self.embedding_function):
            return await self.embedding_function(text)
        else:
            return await asyncio.get_event_loop().run_in_executor(
                None, self.embedding_function, text
            )

    async def _vector_search(
        self,
        db: AsyncDB,
        view_name: str,
        collection: str,
        query_vector: List[float],
        vector_field: str,
        top_k: int,
        score_threshold: Optional[float],
        filter_conditions: Optional[List[str]]
    ) -> List[Dict]:
        """Execute vector similarity search."""
        results = await db.vector_search(
            view_name=view_name,
            collection=collection,
            query_vector=query_vector,
            vector_field=vector_field,
            top_k=top_k,
            filter_conditions=filter_conditions,
            include_similarity=True
        )

        # Apply score threshold if specified
        if score_threshold is not None:
            results = [
                r for r in results
                if r.get('similarity', 0) >= score_threshold
            ]

        return results

    async def _fulltext_search(
        self,
        db: AsyncDB,
        view_name: str,
        query_text: str,
        text_fields: Optional[List[str]],
        analyzer: str,
        top_k: int,
        min_score: Optional[float]
    ) -> List[Dict]:
        """Execute full-text search."""
        results = await db.fulltext_search(
            view_name=view_name,
            query_text=query_text,
            fields=text_fields,
            analyzer=analyzer,
            top_k=top_k,
            min_score=min_score or 0.0
        )
        return results

    async def _hybrid_search(
        self,
        db: AsyncDB,
        view_name: str,
        collection: str,
        query_text: str,
        query_vector: List[float],
        text_fields: Optional[List[str]],
        vector_field: str,
        text_weight: float,
        vector_weight: float,
        analyzer: str,
        top_k: int,
        filter_conditions: Optional[List[str]]
    ) -> List[Dict]:
        """Execute hybrid search combining vector and text."""
        results = await db.hybrid_search(
            view_name=view_name,
            collection=collection,
            query_text=query_text,
            query_vector=query_vector,
            text_fields=text_fields,
            vector_field=vector_field,
            text_weight=text_weight,
            vector_weight=vector_weight,
            analyzer=analyzer,
            top_k=top_k
        )
        return results

    async def _graph_traverse(
        self,
        db: AsyncDB,
        start_vertex: str,
        graph_name: Optional[str],
        max_depth: int,
        relation_types: Optional[List[str]],
        limit: int
    ) -> List[Dict]:
        """Execute graph traversal."""
        results = await db.find_related_nodes(
            node_id=start_vertex,
            relation_types=relation_types,
            max_depth=max_depth,
            limit=limit,
            graph_name=graph_name
        )
        return results

    async def _enrich_with_graph_context(
        self,
        db: AsyncDB,
        results: List[Dict],
        graph_name: str,
        max_depth: int,
        relation_types: Optional[List[str]]
    ) -> List[Dict]:
        """Enrich search results with graph context."""
        enriched = []

        for result in results:
            # Extract document ID
            doc_id = None
            if 'document' in result:
                doc_id = result['document'].get('_id')
            elif '_id' in result:
                doc_id = result['_id']

            if doc_id:
                # Get neighboring nodes
                neighbors = await db.find_related_nodes(
                    node_id=doc_id,
                    relation_types=relation_types,
                    max_depth=max_depth,
                    limit=10,
                    graph_name=graph_name
                )

                result['graph_context'] = neighbors

            enriched.append(result)

        return enriched

    async def close(self):
        """Close database connection."""
        self._db = None

    def __del__(self):
        """Cleanup on deletion."""
        if self._db:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.close())
                else:
                    loop.run_until_complete(self.close())
            except Exception:
                pass


# Example usage and helper functions

async def create_arangodb_search_tool(
    connection_params: Optional[Dict] = None,
    embedding_model: Optional[str] = None,
    **kwargs
) -> ArangoDBSearchTool:
    """
    Factory function to create ArangoDB search tool with embedding support.

    Args:
        connection_params: ArangoDB connection parameters
        embedding_model: Hugging Face model name for embeddings
        **kwargs: Additional tool configuration

    Returns:
        Configured ArangoDBSearchTool instance
    """
    embedding_function = None

    if embedding_model:
        from transformers import AutoTokenizer, AutoModel
        import torch

        # Load model and tokenizer
        tokenizer = AutoTokenizer.from_pretrained(embedding_model)
        model = AutoModel.from_pretrained(embedding_model)

        def generate_embedding(text: str) -> List[float]:
            """Generate embedding using transformers."""
            inputs = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True
            )

            with torch.no_grad():
                outputs = model(**inputs)

            # Use mean pooling
            embeddings = outputs.last_hidden_state.mean(dim=1)
            return embeddings[0].tolist()

        embedding_function = generate_embedding

    return ArangoDBSearchTool(
        connection_params=connection_params,
        embedding_function=embedding_function,
        **kwargs
    )
