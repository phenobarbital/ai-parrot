from langchain_google_genai import (
    GoogleGenerativeAIEmbeddings
)
from .abstract import AbstractEmbed
from ...conf import GOOGLE_API_KEY

class GoogleEmbed(AbstractEmbed):
    """A wrapper class for VertexAI embeddings."""
    model_name: str = "models/embedding-001"

    def _create_embedding(self, model_name: str = None, api_key: str = None, **kwargs):
        # Embedding Model:
        api_key = api_key or GOOGLE_API_KEY
        return GoogleGenerativeAIEmbeddings(
            model=model_name or self.model_name,
            google_api_key=api_key,
            **kwargs
        )
