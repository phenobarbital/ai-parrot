from typing import Any, List, Union
import numpy as np
from google import genai
from navconfig import config
# This file is part of Parrot, an open-source project.
from .base import EmbeddingModel

class GoogleEmbeddingModel(EmbeddingModel):
    """A wrapper class for Google Embedding models using the Gemini API.
    """
    model_name: str = "gemini-embedding-001"

    def __init__(self, **kwargs):
        self.api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        super().__init__(**kwargs)

    def _create_embedding(self, model_name: str = None, **kwargs) -> Any:
        """
        Creates and returns a Google Embedding model instance.

        Args:
            model_name: The name of the Google model to load.

        Returns:
            An instance of Google Embedding model.
        """
        self.model_name = model_name or self.model_name
        self.logger.info(
            f"Loading embedding model '{self.model_name}'"
        )
        self.client = genai.Client(api_key=self.api_key)
        return self.client

    async def encode(self, texts: List[str], **kwargs) -> List[List[float]]:
        result = self.client.models.embed_content(
            model=self.model_name,
            contents=texts
        )
        return result.embeddings

    def embed_query(
        self,
        text: str,
        as_nparray: bool = False
    ) -> Union[List[float], List[np.ndarray]]:
        result = self.client.models.embed_content(
            model=self.model_name,
            contents=[text]
        )
        if as_nparray:
            return [np.array(embedding) for embedding in result.embeddings]
        return result.embeddings
