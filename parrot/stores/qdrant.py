from collections.abc import Callable
from typing import Any, Union
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

    def __init__(self, embeddings: Union[str, Callable] = None, **kwargs):
        super().__init__(embeddings, **kwargs)
        self.host = kwargs.get("host", QDRANT_HOST)
        self.port = kwargs.get("port", QDRANT_PORT)
        qdrant_args = kwargs.get("qdrant_args", {})
        self.connection_type = kwargs.get("connection_type", QDRANT_CONN_TYPE)
        url = kwargs.get("url", QDRANT_URL)
        if url is not None:
            self.url = url
        else:
            self.url = f"{QDRANT_PROTOCOL}://{self.host}"
            if self.port:
                self.url += f":{self.port}"
        self.qdrant_args = {**qdrant_args, **kwargs}

    def connection(self) -> Callable:
        """Connects to the Qdrant database."""
        client = None
        if self.connection_type == "server":
            client = self._create_qdrant_client(
                self.host, self.port, self.url, QDRANT_USE_HTTPS, False, self.qdrant_args
            )
        elif self.connection_type == "cloud":
            if self.url is None:
                raise ValueError(
                    "A URL is required for 'cloud' connection"
                )
            client = self._create_qdrant_client(
                None, None, self.url, False, False, self.qdrant_args
            )
        else:
            raise ValueError(
                f"Invalid connection type: {self.connection_type}"
            )
        return client


    def get_vectorstore(self):
        if self._embed_ is None:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        else:
            _embed_ = self._embed_
        self.vector = Qdrant(
            client=self.client,
            collection_name=self.collection_name,
            embeddings=_embed_,
        )
        return self.vector

    def search(self, payload: dict, collection: str = None) -> dict:
        pass
