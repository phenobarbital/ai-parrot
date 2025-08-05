from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
import importlib
from collections.abc import Callable
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611 # noqa
from navconfig.logging import logging
from ..conf import (
    EMBEDDING_DEFAULT_MODEL
)
from ..exceptions import ConfigError  # pylint: disable=E0611
from ..embeddings import supported_embeddings


logging.getLogger(name='datasets').setLevel(logging.WARNING)

class AbstractStore(ABC):
    """AbstractStore class.

        Base class for all Database Vector Stores.
    Args:
        embeddings (str): Embedding name.

    Supported Vector Stores:
        - Qdrant
        - Milvus
        - Faiss
        - Chroma
        - PgVector
    """

    def __init__(
        self,
        embedding_model: Union[dict, str] = None,
        embedding: Union[dict, Callable] = None,
        **kwargs
    ):
        self.client: Callable = None
        self.vector: Callable = None
        self._embed_: Callable = None
        self._connected: bool = False
        if embedding_model is not None:
            if isinstance(embedding_model, str):
                self.embedding_model = {
                    'model_name': embedding_model,
                    'model_type': 'huggingface'
                }
            elif isinstance(embedding_model, dict):
                self.embedding_model = embedding_model
            else:
                raise ValueError(
                    "Embedding Model must be a string or a dictionary."
                )
        # Use or not connection to a vector database:
        self._use_database: bool = kwargs.get('use_database', True)
        # Database Information:
        self.collection_name: str = kwargs.get('collection_name', 'my_collection')
        self.dimension: int = kwargs.get("dimension", 384)
        self._metric_type: str = kwargs.get("metric_type", 'COSINE')
        self._index_type: str = kwargs.get("index_type", 'IVF_FLAT')
        self.database: str = kwargs.get('database', '')
        self.index_name = kwargs.get("index_name", "my_index")
        if embedding is not None:
            if isinstance(embedding, str):
                self.embedding_model = {
                    'model_name': embedding,
                    'model_type': 'huggingface'
                }
            elif isinstance(embedding, dict):
                self.embedding_model = embedding
            else:
                # is a callable:
                self.embedding_model = {
                    'model_name': EMBEDDING_DEFAULT_MODEL,
                    'model_type': 'huggingface'
                }
                self._embed_ = embedding
        self.logger = logging.getLogger(
            f"Store.{__name__}"
        )
        # Client Connection (if required):
        self._connection = None
        # Create the Embedding Model:
        self._embed_ = self.create_embedding(
            embedding_model=self.embedding_model
        )
        # Track context depth
        self._context_depth = 0
        # JSON parser (based on orjson):
        self._json = JSONContent()

    @property
    def connected(self) -> bool:
        return self._connected

    def is_connected(self):
        return self._connected

    @abstractmethod
    async def connection(self) -> tuple:
        pass

    def get_connection(self) -> Any:
        return self._connection

    def engine(self):
        return self._connection

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    # Async Context Manager
    async def __aenter__(self):
        if self._use_database:
            if not self._connection:
                await self.connection()
        self._context_depth += 1
        return self

    async def _free_resources(self):
        if self._embed_:
            self._embed_.free()
        self._embed_ = None

    async def __aexit__(self, exc_type, exc_value, traceback):
        # closing Embedding
        if self._embed_:
            await self._free_resources()
        try:
            # Only disconnect if we're exiting the outermost context
            if self._context_depth <= 0:
                await self.disconnect()
                self._context_depth = 0
        except RuntimeError:
            pass

    @abstractmethod
    def get_vector(self, metric_type: str = None, **kwargs):
        pass

    def get_vectorstore(self):
        return self.get_vector()

    @abstractmethod
    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        similarity_threshold: float = 0.0,
        search_strategy: str = "auto",
        metadata_filters: Union[dict, None] = None,
        **kwargs
    ) -> list:  # noqa
        pass

    @abstractmethod
    async def from_documents(
        self,
        documents: List[Any],
        collection: Union[str, None] = None,
        **kwargs
    ) -> Callable:
        """
        Create Vector Store from Documents.

        Args:
            documents (List[Any]): List of Documents.
            collection (str): Collection Name.
            kwargs: Additional Arguments.

        Returns:
            Callable VectorStore.
        """

    @abstractmethod
    async def create_collection(self, collection: str) -> None:
        """
        Create Collection in Vector Store.

        Args:
            collection (str): Collection Name.

        Returns:
            None.
        """
        pass

    @abstractmethod
    async def add_documents(
        self,
        documents: List[Any],
        collection: Union[str, None] = None,
        **kwargs
    ) -> None:
        """
        Add Documents to Vector Store.

        Args:
            documents (List[Any]): List of Documents.
            collection (str): Collection Name.
            kwargs: Additional Arguments.

        Returns:
            None.
        """

    def create_embedding(
        self,

        embedding_model: dict,
        **kwargs
    ):
        """
        Create Embedding Model.

        Args:
            embedding_model (dict): Embedding Model Configuration.
            kwargs: Additional Arguments.

        Returns:
            Callable: Embedding Model.

        """
        model_type = embedding_model.get('model_type', 'huggingface')
        model_name = embedding_model.get('model', EMBEDDING_DEFAULT_MODEL)
        if model_type not in supported_embeddings:
            raise ConfigError(
                f"Embedding Model Type: {model_type} not supported."
            )
        embed_cls = supported_embeddings[model_type]
        cls_path = f"..embeddings.{model_type}"  # Relative module path
        try:
            embed_module = importlib.import_module(
                cls_path,
                package=__package__
            )
            embed_obj = getattr(embed_module, embed_cls)
            return embed_obj(
                model_name=model_name,
                **kwargs
            )
        except ImportError as e:
            raise ConfigError(
                f"Error Importing Embedding Model: {model_type}"
            ) from e

    def get_default_embedding(self):
        embed_model = {
            'model_name': EMBEDDING_DEFAULT_MODEL,
            'model_type': 'huggingface'
        }
        return self.create_embedding(
            embedding_model=embed_model
        )

    def generate_embedding(self, documents: List[Any]) -> List[Any]:
        if not self._embed_:
            self._embed_ = self.get_default_embedding()

        # Using the Embed Model to Generate Embeddings:
        embeddings = self._embed_.embed_documents(documents)
        return embeddings

    @abstractmethod
    async def prepare_embedding_table(
        self,
        tablename: str,
        conn: Any = None,
        embedding_column: str = 'embedding',
        document_column: str = 'document',
        metadata_column: str = 'cmetadata',
        dimension: int = None,
        id_column: str = 'id',
        use_jsonb: bool = True,
        drop_columns: bool = False,
        create_all_indexes: bool = True,
        **kwargs
    ):
        """
        Prepare a Table as an embedding table with advanced features.
        This method prepares a table with the following columns:
        - id: unique identifier (String)
        - embedding: the vector column (Vector(dimension) or JSONB)
        - document: text column containing the document
        - collection_id: UUID column for collection identification.
        - metadata: JSONB column for metadata
        - Additional columns based on the provided `columns` list
        - Enhanced indexing strategies for efficient querying
        - Support for multiple distance strategies (COSINE, L2, IP, etc.)
        Args:
        - tablename (str): Name of the table to create.
        - embedding_column (str): Name of the column for storing embeddings.
        - document_column (str): Name of the column for storing document text.
        - metadata_column (str): Name of the column for storing metadata.
        - dimension (int): Dimension of the embedding vector.
        - id_column (str): Name of the column for storing unique identifiers.
        - use_jsonb (bool): Whether to use JSONB for metadata storage.
        - drop_columns (bool): Whether to drop existing columns.
        - create_all_indexes (bool): Whether to create all distance strategies.
    """
        pass


    @abstractmethod
    async def delete_documents(
        self,
        documents: Optional[Any] = None,
        pk: str = 'source_type',
        values: Optional[Union[str, List[str]]] = None,
        table: Optional[str] = None,
        schema: Optional[str] = None,
        collection: Optional[str] = None,
        **kwargs
    ) -> int:
        """
        Delete Documents from the Vector Store.
        Args:
            documents (Optional[Any]): Documents to delete.
            pk (str): Primary key field.
            values (Optional[Union[str, List[str]]]): Values to match for deletion.
            table (Optional[str]): Table name.
            schema (Optional[str]): Schema name.
            collection (Optional[str]): Collection name.
            kwargs: Additional arguments.
        Returns:
            int: Number of deleted documents.
        """
        pass


    @abstractmethod
    async def delete_documents_by_filter(
        self,
        search_filter: Dict[str, Union[str, List[str]]],
        table: Optional[str] = None,
        schema: Optional[str] = None,
        collection: Optional[str] = None,
        **kwargs
    ) -> int:
        """
        Delete Documents by filter.
        Args:
            search_filter (Dict[str, Union[str, List[str]]]): Filter criteria.
            table (Optional[str]): Table name.
            schema (Optional[str]): Schema name.
            collection (Optional[str]): Collection name.
            kwargs: Additional arguments.
        Returns:
            int: Number of deleted documents.
        """
        pass
