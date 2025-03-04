"""
Powerful PostgreSQL Vector Database Store with Custom Table Support.
"""
from typing import (
    Any,
    Dict,
    List,
    Tuple,
    Union,
    Optional,
    Sequence
)
from collections.abc import Callable
import asyncio
import uuid
# SQL Alchemy
import sqlalchemy
from sqlalchemy import inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, ARRAY, Float, JSON, text, func
from sqlalchemy.dialects.postgresql import JSON, JSONB, JSONPATH, UUID, insert
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
# PgVector
from pgvector.sqlalchemy import Vector  # type: ignore
# Langchain
from langchain_core.embeddings import Embeddings
from langchain.docstore.document import Document
from langchain.memory import VectorStoreRetrieverMemory
from langchain_community.vectorstores.pgembedding import PGEmbedding
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_postgres.vectorstores import (
    PGVector,
    _get_embedding_collection_store,
    _results_to_docs
)
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from .abstract import AbstractStore



Base = declarative_base()


# Define the async classmethods to be attached to our ORM model.
async def aget_by_name(cls, session: AsyncSession, name: str) -> Optional["CustomEmbeddingStore"]:
    # result = await session.execute(select(cls).where(cls.name == name))
    # return result.scalars().first()
    return cls(cmetadata={})


class PgVector(PGVector):
    """
    PgVector extends PGVector so that it uses an existing table from a specified schema.

    When instantiating, you provide:
    - connection: an AsyncEngine (or synchronous engine) to your PostgreSQL database.
    - schema: the database schema where your table lives.
    - table_name: the name of the table that stores the embeddings.
    - embedding_length: the dimension of the embedding vectors.
    - embeddings: your embedding function/model (which must provide embed_query).

    This implementation overrides the _get_embedding_collection_store method to return a tuple of
    ORM model classes that both refer to your table. It validates (using SQLAlchemy’s inspector)
    that the table contains the required columns: 'id', 'embedding', 'document', and 'cmetadata'.

    The returned ORM models can then be used by PGVector’s built-in similarity search and retriever.
    """
    def __init__(
        self,
        embeddings: Embeddings,
        *,
        table_name: str = None,
        schema: str = 'public',
        collection_name: Optional[str] = None,
        id_column: str = 'id',
        **kwargs
    ) -> None:
        self.table_name = table_name
        self.schema = schema
        self._id_column: str = id_column
        self._schema_based: bool = False
        if self.table_name:
            self._schema_based: bool = True
        elif '.' in collection_name:
            self.schema, self.table_name = collection_name.split('.')
            self._schema_based: bool = True
        super().__init__(
            embeddings=embeddings,
            collection_name=collection_name,
            **kwargs
        )

    async def _get_embedding_collection_store(
        self,
        table: str,
        schema: str,
        dimension: int = 768,
        **kwargs
    ) -> Tuple[type, type]:
        """
        Return custom ORM model classes (EmbeddingStore, CollectionStore)
        that both reference the same table.

        In this custom implementation, both the "collection" and "embedding" stores
        are represented by a single table.
        The table is expected to have the following columns:
        - id: unique identifier (String)
        - embedding: the vector column (Vector(dimension))
        - document: text column containing the document
        - cmetadata: JSONB column for metadata

        Raises an error if the table does not have the required schema.
        """
        # Dynamically create the model class.
        attrs = {
            '__tablename__': table,
            '__table_args__': {"schema": schema},
            self._id_column: sqlalchemy.Column(
                sqlalchemy.String,
                primary_key=True,
                index=True,
                unique=True,
                default=lambda: str(uuid.uuid4())
            ),
            'embedding': sqlalchemy.Column(Vector(dimension)),
            'document': sqlalchemy.Column(sqlalchemy.String, nullable=True),
            'cmetadata': sqlalchemy.Column(JSONB, nullable=True),
            # Attach the async classmethods.
            'aget_by_name': classmethod(aget_by_name),
            # 'aget_or_create': classmethod(aget_or_create)
        }
        EmbeddingStore = type("CustomEmbeddingStore", (Base,), attrs)
        EmbeddingStore.__name__ = "EmbeddingStore"
        return (EmbeddingStore, EmbeddingStore)

    async def __apost_init__(
        self,
    ) -> None:
        """Async initialize the store (use lazy approach)."""
        if self._async_init:  # Warning: possible race condition
            return
        self._async_init = True
        if self._schema_based:
            ebstore, cstore = await self._get_embedding_collection_store(
                table=self.table_name,
                schema=self.schema,
                dimension=self._embedding_length
            )
        else:
            ebstore, cstore = _get_embedding_collection_store(
                self._embedding_length
            )
        self.CollectionStore = cstore
        self.EmbeddingStore = ebstore

        if not self._schema_based:
            await self.acreate_tables_if_not_exists()
            await self.acreate_collection()

    async def asimilarity_search(
        self,
        query: str,
        k: int = 4,
        score_threshold: Optional[float] = None,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        """Run similarity search with PGVector with distance.

        Args:
            query (str): Query text to search for.
            k (int): Number of results to return. Defaults to 4.
            filter (Optional[Dict[str, str]]): Filter by metadata. Defaults to None.

        Returns:
            List of Documents most similar to the query.
        """
        await self.__apost_init__()  # Lazy async init
        embedding = await self.embeddings.aembed_query(query)
        return await self.asimilarity_search_by_vector(
            embedding=embedding,
            k=k,
            score_threshold=score_threshold,
            filter=filter,
        )

    async def asimilarity_search_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        score_threshold: Optional[float] = None,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        """Return docs most similar to embedding vector.

        Args:
            embedding: Embedding to look up documents similar to.
            k: Number of Documents to return. Defaults to 4.
            filter (Optional[Dict[str, str]]): Filter by metadata. Defaults to None.

        Returns:
            List of Documents most similar to the query vector.
        """
        assert self._async_engine, "This method must be called with async_mode"
        await self.__apost_init__()  # Lazy async init
        docs_and_scores = await self.asimilarity_search_with_score_by_vector(
            embedding=embedding, k=k, score_threshold=score_threshold, filter=filter
        )
        return _results_to_docs(docs_and_scores)

    async def asimilarity_search_with_score_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        score_threshold: Optional[float] = None,
        filter: Optional[dict] = None,
    ) -> List[Tuple[Document, float]]:
        await self.__apost_init__()  # Lazy async init
        async with self._make_async_session() as session:  # type: ignore[arg-type]
            results = await self._aquery_collection(
                session=session, embedding=embedding, k=k, score_threshold=score_threshold, filter=filter
            )
            return self._results_to_docs_and_scores(results)

    async def _aquery_collection(
        self,
        session: AsyncSession,
        embedding: List[float],
        k: int = 4,
        score_threshold: Optional[float] = None,
        filter: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[Document, float]]:
        """Search for similar documents in the collection.

        If score_threshold is provided, returns all documents whose computed distance is below that threshold.
        Otherwise, if k is provided, returns at most k documents.
        """
        async with self._make_async_session() as session:  # type: ignore[arg-type]
            filter_by = []
            if filter:
                if self.use_jsonb:
                    filter_clause = self._create_filter_clause(filter)
                    if filter_clause is not None:
                        filter_by.append(filter_clause)
                else:
                    # For non-JSONB cases, you might use a deprecated method:
                    filter_clauses = self._create_filter_clause_json_deprecated(filter)
                    filter_by.extend(filter_clauses)

            # Compute the distance expression
            distance_expr = self.distance_strategy(embedding).label("distance")
            stmt = (
                sqlalchemy.select(
                    self.EmbeddingStore,
                    self.distance_strategy(embedding).label("distance")
                )
                .filter(*filter_by)
            )
            # If a score threshold is provided, add a filter on the distance.
            if score_threshold is not None:
                stmt = stmt.filter(distance_expr < score_threshold)
            else:
                # Otherwise, limit the number of results.
                stmt = stmt.order_by(distance_expr).limit(k)

            stmt = stmt.order_by(sqlalchemy.asc(distance_expr))
            # Execute the query and return the results.
            results: Sequence[Any] = (await session.execute(stmt)).all()
            return results

    def _results_to_docs_and_scores(self, results: Any) -> List[Tuple[Document, float]]:
        """Return docs and scores from results."""
        id_col = getattr(self, "_id_column", "id")
        docs = [
            (
                Document(
                    id=str(getattr(result.EmbeddingStore, id_col)),
                    page_content=result.EmbeddingStore.document,
                    metadata=result.EmbeddingStore.cmetadata,
                ),
                result.distance if self.embeddings is not None else None,
            )
            for result in results
        ]
        return docs


