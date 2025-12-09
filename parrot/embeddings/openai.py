from typing import Any, List, Union, Optional
import asyncio
import numpy as np
from navconfig import config
from openai import AsyncOpenAI
from .base import EmbeddingModel

class OpenAIEmbeddingModel(EmbeddingModel):
    """A wrapper class for OpenAI Embedding models.
    """
    model_name: str = "text-embedding-3-large"

    def __init__(self, model_name: str = None, dimensions: int = None, **kwargs):
        self.api_key = kwargs.pop('api_key', config.get('OPENAI_API_KEY'))
        if model_name:
            self.model_name = model_name
        self.dimensions = dimensions
        self._dimension = dimensions
        super().__init__(model_name=self.model_name, **kwargs)

    def _create_embedding(self, model_name: str = None, **kwargs) -> Any:
        """
        Creates and returns an OpenAI client instance.

        Args:
            model_name: The name of the OpenAI model to load.

        Returns:
            An instance of AsyncOpenAI client.
        """
        if model_name:
            self.model_name = model_name
        
        self.logger.info(
            f"Loading embedding model '{self.model_name}'"
        )
        # Using AsyncOpenAI as consistent with other parts of the system
        return AsyncOpenAI(api_key=self.api_key)

    async def encode(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings for a list of texts using AsyncOpenAI.

        This mirrors the official OpenAI embeddings guide, allowing callers to
        override the model or dimensions per request while keeping asynchronous
        semantics.
        """
        model = kwargs.pop("model", self.model_name)
        dimensions = kwargs.pop("dimensions", self.dimensions)
        call_kwargs = {
            "model": model,
            "input": texts,
            "encoding_format": "float",
            **kwargs,
        }
        if dimensions:
            call_kwargs["dimensions"] = dimensions

        result = await self.model.embeddings.create(**call_kwargs)
        embeddings = [data.embedding for data in result.data]
        if embeddings and not self._dimension:
            # Keep a record of the dimension reported by the service when not set
            self._dimension = len(embeddings[0])
        return embeddings

    async def embed_query(
        self,
        text: str,
        as_nparray: bool = False
    ) -> Union[List[float], List[np.ndarray]]:
        """
        Generates an embedding for a single query string asynchronously.
        """
        embeddings = await self.encode([text])
        embedding = embeddings[0]
        
        if as_nparray:
            return [np.array(embedding)]
        return embedding

    async def embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]:
        """
        Generates embeddings for a list of documents asynchronously.
        """
        return await self.encode(texts)
