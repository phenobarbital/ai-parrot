from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from .base import BaseEmbed


class BgeEmbed(BaseEmbed):
    """A wrapper class for VertexAI embeddings."""
    model_name: str = "BAAI/bge-large-en-v1.5"

    def _create_embedding(self, model_name: str = None, **kwargs):
        # Embedding Model:
        device = self._get_device()
        model_args = {
            **self.model_kwargs,
            'device': device,
        }
        return HuggingFaceBgeEmbeddings(
            model_name=model_name or self.model_name,
            model_kwargs=model_args,
            encode_kwargs=self.encode_kwargs
        )