class PgvectorStore(AbstractStore):
    """Pgvector Store Class.

    Using PostgreSQL + PgVector to saving vectors in database.
    """
    def __init__(
        self,
        embedding_model: Union[dict, str] = None,
        embedding: Union[dict, Callable] = None,
        **kwargs
    ):
        super().__init__(
            embedding_model=embedding_model,
            embedding=embedding,
            **kwargs
        )
        self.table: str = kwargs.get('table', None)
        self.schema: str = kwargs.get('schema', 'public')
        self._id_column = kwargs.get('id_column', 'id')
        if self.table and not self.collection_name:
            self.collection_name = f"{self.schema}.{self.table}"
        self.dsn = kwargs.get('dsn', self.database)
        self._drop: bool = kwargs.pop('drop', False)
        self._connection: AsyncEngine = None

    async def collection_exists(self, collection: str = None) -> bool:
        """Check if a collection exists in the database."""
        if not collection:
            collection = self.collection_name
        async with self._connection.connect() as conn:
            # ✅ Check if the collection (table) exists
            check_query = f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = '{collection}'
            );
            """
            result = await conn.execute(sqlalchemy.text(check_query))
            return bool(result.scalar())

    async def connection(self, alias: str = None):
        """Connection to DuckDB.

        Args:
            alias (str): Database alias.

        Returns:
            Callable: DuckDB connection.

        """
        self._connection = create_async_engine(self.dsn, future=True, echo=False)
        async with self._connection.begin() as conn:
            if getattr(self, "_drop", False):
                vectorstore = PgVector(
                    embeddings=self._embed_.embedding,
                    table_name=self.table,
                    schema=self.schema,
                    id_column=self._id_column,
                    collection_name=self.collection_name,
                    embedding_length=self.dimension,
                    connection=self._connection,
                    use_jsonb=True,
                    create_extension=False
                )
                await vectorstore.adrop_tables()
            if not await self.collection_exists(self.collection_name):
                print(f"⚠️ Collection `{self.collection_name}` not found. Creating a new one...")
                await self.create_collection(self.collection_name)
        self._connected = True
        return self._connection

    def engine(self):
        return self._connection

    async def disconnect(self) -> None:
        """
        Closing the Connection on DuckDB
        """
        try:
            if self._connection:
                await self._connection.dispose()
        except Exception as err:
            raise RuntimeError(
                message=f"{__name__!s}: Closing Error: {err!s}"
            ) from err
        finally:
            self._connection = None
            self._connected = False

    async def create_collection(self, collection: str) -> None:
        """Create a new collection in the database."""
        async with self._connection.connect() as conn:
            # ✅ Create the collection in PgVector
            _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
            )
            self._client = PgVector(
                embeddings=_embed_.embedding,
                embedding_length=self.dimension,
                collection_name=self.collection_name,
                connection=self._connection,
                use_jsonb=True,
                create_extension=False
            )
            print(
                f"✅ Collection `{self.collection_name}` created successfully."
            )

    def get_vector(
        self,
        table: Optional[str] = None,
        schema: Optional[str] = None,
        collection: Union[str, None] = None,
        embedding: Optional[Callable] = None,
        **kwargs
    ) -> PGVector:
        """
        This function retrieves a vector from the specified collection using the provided embedding.
        If no collection is specified, it uses the default collection name.
        If no embedding is provided, it creates a new embedding using the specified embedding model.

        Parameters:
        - collection (Union[str, None]): The name of the collection from which to retrieve the vector.
        - embedding (Optional[Callable]): The embedding function to use for vector retrieval.
        - kwargs: Additional keyword arguments to pass to the PGVector constructor.

        Returns:
        - PGVector: The retrieved vector from the specified collection.
        """
        if not table:
            table = self.table
        if not schema:
            schema = self.schema
        if not collection:
            collection = self.collection_name
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        return PgVector(
            connection=self._connection,
            table_name=table,
            schema=schema,
            id_column=self._id_column,
            collection_name=collection,
            embedding_length=self.dimension,
            embeddings=_embed_.embedding,
            logger=self.logger,
            async_mode=True,
            use_jsonb=True,
            create_extension=False,
            **kwargs
        )

    def memory_retriever(
        self,
        documents: Optional[List[Document]] = None,
        num_results: int  = 5
    ) -> VectorStoreRetrieverMemory:
        _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
        )
        vectordb = PgVector.from_documents(
            documents or [],
            embedding=_embed_.embedding,
            connection=self._connection,
            collection_name=self.collection_name,
            embedding_length=self.dimension,
            use_jsonb=True,
            async_mode=True,
            create_extension=False,
        )
        retriever = PgVector.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)

    async def from_documents(
        self,
        documents: List[Document],
        table: Optional[str] = None,
        schema: Optional[str] = 'public',
        collection: Union[str, None] = None,
        **kwargs
    ) -> None:
        """Save Documents as Vectors in VectorStore."""
        _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
        )
        if not collection:
            collection = self.collection_name
        vectordb = await PgVector.afrom_documents(
            documents,
            connection=self._connection,
            table_name=table,
            schema=schema,
            id_column=self._id_column,
            collection_name=collection,
            embedding=_embed_.embedding,
            embedding_length=self.dimension,
            use_jsonb=True,
            async_mode=True,
        )
        return vectordb

    async def add_documents(
        self,
        documents: List[Document],
        collection: Union[str, None] = None,
        **kwargs
    ) -> None:
        """Save Documents as Vectors in VectorStore."""
        if not collection:
            collection = self.collection_name
        vectordb = self.get_vector(collection=collection, **kwargs)
        # Asynchronously add documents to PGVector
        await vectordb.aadd_documents(documents)

    async def similarity_search(
        self,
        query: str,
        table: Optional[str] = None,
        schema: Optional[str] = None,
        collection: Union[str, None] = None,
        limit: int = 2,
        score_threshold: Optional[float] = None,
        filter: Optional[dict] = None,
        **kwargs
    ) -> List[Document]:
        """Search for similar documents in VectorStore."""
        if not table:
            table = self.table
        if not schema:
            schema = self.schema
        if collection is None:
            collection = self.collection_name
        async with self:
            vector_db = self.get_vector(table=table, schema=schema, collection=collection, **kwargs)
            return await vector_db.asimilarity_search(
                query,
                k=limit,
                score_threshold=score_threshold,
                filter=filter
            )

    async def create_embedding_table(
        self,
        table: str,
        columns: List[str],
        schema: str = 'public',
        embedding_column: str = 'embedding',
        document_column: str = 'document',
        metadata_column: str = 'metadata',
        id_column: str = 'id',
        dimension: int = 768,
        use_jsonb: bool = False,
        drop_columns: bool = False,
        **kwargs
    ):
        """
        Create an embedding column and vectorize Table information.
        """
        tablename = f'{schema}.{table}'
        cols = ', '.join(columns)
        _qry = f'SELECT {cols} FROM {tablename};'
        # Generate a sample embedding to determine its dimension
        sample_vector = self._embed_.embedding.embed_query("sample text")
        vector_dim = len(sample_vector)
        # Compare it with the expected dimension
        if vector_dim != dimension:
            raise ValueError(
                f"Expected embedding dimension {self.dimension}, but got {vector_dim}"
            )
        async with self._connection.begin() as conn:
            result = await conn.execute(
                sqlalchemy.text(_qry)
            )
            rows = result.fetchall()
            # Concatenate column names and values to form an input string:
            # 'store_name: BestBuy, location_code: 123456, ...'
            # data = [
            #     ', '.join([f"{col}: {row[col]}" for col in columns])
            #     for row in rows
            # ]
            # if drop columns, then first remove the existing columns:
            if drop_columns:
                for column in (document_column, embedding_column, metadata_column):
                    await conn.execute(
                        sqlalchemy.text(
                            f'ALTER TABLE {tablename} DROP COLUMN IF EXISTS {column};'
                        )
                    )
            # Create a new column for embeddings
            if use_jsonb:
                await conn.execute(
                    sqlalchemy.text(
                        f'ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS {embedding_column} JSONB;'  # pylint: disable=C0301
                    )
                )
            else:
                # Use Embedding pgvector type:
                await conn.execute(
                    sqlalchemy.text(
                        f'ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS {embedding_column} vector({dimension});'  # pylint: disable=C0301
                    )
                )
                # Create a Index for vector:
                # TODO: define index algorithm and options.
                await conn.execute(
                    sqlalchemy.text(
                        f"CREATE INDEX IF NOT EXISTS idx_{schema}_{table}_embeddings ON {tablename} USING hnsw ({embedding_column} vector_l2_ops);"  # pylint: disable=C0301
                    )
                )
                # And also, an index IVFLAT:
                await conn.execute(
                    sqlalchemy.text(
                        f"CREATE INDEX IF NOT EXISTS idx_{schema}_{table}_ivflat ON {tablename} USING ivfflat ({embedding_column} vector_cosine_ops);"  # pylint: disable=C0301
                    )
                )
            # Then, create the info column and id column (if required):
            # Text info Column (content)
            await conn.execute(
                sqlalchemy.text(
                    f'ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS {document_column} TEXT;'
                )
            )
            # ID Column (if required)
            await conn.execute(
                sqlalchemy.text(
                    f'ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS {id_column} varchar;'
                )
            )
            # Metadata Column (JSONB):
            await conn.execute(
                sqlalchemy.text(
                    f'ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS {metadata_column} jsonb;'
                )
            )
            # And ID Column:
            await conn.execute(
                sqlalchemy.text(
                    f'ALTER TABLE {tablename} ADD COLUMN IF NOT EXISTS {id_column} varchar;'
                )
            )
            for row in rows:
                _id = getattr(row, id_column)
                metadata = {col: getattr(row, col) for col in columns}
                data = " ".join([f"{col}: {metadata[col]}" for col in columns])
                # Get the vector information from data:
                vector = self._embed_.embedding.embed_query(data)
                vector_str = "[" + ",".join(str(v) for v in vector) + "]"
                await conn.execute(
                sqlalchemy.text(f"""
                    UPDATE {tablename}
                    SET {embedding_column} = :vector, {document_column} = :info, {metadata_column} = :metadata
                    WHERE {id_column} = :id
                """),
                {"vector": vector_str, "id": _id, "info": data, "metadata": json_encoder(metadata)}
            )
        print("✅ Updated Table embeddings.")
