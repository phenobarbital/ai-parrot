from langchain_ollama import OllamaEmbeddings
from .base import BaseEmbed


class OllamaEmbed(BaseEmbed):
    """A wrapper class for Ollama embeddings."""
    model_name: str = "llama3"

    def __new__(cls, model_name: str = None, **kwargs):
        # Embedding Model:
        return OllamaEmbeddings(
            model_name=model_name or cls.model_name,
            **kwargs
        )
