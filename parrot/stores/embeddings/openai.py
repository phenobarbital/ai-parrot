from langchain_openai import (  # pylint: disable=E0401, E0611
    OpenAIEmbeddings
)
from .abstract import AbstractEmbed
from ...conf import OPENAI_API_KEY, OPENAI_ORGANIZATION


class OpenAIEmbed(AbstractEmbed):
    """A wrapper class for OpenAI embeddings."""
    model_name: str = "text-embedding-3-large"

    def _create_embedding(
        self,
        model_name: str = None,
        api_key: str = None,
        organization: str = None,
        **kwargs
    ):
        # Embedding
        return OpenAIEmbeddings(
            model=model_name or self.model_name,
            dimensions=kwargs.get('dimensions', 512),
            api_key=api_key or OPENAI_API_KEY,
            organization=organization or OPENAI_ORGANIZATION,
            max_retries=kwargs.get('max_retries', 4),
        )
