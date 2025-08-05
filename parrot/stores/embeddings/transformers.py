from langchain_huggingface import HuggingFaceEmbeddings
from .base import BaseEmbed


class TransformersEmbed(BaseEmbed):
    """A wrapper class for Transformers embeddings."""
    model_name: str = "all-MiniLM-L6-v2"
    #  "sentence-transformers/all-mpnet-base-v2"

    def _create_embedding(self, model_name: str = None, **kwargs):
        # Embedding Model:
        device = self._get_device()
        model_args = {
            **self.model_kwargs,
            'device': device,
        }
        return HuggingFaceEmbeddings(
            model_name=model_name or self.model_name,
            model_kwargs=model_args,
            encode_kwargs=self.encode_kwargs
        )
