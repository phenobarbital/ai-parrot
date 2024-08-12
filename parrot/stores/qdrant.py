from typing import Any
from qdrant_client import QdrantClient  # pylint: disable=import-error
from langchain_community.vectorstores import (  # pylint: disable=import-error, E0611
    Qdrant
)
from .abstract import AbstractStore
from ..conf import (
    QDRANT_PROTOCOL,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_USE_HTTPS,
    QDRANT_CONN_TYPE,
    QDRANT_URL
)


class QdrantStore(AbstractStore):
    """QdrantStore class.


    Args:
        host (str): Qdrant host.
        port (int): Qdrant port.
        index_name (str): Qdrant index name.
    """

    def _create_qdrant_client(self, host, port, url, https, verify, qdrant_args):
        """
        Creates a Qdrant client based on the provided configuration.

        Args:
            host: Host of the Qdrant server (if using "server" connection).
            port: Port of the Qdrant server (if using "server" connection).
            url: URL of the Qdrant cloud service (if using "cloud" connection).
            https: Whether to use HTTPS for the connection.
            verify: Whether to verify the SSL certificate.
            qdrant_args: Additional arguments for the Qdrant client.

        Returns:
            A QdrantClient object.
        """
        if url is not None:
            return QdrantClient(
            url=url,
            port=None,
            verify=verify,
            **qdrant_args
            )
        else:
            return QdrantClient(
            host,
            port=port,
            https=https,
            verify=verify,
            **qdrant_args
            )

    def __init__(self, embeddings = None, **kwargs):
        super().__init__(embeddings, **kwargs)
        self.host = kwargs.get("host", QDRANT_HOST)
        self.port = kwargs.get("port", QDRANT_PORT)
        qdrant_args = kwargs.get("qdrant_args", {})
        connection_type = kwargs.get("connection_type", QDRANT_CONN_TYPE)
        url = kwargs.get("url", QDRANT_URL)
        if connection_type == "server":
            self.client = self._create_qdrant_client(
                self.host, self.port, url, QDRANT_USE_HTTPS, False, qdrant_args
            )
        elif connection_type == "cloud":
            if url is None:
                raise ValueError(
                    "A URL is required for 'cloud' connection"
                )
            self.client = self._create_qdrant_client(
                None, None, url, False, False, qdrant_args
            )
        else:
            raise ValueError(
                f"Invalid connection type: {connection_type}"
            )
        if url is not None:
            self.url = url
        else:
            self.url = f"{QDRANT_PROTOCOL}://{self.host}"
            if self.port:
                self.url += f":{self.port}"

    def get_vectorstore(self):
        if self._embed_ is None:
            _embed_ = self.create_embedding(
                model_name=self.embedding_name
            )
        else:
            _embed_ = self._embed_
        self.vector = Qdrant(
            client=self.client,
            collection_name=self.collection,
            embeddings=_embed_,
        )
        return self.vector

    async def load_documents(
        self,
        documents: list,
        collection: str = None
    ):
        if collection is None:
            collection = self.collection

        docstore = Qdrant.from_documents(
            documents,
            self._embed_,
            url=self.url,
            # location=":memory:",  # Local mode with in-memory storage only
            collection_name=collection,
            force_recreate=False,
        )
        return docstore

    def upsert(self, payload: dict, collection: str = None) -> None:
        if collection is None:
            collection = self.collection
        self.client.upsert(
            collection_name=collection,
            points=self._embed_,
            payload=payload
        )

    def search(self, payload: dict, collection: str = None) -> dict:
        pass

    async def delete_collection(self, collection: str = None) -> dict:
        self.client.delete_collection(
            collection_name=collection
        )

    async def create_collection(
        self,
        collection_name: str,
        document: Any,
        dimension: int = 768,
        **kwargs
    ) -> dict:
        # Here using drop_old=True to force recreate based on the first document
        docstore = Qdrant.from_documents(
            [document],
            self._embed_,
            url=self.url,
            # location=":memory:",  # Local mode with in-memory storage only
            collection_name=collection_name,
            force_recreate=True,
        )
        return docstore
