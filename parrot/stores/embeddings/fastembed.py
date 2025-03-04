from langchain_community.embeddings.fastembed import (
    FastEmbedEmbeddings
)
from .abstract import AbstractEmbed


class FastembedEmbed(AbstractEmbed):
    """A wrapper class for FastEmbed embeddings."""
    model_name: str = "BAAI/bge-large-en-v1.5"

    def _create_embedding(self, model_name: str = None, **kwargs):
        # Embedding Model:
        return FastEmbedEmbeddings(
            model_name=model_name,
            max_length=1024,
            threads=4
        )
