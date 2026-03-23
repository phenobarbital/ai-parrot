"""
VectorStoreSearchTool - A tool for performing similarity search on vector stores.

This tool accepts a StoreConfig to configure the vector store and performs
similarity searches based on user queries.
"""
import importlib
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from navconfig.logging import logging
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from ..stores import AbstractStore, supported_stores
from ..stores.models import StoreConfig, SearchResult


class VectorSearchArgs(AbstractToolArgsSchema):
    """Arguments schema for VectorStoreSearchTool."""
    query: str = Field(
        ...,
        description="The search query to find similar documents in the vector store"
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100
    )
    score_threshold: Optional[float] = Field(
        default=None,
        description="Minimum similarity score threshold (0.0 to 1.0)"
    )
    metadata_filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata filters to apply to the search"
    )
    use_mmr: bool = Field(
        default=False,
        description="Whether to use Maximal Marginal Relevance (MMR) search for diversity"
    )
    lambda_mult: float = Field(
        default=0.5,
        description="Lambda multiplier for MMR search (0.0 = max diversity, 1.0 = max relevance)",
        ge=0.0,
        le=1.0
    )


class VectorStoreSearchTool(AbstractTool):
    """
    A tool for performing similarity search on vector stores.

    This tool creates a vector store instance based on the provided StoreConfig
    and performs similarity searches to find documents relevant to user queries.

    Example usage:
        config = StoreConfig(
            vector_store='postgres',
            table='products',
            schema='gorillashed',
            embedding_model={"model": "BAAI/bge-base-en-v1.5", "model_type": "huggingface"},
            dimension=768,
            dsn=asyncpg_sqlalchemy_url,
            auto_create=False
        )
        tool = VectorStoreSearchTool(store_config=config)
        result = await tool.execute(query="Find products similar to...")
    """

    name: str = "vector_store_search"
    description: str = (
        "Search for relevant documents in a vector store using semantic similarity. "
        "Useful for finding products, documents, or any content that matches a natural language query."
    )
    args_schema = VectorSearchArgs

    def __init__(
        self,
        store_config: StoreConfig,
        name: Optional[str] = None,
        description: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        content_column: str = 'document',
        embedding_column: str = 'embedding',
        metadata_column: str = 'cmetadata',
        id_column: str = 'id',
        **kwargs
    ):
        """
        Initialize the VectorStoreSearchTool.

        Args:
            store_config: Configuration for the vector store
            name: Optional custom name for the tool
            description: Optional custom description for the tool
            additional_columns: Additional columns to retrieve from the store
            content_column: Name of the column containing document content
            embedding_column: Name of the column containing embeddings
            metadata_column: Name of the column containing metadata
            id_column: Name of the ID column
            **kwargs: Additional arguments passed to AbstractTool
        """
        super().__init__(name=name, description=description, **kwargs)

        self.store_config = store_config
        self._store: Optional[AbstractStore] = None

        # Column configuration
        self.additional_columns = additional_columns
        self.content_column = content_column
        self.embedding_column = embedding_column
        self.metadata_column = metadata_column
        self.id_column = id_column

        # Store initialization kwargs for cloning
        self._init_kwargs.update({
            'store_config': store_config,
            'additional_columns': additional_columns,
            'content_column': content_column,
            'embedding_column': embedding_column,
            'metadata_column': metadata_column,
            'id_column': id_column,
        })

    def _create_store(self) -> AbstractStore:
        """
        Create a vector store instance based on the StoreConfig.

        Returns:
            An AbstractStore instance configured according to store_config
        """
        store_name = self.store_config.vector_store
        store_cls_name = supported_stores.get(store_name)

        if not store_cls_name:
            raise ValueError(
                f"Unsupported vector store: {store_name}. "
                f"Supported stores: {list(supported_stores.keys())}"
            )

        # Import the store module
        cls_path = f"parrot.stores.{store_name}"
        try:
            module = importlib.import_module(cls_path)
            store_cls = getattr(module, store_cls_name)
        except ImportError as e:
            self.logger.error(f"Error importing VectorStore: {e}")
            raise ValueError(f"Could not import vector store '{store_name}': {e}") from e
        except AttributeError as e:
            self.logger.error(f"Store class not found: {e}")
            raise ValueError(f"Store class '{store_cls_name}' not found in module '{cls_path}'") from e

        # Prepare store configuration
        store_kwargs = {
            'embedding_model': self.store_config.embedding_model,
            'dimension': self.store_config.dimension,
            'metric_type': self.store_config.metric_type,
            'index_type': self.store_config.index_type,
        }

        if self.store_config.table:
            store_kwargs['table'] = self.store_config.table
        if self.store_config.schema:
            store_kwargs['schema'] = self.store_config.schema
        if self.store_config.dsn:
            store_kwargs['dsn'] = self.store_config.dsn

        # Add any extra configuration
        store_kwargs.update(self.store_config.extra)

        self.logger.info(
            f"Creating VectorStore: {store_cls.__name__} for {store_name} "
            f"with embedding {self.store_config.embedding_model}"
        )

        return store_cls(**store_kwargs)

    @property
    def store(self) -> AbstractStore:
        """Get or create the vector store instance."""
        if self._store is None:
            self._store = self._create_store()
        return self._store

    async def _execute(
        self,
        query: str,
        limit: int = 10,
        score_threshold: Optional[float] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        use_mmr: bool = False,
        lambda_mult: float = 0.5,
        **kwargs
    ) -> Union[List[Dict[str, Any]], ToolResult]:
        """
        Execute a similarity search on the vector store.

        Args:
            query: The search query
            limit: Maximum number of results to return
            score_threshold: Minimum similarity score threshold
            metadata_filters: Optional metadata filters
            use_mmr: Whether to use MMR search for diversity
            lambda_mult: Lambda multiplier for MMR search

        Returns:
            ToolResult containing the search results
        """
        try:
            async with self.store as store:
                # Build search kwargs
                search_kwargs = {
                    'query': query,
                    'table': self.store_config.table,
                    'schema': self.store_config.schema,
                    'limit': limit,
                    'content_column': self.content_column,
                    'embedding_column': self.embedding_column,
                    'metadata_column': self.metadata_column,
                    'id_column': self.id_column,
                }

                if score_threshold is not None:
                    search_kwargs['score_threshold'] = score_threshold

                if metadata_filters:
                    search_kwargs['metadata_filters'] = metadata_filters

                if self.additional_columns:
                    search_kwargs['additional_columns'] = self.additional_columns

                if use_mmr:
                    # Use MMR search for diverse results
                    search_kwargs['k'] = limit
                    search_kwargs['fetch_k'] = limit * 3
                    search_kwargs['lambda_mult'] = lambda_mult
                    # Remove limit since MMR uses 'k'
                    search_kwargs.pop('limit', None)

                    search_results = await store.mmr_search(**search_kwargs)
                else:
                    # Standard similarity search
                    search_results = await store.similarity_search(**search_kwargs)

                # Format results
                formatted_results = self._format_results(search_results)

                return ToolResult(
                    success=True,
                    status="success",
                    result=formatted_results,
                    metadata={
                        "query": query,
                        "result_count": len(formatted_results),
                        "search_type": "mmr" if use_mmr else "similarity",
                        "vector_store": self.store_config.vector_store,
                        "table": self.store_config.table,
                    }
                )

        except Exception as e:
            self.logger.error(f"Error during vector search: {e}")
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "query": query,
                    "vector_store": self.store_config.vector_store,
                }
            )

    def _format_results(
        self,
        search_results: List[SearchResult]
    ) -> List[Dict[str, Any]]:
        """
        Format search results into a consistent dictionary format.

        Args:
            search_results: List of SearchResult objects

        Returns:
            List of dictionaries with formatted results
        """
        formatted = []
        for idx, result in enumerate(search_results):
            formatted_result = {
                "rank": idx + 1,
                "id": result.id,
                "content": result.content,
                "score": result.score,
                "metadata": result.metadata,
            }

            # Add ensemble information if available
            if result.ensemble_score is not None:
                formatted_result["ensemble_score"] = result.ensemble_score
            if result.search_source:
                formatted_result["search_source"] = result.search_source
            if result.similarity_rank is not None:
                formatted_result["similarity_rank"] = result.similarity_rank
            if result.mmr_rank is not None:
                formatted_result["mmr_rank"] = result.mmr_rank

            formatted.append(formatted_result)

        return formatted

    async def search(
        self,
        query: str,
        limit: int = 10,
        score_threshold: Optional[float] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        use_mmr: bool = False,
        lambda_mult: float = 0.5,
    ) -> ToolResult:
        """
        Convenience method for executing a search.

        This is a wrapper around execute() with named parameters.

        Args:
            query: The search query
            limit: Maximum number of results to return
            score_threshold: Minimum similarity score threshold
            metadata_filters: Optional metadata filters
            use_mmr: Whether to use MMR search
            lambda_mult: Lambda multiplier for MMR

        Returns:
            ToolResult containing the search results
        """
        return await self.execute(
            query=query,
            limit=limit,
            score_threshold=score_threshold,
            metadata_filters=metadata_filters,
            use_mmr=use_mmr,
            lambda_mult=lambda_mult,
        )

    async def __call__(
        self,
        query: str,
        **kwargs
    ) -> ToolResult:
        """Allow the tool to be called directly as a function."""
        return await self.execute(query=query, **kwargs)
