from typing import Any, Dict, List, Optional, Union, Callable
import uuid
import time
import asyncio
from sklearn.metrics.pairwise import cosine_similarity, euclidean_distances
from google.cloud import bigquery as bq
from google.oauth2 import service_account
from google.cloud.exceptions import NotFound, Conflict
import numpy as np
import pandas as pd
from navconfig.logging import logging
from .abstract import AbstractStore
from ..conf import (
    BIGQUERY_CREDENTIALS,
    BIGQUERY_PROJECT_ID,
    BIGQUERY_DATASET
)
from .models import SearchResult, Document, DistanceStrategy
from .utils.chunking import LateChunkingProcessor
from ..exceptions import DriverError



class BigQueryStore(AbstractStore):
    """
    A BigQuery vector store implementation for storing and searching embeddings.
    This store provides vector similarity search capabilities using BigQuery's ML functions.
    """

    def __init__(
        self,
        table: str = None,
        dataset: str = None,
        project_id: str = None,
        credentials: str = None,
        id_column: str = 'id',
        embedding_column: str = 'embedding',
        document_column: str = 'document',
        text_column: str = 'text',
        metadata_column: str = 'metadata',
        embedding_model: Union[dict, str] = "sentence-transformers/all-mpnet-base-v2",
        embedding: Optional[Callable] = None,
        distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
        auto_initialize: bool = True,
        **kwargs
    ):
        """Initialize the BigQueryStore with the specified parameters."""
        self.table_name = table
        self.dataset = dataset or BIGQUERY_DATASET
        self._project_id = project_id or BIGQUERY_PROJECT_ID
        self._credentials = credentials or BIGQUERY_CREDENTIALS

        # Column definitions
        self._id_column: str = id_column
        self._embedding_column: str = embedding_column
        self._document_column: str = document_column
        self._text_column: str = text_column
        self._metadata_column: str = metadata_column

        # Configuration
        self.distance_strategy = distance_strategy
        self._auto_initialize: bool = auto_initialize
        self._collection_store_cache: Dict[str, Any] = {}

        # Initialize parent class
        super().__init__(
            embedding_model=embedding_model,
            embedding=embedding,
            **kwargs
        )

        # BigQuery client and session management
        self._connection: Optional[bq.Client] = None
        self._connected: bool = False
        self.credentials = None
        self._account = None

        # Initialize logger
        self.logger = logging.getLogger("BigQueryStore")

    def get_vector(self, metric_type: str = None, **kwargs):
        raise NotImplementedError("This method is part of the old implementation.")

    def _execute_query(
        self,
        query: str,
        job_config: Optional[bq.QueryJobConfig] = None
    ) -> List[Dict[str, Any]]:
        query_job = self._connection.query(query, job_config=job_config)
        return list(query_job.result())

    async def _thread_func(self, func, *args, **kwargs):
        """
        Run a synchronous function in an async context.
        Helper for running blocking calls in a non-blocking way.
        """
        return await asyncio.to_thread(func, *args, **kwargs)

    async def connection(self):
        """Initialize BigQuery client.
        Assuming that authentication is handled outside
        (via environment variables or similar)
        """
        try:
            if self._credentials:  # usage of explicit credentials
                self.credentials = service_account.Credentials.from_service_account_file(
                    self._credentials
                )
                if not self._project_id:
                    self._project_id = self.credentials.project_id
                self._connection = bq.Client(credentials=self.credentials, project=self._project_id)
                self._connected = True
            else:
                self.credentials = self._account
                self._connection = bq.Client(project=self._project_id)
                self._connected = True

            if self._auto_initialize:
                await self.initialize_database()

            self.logger.debug("Successfully connected to BigQuery.")

        except Exception as e:
            self._connected = False
            raise DriverError(f"BigQuery: Error initializing client: {e}")
        return self

    async def initialize_database(self):
        """Initialize BigQuery dataset and any required setup."""
        try:
            # Ensure dataset exists
            dataset_id = f"{self._project_id}.{self.dataset}"
            try:
                self._connection.get_dataset(dataset_id)
                self.logger.info(f"Dataset {dataset_id} already exists")
            except NotFound:
                # Create dataset if it doesn't exist
                dataset = bq.Dataset(dataset_id)
                dataset.location = "US"
                dataset = self._connection.create_dataset(dataset, timeout=30)
                self.logger.info(f"Created dataset {dataset_id}")

        except Exception as e:
            self.logger.warning(
                f"⚠️ Database auto-initialization failed: {e}"
            )

    def _define_collection_store(
        self,
        table: str,
        dataset: str,
        dimension: int = 384,
        id_column: str = 'id',
        embedding_column: str = 'embedding',
        document_column: str = 'document',
        metadata_column: str = 'metadata',
        text_column: str = 'text'
    ) -> str:
        """Define a collection store table name for BigQuery.

        Returns:
            str: Fully qualified table name in format project.dataset.table
        """
        full_table_name = f"{self._project_id}.{dataset}.{table}"

        if full_table_name in self._collection_store_cache:
            return self._collection_store_cache[full_table_name]

        # Cache the table reference
        self._collection_store_cache[full_table_name] = {
            'table_name': full_table_name,
            'dimension': dimension,
            'columns': {
                'id': id_column,
                'embedding': embedding_column,
                'document': document_column,
                'metadata': metadata_column,
                'text': text_column
            }
        }

        self.logger.debug(
            f"Defined collection store: {full_table_name}"
        )
        return full_table_name

    async def dataset_exists(self, dataset: str = None) -> bool:
        """Check if a dataset exists in BigQuery."""
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset
        dataset_id = f"{self._project_id}.{dataset}"

        try:
            self._connection.get_dataset(dataset_id)
            return True
        except NotFound:
            return False

    async def create_dataset(self, dataset: str = None, location: str = "US") -> Any:
        """Create a new dataset in BigQuery."""
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset

        try:
            dataset_ref = bq.DatasetReference(self._project_id, dataset)
            dataset_obj = bq.Dataset(dataset_ref)
            dataset_obj.location = location
            dataset_obj = self._connection.create_dataset(dataset_obj)
            self.logger.debug(f"Created dataset {self._project_id}.{dataset}")
            return dataset_obj
        except Conflict:
            self.logger.warning(f"Dataset {self._project_id}.{dataset} already exists")
            # Get the existing dataset to return it
            return self._connection.get_dataset(f"{self._project_id}.{dataset}")
        except Exception as exc:
            self.logger.error(f"Error creating Dataset: {exc}")
            raise DriverError(
                f"Error creating Dataset: {exc}"
            ) from exc

    async def collection_exists(self, table: str, dataset: str = None) -> bool:
        """Check if a collection (table) exists in BigQuery."""
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset
        table_id = f"{self._project_id}.{dataset}.{table}"

        try:
            await self._thread_func(self._connection.get_table, table_id)
            return True
        except NotFound:
            return False

    async def create_collection(
        self,
        table: str,
        dataset: str = None,
        dimension: int = 768,
        id_column: str = None,
        embedding_column: str = None,
        document_column: str = None,
        metadata_column: str = None,
        **kwargs
    ) -> None:
        """Create a new collection (table) in BigQuery."""
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset
        id_column = id_column or self._id_column
        embedding_column = embedding_column or self._embedding_column
        document_column = document_column or self._document_column
        metadata_column = metadata_column or self._metadata_column

        table_id = f"{self._project_id}.{dataset}.{table}"

        try:
            # Check if table already exists
            if await self.collection_exists(table, dataset):
                self.logger.info(f"Collection {table_id} already exists")
                return

            # Define table schema - use FLOAT64 REPEATED instead of STRUCT
            schema = [
                bq.SchemaField(id_column, "STRING", mode="REQUIRED"),
                bq.SchemaField(embedding_column, "FLOAT64", mode="REPEATED"),
                bq.SchemaField(document_column, "STRING", mode="NULLABLE"),
                bq.SchemaField(metadata_column, "JSON", mode="NULLABLE"),
                bq.SchemaField(self._text_column, "STRING", mode="NULLABLE"),
                bq.SchemaField("collection_id", "STRING", mode="NULLABLE"),
            ]

            table_ref = bq.Table(table_id, schema=schema)
            table_ref = await self._thread_func(self._connection.create_table, table_ref)

            self.logger.debug(f"Created collection {table_id}")

            # Cache the collection store
            self._define_collection_store(
                table=table,
                dataset=dataset,
                dimension=dimension,
                id_column=id_column,
                embedding_column=embedding_column,
                document_column=document_column,
                metadata_column=metadata_column
            )

        except Exception as e:
            self.logger.error(f"Error creating collection: {e}")
            raise RuntimeError(
                f"Failed to create collection: {e}"
            ) from e

    async def drop_collection(self, table: str, dataset: str = None) -> None:
        """
        Drops the specified table in the given dataset.

        Args:
            table: The name of the table to drop.
            dataset: The dataset where the table resides (optional, uses default if not provided).
        """
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset
        table_id = f"{self._project_id}.{dataset}.{table}"

        try:
            # Check if table exists first
            if not await self.collection_exists(table, dataset):
                self.logger.warning(f"Table '{table_id}' does not exist, nothing to drop")
                return

            # Drop the table
            self._connection.delete_table(table_id, not_found_ok=True)

            # Remove from cache if it exists
            if table_id in self._collection_store_cache:
                del self._collection_store_cache[table_id]

            self.logger.debug(f"Table '{table_id}' dropped successfully")

        except Exception as e:
            self.logger.error(
                f"Error dropping table '{table_id}': {e}"
            )
            raise RuntimeError(
                f"Failed to drop table '{table_id}': {e}"
            ) from e

    async def prepare_embedding_table(
        self,
        table: str,
        dataset: str = None,
        dimension: int = 768,
        id_column: str = 'id',
        embedding_column: str = 'embedding',
        document_column: str = 'document',
        metadata_column: str = 'metadata',
        **kwargs
    ) -> bool:
        """Prepare an existing BigQuery table for embedding storage."""
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset
        table_id = f"{self._project_id}.{dataset}.{table}"

        try:
            # Get existing table
            table_ref = self._connection.get_table(table_id)
            current_schema = table_ref.schema

            # Check if embedding columns already exist
            existing_fields = {field.name for field in current_schema}
            new_fields = []

            if embedding_column not in existing_fields:
                new_fields.append(
                    bq.SchemaField(
                        embedding_column,
                        "REPEATED",
                        mode="NULLABLE",
                        fields=[bq.SchemaField("value", "FLOAT64")]
                    )
                )

            if metadata_column not in existing_fields:
                new_fields.append(
                    bq.SchemaField(metadata_column, "JSON", mode="NULLABLE")
                )

            if "collection_id" not in existing_fields:
                new_fields.append(
                    bq.SchemaField("collection_id", "STRING", mode="NULLABLE")
                )

            # Add new fields if any
            if new_fields:
                new_schema = list(current_schema) + new_fields
                table_ref.schema = new_schema
                table_ref = self._connection.update_table(table_ref, ["schema"])
                self.logger.info(f"Updated table {table_id} schema with embedding columns")

            # Cache the collection store
            self._define_collection_store(
                table=table,
                dataset=dataset,
                dimension=dimension,
                id_column=id_column,
                embedding_column=embedding_column,
                document_column=document_column,
                metadata_column=metadata_column
            )

            return True

        except Exception as e:
            self.logger.error(f"Error preparing embedding table: {e}")
            raise RuntimeError(f"Failed to prepare embedding table: {e}") from e

    async def _wait_for_table_insert_ready(self, table_id: str, max_wait_seconds: int = 30, poll_interval: float = 0.5) -> bool:
        """
        Wait for a table to be ready for insert operations specifically.

        Args:
            table_id: Fully qualified table ID (project.dataset.table)
            max_wait_seconds: Maximum time to wait in seconds
            poll_interval: Time between polling attempts in seconds

        Returns:
            bool: True if table is ready for inserts, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < max_wait_seconds:
            try:
                # First check if table exists via get_table
                table_ref = await self._thread_func(self._connection.get_table, table_id)

                # Then test with a simple query to see if the table is accessible for operations
                # This is a lightweight way to test table readiness
                test_query = f"SELECT COUNT(*) as row_count FROM `{table_id}` LIMIT 1"
                query_job = await self._thread_func(self._connection.query, test_query)
                await self._thread_func(query_job.result)

                # If we get here without exception, table is ready for operations
                self.logger.debug(f"Table {table_id} is ready for insert operations")
                return True

            except NotFound:
                # Table not ready yet, wait and retry
                self.logger.debug(f"Table {table_id} not ready yet, waiting {poll_interval}s...")
                await asyncio.sleep(poll_interval)
            except Exception as e:
                # For other errors, we might want to continue trying for a bit
                # as BigQuery can have temporary inconsistencies
                self.logger.debug(f"Checking table readiness, got error (will retry): {e}")
                await asyncio.sleep(poll_interval)

        self.logger.warning(f"Table {table_id} not ready after {max_wait_seconds} seconds")
        return False

    async def add_documents(
        self,
        documents: List[Document],
        table: str = None,
        dataset: str = None,
        embedding_column: str = 'embedding',
        content_column: str = 'document',
        metadata_column: str = 'metadata',
        **kwargs
    ) -> None:
        """Add documents to BigQuery table with embeddings."""
        if not self._connected:
            await self.connection()

        table = table or self.table_name
        dataset = dataset or self.dataset

        if not table:
            raise ValueError("Table name must be provided")

        table_id = f"{self._project_id}.{dataset}.{table}"

        # Ensure collection exists
        if not await self.collection_exists(table, dataset):
            await self.create_collection(
                table=table,
                dataset=dataset,
                dimension=self.dimension
            )

        # If we just created the table, wait for it to be ready for inserts
        is_ready = await self._wait_for_table_insert_ready(table_id, max_wait_seconds=60)
        if not is_ready:
            raise RuntimeError(
                f"Table {table_id} was created but not ready for insert operations within timeout"
            )

        # Process documents
        texts = [doc.page_content for doc in documents]
        # Thread the embedding generation as it can be slow
        embeddings = await self._thread_func(self._embed_.embed_documents, texts)
        metadatas = [doc.metadata for doc in documents]

        # Prepare data for BigQuery (this is fast, no threading needed)
        rows_to_insert = []
        for i, doc in enumerate(documents):
            embedding_vector = embeddings[i]
            if isinstance(embedding_vector, np.ndarray):
                embedding_vector = embedding_vector.tolist()

            embedding_array = [float(val) for val in embedding_vector]

            metadata_value = metadatas[i] or {}
            metadata_json = self._json.dumps(metadata_value) if metadata_value else self._json.dumps({})

            row = {
                self._id_column: str(uuid.uuid4()),
                embedding_column: embedding_array,
                content_column: texts[i],
                metadata_column: metadata_json,
                "collection_id": str(uuid.uuid4())
            }
            rows_to_insert.append(row)

        # Insert data with retry logic and longer delays
        max_retries = 5
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                # Always get a fresh table reference
                table_ref = await self._thread_func(self._connection.get_table, table_id)

                # Add a small delay even on first attempt if table was just created
                if attempt == 0:
                    await asyncio.sleep(1.0)

                errors = await self._thread_func(
                    self._connection.insert_rows_json, table_ref, rows_to_insert
                )

                if errors:
                    self.logger.error(f"Errors inserting rows: {errors}")
                    raise RuntimeError(f"Failed to insert documents: {errors}")

                self.logger.info(f"Successfully added {len(documents)} documents to {table_id}")
                return  # Success, exit the retry loop

            except NotFound as e:
                if attempt < max_retries - 1:
                    self.logger.warning(
                        f"Table {table_id} not found for insert (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s..."
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10.0)  # Cap at 10 seconds
                else:
                    self.logger.error(
                        f"Table {table_id} still not found for insert after {max_retries} attempts"
                    )
                    raise
            except Exception as e:
                if attempt < max_retries - 1 and "not found" in str(e).lower():
                    # Treat any "not found" error as retryable
                    self.logger.warning(
                        f"Insert failed with 'not found' error (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s..."
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10.0)
                else:
                    self.logger.error(f"Error adding documents: {e}")
                    raise

    def _get_distance_function(self, metric: str = None) -> str:
        """Get BigQuery ML distance function based on strategy."""
        strategy = metric or self.distance_strategy

        if isinstance(strategy, str):
            metric_mapping = {
                'COSINE': DistanceStrategy.COSINE,
                'L2': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'EUCLIDEAN': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'DOT': DistanceStrategy.DOT_PRODUCT,
            }
            strategy = metric_mapping.get(strategy.upper(), DistanceStrategy.COSINE)

        if strategy == DistanceStrategy.COSINE:
            return "ML.DISTANCE"  # Cosine distance in BigQuery ML
        elif strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
            return "ML.EUCLIDEAN_DISTANCE"
        elif strategy == DistanceStrategy.DOT_PRODUCT:
            return "ML.DOT_PRODUCT"
        else:
            return "ML.DISTANCE"  # Default to cosine

    async def similarity_search(
        self,
        query: str,
        table: str = None,
        dataset: str = None,
        k: Optional[int] = None,
        limit: int = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
        metric: str = None,
        embedding_column: str = 'embedding',
        content_column: str = 'document',
        metadata_column: str = 'metadata',
        id_column: str = 'id',
        **kwargs
    ) -> List[SearchResult]:
        """Perform similarity search using BigQuery ML functions."""
        if not self._connected:
            await self.connection()

        table = table or self.table_name
        dataset = dataset or self.dataset

        if k and not limit:
            limit = k
        if not limit:
            limit = 10

        table_id = f"{self._project_id}.{dataset}.{table}"

        # Get query embedding
        # query_embedding = self._embed_.embed_query(query)
        query_embedding = await self._thread_func(self._embed_.embed_query, query)
        if isinstance(query_embedding, np.ndarray):
            query_embedding = query_embedding.tolist()

        # Convert embedding to BigQuery array literal format
        embedding_literal = "[" + ",".join([str(float(val)) for val in query_embedding]) + "]"

        # Build the SQL query
        distance_func = self._get_distance_function(metric)

        # Create the SQL query with embedded array literal
        sql_query = f"""
        SELECT
            {id_column},
            {content_column},
            {metadata_column},
            {distance_func}({embedding_column}, {embedding_literal}) as distance
        FROM `{table_id}`
        WHERE {embedding_column} IS NOT NULL
        """

        # Add metadata filters
        filter_params = []
        if metadata_filters:
            filter_conditions = []
            for key, value in metadata_filters.items():
                if isinstance(value, str):
                    filter_conditions.append(f"JSON_EXTRACT_SCALAR({metadata_column}, '$.{key}') = @filter_{key}")
                    filter_params.append(bq.ScalarQueryParameter(f"filter_{key}", "STRING", value))
                else:
                    filter_conditions.append(f"JSON_EXTRACT_SCALAR({metadata_column}, '$.{key}') = @filter_{key}")
                    filter_params.append(bq.ScalarQueryParameter(f"filter_{key}", "STRING", str(value)))

            if filter_conditions:
                sql_query += " AND " + " AND ".join(filter_conditions)

        # Add score threshold
        if score_threshold is not None:
            sql_query += f" AND {distance_func}({embedding_column}, {embedding_literal}) <= {score_threshold}"

        # Order and limit
        sql_query += f" ORDER BY distance ASC"
        if limit:
            sql_query += f" LIMIT {limit}"

        # Configure query parameters
        job_config = None
        if filter_params:
            job_config = bq.QueryJobConfig(
                query_parameters=filter_params
            )

        try:
            # Execute query
            query_job = await self._thread_func(
                self._connection.query, sql_query, job_config=job_config
            )
            results = await self._thread_func(query_job.result)

            # Process results
            search_results = []
            for row in results:
                metadata_str = row[metadata_column]
                if isinstance(metadata_str, str):
                    # Ensure metadata is a JSON string
                    metadata_str = metadata_str.strip()
                    metadata = self._json.loads(metadata_str)
                else:
                    metadata = dict(metadata_str) if metadata_str else {}

                search_result = SearchResult(
                    id=row[id_column],
                    content=row[content_column],
                    metadata=metadata,
                    score=float(row.distance)
                )
                search_results.append(search_result)

            self.logger.debug(
                f"Similarity search returned {len(search_results)} results"
            )
            return search_results

        except Exception as e:
            self.logger.error(f"Error during similarity search: {e}")
            raise

    async def mmr_search(
        self,
        query: str,
        table: str = None,
        dataset: str = None,
        k: int = 10,
        fetch_k: int = None,
        lambda_mult: float = 0.5,
        metadata_filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
        metric: str = None,
        embedding_column: str = 'embedding',
        content_column: str = 'document',
        metadata_column: str = 'metadata',
        id_column: str = 'id',
        **kwargs
    ) -> List[SearchResult]:
        """
        Perform Maximal Marginal Relevance (MMR) search.

        Since BigQuery doesn't have native MMR support, we fetch more candidates
        and perform MMR selection in Python.
        """
        if not self._connected:
            await self.connection()

        # Default to fetching 3x more candidates than final results
        if fetch_k is None:
            fetch_k = max(k * 3, 20)

        # Step 1: Get initial candidates using similarity search
        candidates = await self.similarity_search(
            query=query,
            table=table,
            dataset=dataset,
            limit=fetch_k,
            metadata_filters=metadata_filters,
            score_threshold=score_threshold,
            metric=metric,
            embedding_column=embedding_column,
            content_column=content_column,
            metadata_column=metadata_column,
            id_column=id_column,
            **kwargs
        )

        if len(candidates) <= k:
            return candidates

        # Step 2: Fetch embeddings for MMR computation
        candidate_embeddings = await self._fetch_embeddings_for_mmr(
            candidate_ids=[result.id for result in candidates],
            table=table,
            dataset=dataset,
            embedding_column=embedding_column,
            id_column=id_column
        )

        # Step 3: Get query embedding
        query_embedding = self._embed_.embed_query(query)

        # Step 4: Run MMR algorithm
        selected_results = self._mmr_algorithm(
            query_embedding=query_embedding,
            candidates=candidates,
            candidate_embeddings=candidate_embeddings,
            k=k,
            lambda_mult=lambda_mult,
            metric=metric or self.distance_strategy
        )

        self.logger.info(
            f"MMR search selected {len(selected_results)} results from {len(candidates)} candidates"
        )

        return selected_results

    async def _fetch_embeddings_for_mmr(
        self,
        candidate_ids: List[str],
        table: str,
        dataset: str,
        embedding_column: str,
        id_column: str
    ) -> Dict[str, np.ndarray]:
        """Fetch embedding vectors for candidate documents from BigQuery."""
        table_id = f"{self._project_id}.{dataset}.{table}"

        # Create placeholders for the IDs
        id_placeholders = ', '.join([f"'{id_}'" for id_ in candidate_ids])

        sql_query = f"""
        SELECT {id_column}, {embedding_column}
        FROM `{table_id}`
        WHERE {id_column} IN ({id_placeholders})
        """

        try:
            query_job = await self._thread_func(self._connection.query, sql_query)
            results = await self._thread_func(query_job.result)

            embeddings_dict = {}
            for row in results:
                doc_id = row[id_column]
                embedding_data = row[embedding_column]

                # Convert BigQuery array format back to numpy array
                if embedding_data:
                    embedding_values = [item['value'] for item in embedding_data]
                    embedding_values = embedding_data if isinstance(embedding_data, list) else embedding_data.tolist()
                    embeddings_dict[doc_id] = np.array(embedding_values, dtype=np.float32)

            return embeddings_dict

        except Exception as e:
            self.logger.error(f"Error fetching embeddings for MMR: {e}")
            raise

    def _mmr_algorithm(
        self,
        query_embedding: np.ndarray,
        candidates: List[SearchResult],
        candidate_embeddings: Dict[str, np.ndarray],
        k: int,
        lambda_mult: float,
        metric: str
    ) -> List[SearchResult]:
        """Core MMR algorithm implementation (same as PgVectorStore)."""
        if len(candidates) <= k:
            return candidates

        # Convert query embedding to numpy array
        if not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        # Prepare data structures
        selected_indices = []
        remaining_indices = list(range(len(candidates)))

        # Step 1: Select the most relevant document first
        query_similarities = []
        for candidate in candidates:
            doc_embedding = candidate_embeddings.get(candidate.id)
            if doc_embedding is not None:
                similarity = self._compute_similarity(query_embedding, doc_embedding, metric)
                query_similarities.append(similarity)
            else:
                # Fallback to distance score if embedding not available
                query_similarities.append(1.0 / (1.0 + candidate.score))

        # Select the most similar document first
        best_idx = np.argmax(query_similarities)
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)

        # Step 2: Iteratively select remaining documents using MMR
        for _ in range(min(k - 1, len(remaining_indices))):
            mmr_scores = []

            for idx in remaining_indices:
                candidate = candidates[idx]
                doc_embedding = candidate_embeddings.get(candidate.id)

                if doc_embedding is None:
                    # Fallback scoring if embedding not available
                    mmr_score = lambda_mult * query_similarities[idx]
                    mmr_scores.append(mmr_score)
                    continue

                # Relevance: similarity to query
                relevance = query_similarities[idx]

                # Diversity: maximum similarity to already selected documents
                max_similarity_to_selected = 0.0
                for selected_idx in selected_indices:
                    selected_candidate = candidates[selected_idx]
                    selected_embedding = candidate_embeddings.get(selected_candidate.id)

                    if selected_embedding is not None:
                        similarity = self._compute_similarity(doc_embedding, selected_embedding, metric)
                        max_similarity_to_selected = max(max_similarity_to_selected, similarity)

                # MMR formula: λ * relevance - (1-λ) * max_similarity_to_selected
                mmr_score = (
                    lambda_mult * relevance -
                    (1.0 - lambda_mult) * max_similarity_to_selected
                )
                mmr_scores.append(mmr_score)

            # Select document with highest MMR score
            if mmr_scores:
                best_remaining_idx = np.argmax(mmr_scores)
                best_idx = remaining_indices[best_remaining_idx]
                selected_indices.append(best_idx)
                remaining_indices.remove(best_idx)

        # Step 3: Return selected results with MMR scores in metadata
        selected_results = []
        for i, idx in enumerate(selected_indices):
            result = candidates[idx]
            # Add MMR ranking to metadata
            enhanced_metadata = dict(result.metadata)
            enhanced_metadata['mmr_rank'] = i + 1
            enhanced_metadata['mmr_lambda'] = lambda_mult
            enhanced_metadata['original_rank'] = idx + 1

            enhanced_result = SearchResult(
                id=result.id,
                content=result.content,
                metadata=enhanced_metadata,
                score=result.score
            )
            selected_results.append(enhanced_result)

        return selected_results

    def _compute_similarity(
        self,
        embedding1: np.ndarray,
        embedding2: np.ndarray,
        metric: Union[str, Any]
    ) -> float:
        """Compute similarity between two embeddings (same as PgVectorStore)."""
        # Convert to numpy arrays if needed
        if isinstance(embedding1, list):
            embedding1 = np.array(embedding1, dtype=np.float32)
        if isinstance(embedding2, list):
            embedding2 = np.array(embedding2, dtype=np.float32)

        # Ensure embeddings are numpy arrays
        if not isinstance(embedding1, np.ndarray):
            embedding1 = np.array(embedding1, dtype=np.float32)
        if not isinstance(embedding2, np.ndarray):
            embedding2 = np.array(embedding2, dtype=np.float32)

        # Ensure embeddings are 2D arrays for sklearn
        emb1 = embedding1.reshape(1, -1)
        emb2 = embedding2.reshape(1, -1)

        # Convert string metrics to DistanceStrategy enum if needed
        if isinstance(metric, str):
            metric_mapping = {
                'COSINE': DistanceStrategy.COSINE,
                'L2': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'EUCLIDEAN': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'DOT': DistanceStrategy.DOT_PRODUCT,
            }
            strategy = metric_mapping.get(metric.upper(), DistanceStrategy.COSINE)
        else:
            strategy = metric

        if strategy == DistanceStrategy.COSINE:
            # Cosine similarity
            similarity = cosine_similarity(emb1, emb2)[0, 0]
            return float(similarity)
        elif strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
            # Convert Euclidean distance to similarity
            distance = euclidean_distances(emb1, emb2)[0, 0]
            similarity = 1.0 / (1.0 + distance)
            return float(similarity)
        elif strategy == DistanceStrategy.DOT_PRODUCT:
            # Dot product
            similarity = np.dot(embedding1.flatten(), embedding2.flatten())
            return float(similarity)
        else:
            # Default to cosine similarity
            similarity = cosine_similarity(emb1, emb2)[0, 0]
            return float(similarity)

    async def delete_documents(
        self,
        documents: Optional[List[Document]] = None,
        pk: str = 'source_type',
        values: Optional[Union[str, List[str]]] = None,
        table: Optional[str] = None,
        dataset: Optional[str] = None,
        metadata_column: Optional[str] = None,
        **kwargs
    ) -> int:
        """Delete documents from BigQuery table based on metadata field values."""
        if not self._connected:
            await self.connection()

        table = table or self.table_name
        dataset = dataset or self.dataset
        metadata_column = metadata_column or self._metadata_column

        if not table:
            raise ValueError("Table name must be provided")

        table_id = f"{self._project_id}.{dataset}.{table}"

        # Extract values to delete
        delete_values = []
        if values is not None:
            if isinstance(values, str):
                delete_values = [values]
            else:
                delete_values = list(values)
        elif documents:
            for doc in documents:
                if hasattr(doc, 'metadata') and doc.metadata and pk in doc.metadata:
                    value = doc.metadata[pk]
                    if value and value not in delete_values:
                        delete_values.append(value)
        else:
            raise ValueError("Either 'documents' or 'values' parameter must be provided")

        if not delete_values:
            self.logger.warning(f"No values found for field '{pk}' to delete")
            return 0

        deleted_count = 0

        try:
            for value in delete_values:
                # Create delete query using JSON extraction
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE JSON_EXTRACT_SCALAR({metadata_column}, '$.{pk}') = @value
                """

                job_config = bq.QueryJobConfig(
                    query_parameters=[
                        bq.ScalarQueryParameter("value", "STRING", str(value))
                    ]
                )

                query_job = await self._thread_func(
                    self._connection.query,
                    delete_query,
                    job_config=job_config
                )
                await self._thread_func(query_job.result)

                rows_deleted = query_job.num_dml_affected_rows or 0
                deleted_count += rows_deleted

                self.logger.info(
                    f"Deleted {rows_deleted} documents with {pk}='{value}' from {table_id}"
                )

            self.logger.info(f"Total deleted: {deleted_count} documents")
            return deleted_count

        except Exception as e:
            self.logger.error(f"Error deleting documents: {e}")
            raise RuntimeError(f"Failed to delete documents: {e}") from e

    async def delete_documents_by_filter(
        self,
        filter_dict: Dict[str, Union[str, List[str]]],
        table: Optional[str] = None,
        dataset: Optional[str] = None,
    ) -> int:
        """Deletes documents based on multiple metadata field conditions."""
        if not self._connected: await self.connection()
        if not filter_dict: raise ValueError("filter_dict cannot be empty")

        table = table or self.table_name
        dataset = dataset or self.dataset
        table_id = f"`{self._project_id}.{dataset}.{table}`"

        where_conditions = []
        query_params = []
        for i, (field, values) in enumerate(filter_dict.items()):
            safe_field = field.replace("'", "\\'")
            if isinstance(values, (list, tuple)):
                param_name = f"val_{i}"
                where_conditions.append(f"JSON_VALUE({self._metadata_column}, '$.{safe_field}') IN UNNEST(@{param_name})")
                query_params.append(bq.ArrayQueryParameter(param_name, "STRING", [str(v) for v in values]))
            else:
                param_name = f"val_{i}"
                where_conditions.append(f"JSON_VALUE({self._metadata_column}, '$.{safe_field}') = @{param_name}")
                query_params.append(bq.ScalarQueryParameter(param_name, "STRING", str(values)))

        where_clause = " AND ".join(where_conditions)
        delete_query = f"DELETE FROM {table_id} WHERE {where_clause}"
        job_config = bq.QueryJobConfig(query_parameters=query_params)

        try:
            query_job = await self._thread_func(
                self._connection.query, delete_query, job_config=job_config
            )
            await self._thread_func(query_job.result)
            deleted_count = query_job.num_dml_affected_rows or 0
            self.logger.debug(
                f"Deleted {deleted_count} documents from {table_id} with filter: {filter_dict}"
            )
            return deleted_count
        except Exception as e:
            raise RuntimeError(
                f"Failed to delete documents by filter: {e}"
            ) from e


    async def delete_documents_by_ids(
        self,
        document_ids: List[str],
        table: Optional[str] = None,
        dataset: Optional[str] = None,
        id_column: Optional[str] = None,
        **kwargs
    ) -> int:
        """Delete documents by their IDs."""
        if not self._connected:
            await self.connection()

        if not document_ids:
            self.logger.warning("No document IDs provided for deletion")
            return 0

        table = table or self.table_name
        dataset = dataset or self.dataset
        id_column = id_column or self._id_column

        if not table:
            raise ValueError("Table name must be provided")

        table_id = f"{self._project_id}.{dataset}.{table}"

        # Build parameterized query for multiple IDs
        query_parameters = []
        value_params = []
        for i, doc_id in enumerate(document_ids):
            param_name = f"id_{i}"
            value_params.append(f"@{param_name}")
            query_parameters.append(
                bq.ScalarQueryParameter(param_name, "STRING", str(doc_id))
            )

        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE {id_column} IN ({', '.join(value_params)})
        """

        try:
            job_config = bq.QueryJobConfig(query_parameters=query_parameters)
            query_job = self._connection.query(delete_query, job_config=job_config)
            query_job.result()  # Wait for completion

            deleted_count = query_job.num_dml_affected_rows or 0

            self.logger.info(
                f"Deleted {deleted_count} documents by IDs from {table_id}"
            )

            return deleted_count

        except Exception as e:
            self.logger.error(f"Error deleting documents by IDs: {e}")
            raise RuntimeError(
                f"Failed to delete documents by IDs: {e}"
            ) from e

    async def delete_all_documents(
        self,
        table: Optional[str] = None,
        dataset: Optional[str] = None,
        confirm: bool = False,
        **kwargs
    ) -> int:
        """Delete ALL documents from the BigQuery table."""
        if not confirm:
            raise ValueError(
                "This operation will delete ALL documents. "
                "Set confirm=True to proceed."
            )

        if not self._connected:
            await self.connection()

        table = table or self.table_name
        dataset = dataset or self.dataset

        if not table:
            raise ValueError("Table name must be provided")

        table_id = f"{self._project_id}.{dataset}.{table}"

        try:
            # First count existing documents
            count_query = f"SELECT COUNT(*) as total FROM `{table_id}`"
            count_job = self._connection.query(count_query)
            count_result = list(count_job.result())[0]
            total_docs = count_result.total

            if total_docs == 0:
                self.logger.info(f"No documents to delete from {table_id}")
                return 0

            # Delete all documents
            delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
            query_job = self._connection.query(delete_query)
            query_job.result()  # Wait for completion

            deleted_count = query_job.num_dml_affected_rows or 0

            self.logger.warning(
                f"DELETED ALL {deleted_count} documents from {table_id}"
            )

            return deleted_count

        except Exception as e:
            self.logger.error(f"Error deleting all documents: {e}")
            raise RuntimeError(f"Failed to delete all documents: {e}") from e

    async def count_documents_by_filter(
        self,
        filter_dict: Dict[str, Union[str, List[str]]],
        table: Optional[str] = None,
        dataset: Optional[str] = None,
        metadata_column: Optional[str] = None,
        **kwargs
    ) -> int:
        """Count documents that would be affected by a filter."""
        if not self._connected:
            await self.connection()

        if not filter_dict:
            return 0

        table = table or self.table_name
        dataset = dataset or self.dataset
        metadata_column = metadata_column or self._metadata_column

        if not table:
            raise ValueError("Table name must be provided")

        table_id = f"{self._project_id}.{dataset}.{table}"

        # Build WHERE conditions (same logic as delete_documents_by_filter)
        where_conditions = []
        query_parameters = []

        for field, values in filter_dict.items():
            if isinstance(values, (list, tuple)):
                value_params = []
                for i, value in enumerate(values):
                    param_name = f"{field}_{i}"
                    value_params.append(f"@{param_name}")
                    query_parameters.append(
                        bq.ScalarQueryParameter(param_name, "STRING", str(value))
                    )

                condition = f"JSON_EXTRACT_SCALAR({metadata_column}, '$.{field}') IN ({', '.join(value_params)})"
                where_conditions.append(condition)
            else:
                param_name = f"{field}_single"
                where_conditions.append(f"JSON_EXTRACT_SCALAR({metadata_column}, '$.{field}') = @{param_name}")
                query_parameters.append(
                    bq.ScalarQueryParameter(param_name, "STRING", str(values))
                )

        where_clause = " AND ".join(where_conditions)
        count_query = f"""
        SELECT COUNT(*) as total FROM `{table_id}`
        WHERE {where_clause}
        """

        try:
            job_config = bq.QueryJobConfig(query_parameters=query_parameters)
            query_job = self._connection.query(count_query, job_config=job_config)
            result = list(query_job.result())[0]
            count = result.total

            self.logger.info(
                f"Found {count} documents matching filter: {filter_dict}"
            )

            return count

        except Exception as e:
            self.logger.error(f"Error counting documents: {e}")
            raise RuntimeError(f"Failed to count documents: {e}") from e

    async def delete_collection(
        self,
        table: str,
        dataset: str = None
    ) -> None:
        """Delete a collection (table) from BigQuery."""
        if not self._connected:
            await self.connection()

        dataset = dataset or self.dataset
        table_id = f"{self._project_id}.{dataset}.{table}"

        if not await self.collection_exists(table, dataset):
            raise RuntimeError(f"Collection {table_id} does not exist")

        try:
            self._connection.delete_table(table_id)
            self.logger.info(f"Collection {table_id} deleted successfully")

            # Remove from cache
            if table_id in self._collection_store_cache:
                del self._collection_store_cache[table_id]

        except Exception as e:
            self.logger.error(f"Error deleting collection: {e}")
            raise RuntimeError(f"Failed to delete collection: {e}") from e

    async def from_documents(
        self,
        documents: List[Document],
        table: str = None,
        dataset: str = None,
        embedding_column: str = 'embedding',
        content_column: str = 'document',
        metadata_column: str = 'metadata',
        chunk_size: int = 8192,
        chunk_overlap: int = 200,
        store_full_document: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Add documents using late chunking strategy (if available)."""
        if not self._connected:
            await self.connection()

        table = table or self.table_name
        dataset = dataset or self.dataset

        if not table:
            raise ValueError("Table name must be provided")

        # For BigQuery, we'll implement a simpler version without late chunking
        # since LateChunkingProcessor might not be available
        await self.add_documents(
            documents=documents,
            table=table,
            dataset=dataset,
            embedding_column=embedding_column,
            content_column=content_column,
            metadata_column=metadata_column,
            **kwargs
        )

        stats = {
            'documents_processed': len(documents),
            'chunks_created': 0,  # Not implementing chunking in this version
            'full_documents_stored': len(documents)
        }

        return stats

    # Context manager support
    async def __aenter__(self):
        """Context manager entry."""
        if not self._connected:
            await self.connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # BigQuery client doesn't need explicit cleanup
        pass

    async def disconnect(self) -> None:
        """Disconnect from BigQuery (cleanup resources)."""
        if self._connection:
            self._connection.close()
            self._connection = None
            self._connected = False
            self.logger.info("BigQuery client disconnected")

    def __str__(self) -> str:
        return f"BigQueryStore(project={self._project_id}, dataset={self.dataset})"

    def __repr__(self) -> str:
        return (
            f"<BigQueryStore(project='{self._project_id}', "
            f"dataset='{self.dataset}', table='{self.table_name}')>"
        )
