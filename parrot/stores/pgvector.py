from typing import Union, Optional
from collections.abc import Callable
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from langchain_postgres.vectorstores import PGVector
from .abstract import AbstractStore


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
        self.dsn = kwargs.get('dsn', self.database)

    async def connection(self, alias: str = None):
        """Connection to DuckDB.

        Args:
            alias (str): Database alias.

        Returns:
            Callable: DuckDB connection.

        """
        self._connection = create_async_engine(self.dsn, future=True, echo=False)
        self._connected = True
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

    def get_vector(
        self,
        collection: Union[str, None] = None,
        embedding: Optional[Callable] = None,
        metadata_field: str = 'id',
        text_field: str = 'text',
        vector_key: str = 'vector',
    ) -> PGVector:

        if not collection:
            collection = self.collection_name
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        return PGVector(
            connection=self._connection,
            collection_name=collection,
            embedding_length=self.dimension,
            embeddings=_embed_,
            logger=self.logger,
            use_jsonb=True,
            create_extension=True,
            async_mode=True
        )
