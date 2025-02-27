from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from .base import BaseEmbed


class BgeEmbed(BaseEmbed):
    """A wrapper class for VertexAI embeddings."""
    model_name: str = "BAAI/bge-large-en-v1.5"

    def __new__(cls, model_name: str = None, **kwargs):
        # Embedding Model:
        device = cls._get_device(cls)
        model_args = {
            **cls.model_kwargs,
            'device': device,
        }
        return HuggingFaceBgeEmbeddings(
            model_name=model_name or cls.model_name,
            model_kwargs=model_args,
            encode_kwargs=cls.encode_kwargs
        )
