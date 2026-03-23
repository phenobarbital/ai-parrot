# from .huggingface import SentenceTransformerModel
# from .google import GoogleEmbeddingModel
# from .openai import OpenAIEmbeddingModel

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}

from .registry import EmbeddingRegistry  # noqa: E402

__all__ = ["supported_embeddings", "EmbeddingRegistry"]
