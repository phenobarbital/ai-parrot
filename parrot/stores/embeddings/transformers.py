from langchain_huggingface import HuggingFaceEmbeddings
from .base import BaseEmbed


class TransformersEmbed(BaseEmbed):
    """A wrapper class for Transformers embeddings."""
    model_name: str = "all-MiniLM-L6-v2"
    #  "sentence-transformers/all-mpnet-base-v2"

    def __new__(cls, model_name: str = None):
        # Embedding Model:
        device = cls._get_device(cls)
        model_args = {
            **cls.model_kwargs,
            'device': device,
        }
        return HuggingFaceEmbeddings(
            model_name=model_name or cls.model_name,
            model_kwargs=model_args,
            encode_kwargs=cls.encode_kwargs
        )
