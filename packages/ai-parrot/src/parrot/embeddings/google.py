from typing import Any, List, Union
import numpy as np
from navconfig import config
# This file is part of Parrot, an open-source project.
from .base import EmbeddingModel

class GoogleEmbeddingModel(EmbeddingModel):
    """A wrapper class for Google Embedding models using the Gemini API.
    """
    model_name: str = "gemini-embedding-001"

    def __init__(self, model_name: str = None, output_dimensionality: int = None, **kwargs):
        self.api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        if model_name:
            self.model_name = model_name
        self.output_dimensionality = output_dimensionality
        super().__init__(**kwargs)

    def _create_embedding(self, model_name: str = None, **kwargs) -> Any:
        """
        Creates and returns a Google Embedding model instance.

        Args:
            model_name: The name of the Google model to load.

        Returns:
            An instance of Google Embedding model.
        """
        from google import genai
        if model_name:
            self.model_name = model_name
        self.logger.info(
            f"Loading embedding model '{self.model_name}'"
        )
        self.client = genai.Client(api_key=self.api_key)
        return self.client

    def _normalize_embeddings(self, embeddings: List[Any]) -> List[List[float]]:
        if not self.output_dimensionality or self.output_dimensionality == 3072:
            return [e.values for e in embeddings]
        
        # Normalize embeddings for lower dimensions
        normalized = []
        for embedding in embeddings:
            if hasattr(embedding, 'values'):
                val = np.array(embedding.values)
            else:
                val = np.array(embedding)
            norm = np.linalg.norm(val)
            if norm > 0:
                val = val / norm
            normalized.append(val.tolist())
        return normalized

    async def encode(self, texts: List[str], **kwargs) -> List[List[float]]:
        from google.genai import types
        
        call_kwargs = {
            "model": self.model_name,
            "contents": texts
        }
        if self.output_dimensionality:
            call_kwargs["config"] = types.EmbedContentConfig(
                output_dimensionality=self.output_dimensionality
            )
            
        if hasattr(self.client, 'aio'):
            result = await self.client.aio.models.embed_content(**call_kwargs)
        else:
            result = self.client.models.embed_content(**call_kwargs)
            
        if self.output_dimensionality:
            return self._normalize_embeddings(result.embeddings)
        return [e.values for e in result.embeddings]

    async def embed_query(
        self,
        text: str,
        as_nparray: bool = False
    ) -> Union[List[float], List[np.ndarray]]:
        embeddings = await self.encode([text])
        embedding = embeddings[0]

        if as_nparray:
            return [np.array(embedding)]
        return embedding

    async def embed_documents(
        self,
        texts: List[str],
        batch_size: Optional[int] = None
    ) -> List[List[float]]:
        return await self.encode(texts)
