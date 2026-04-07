from .registry import EmbeddingRegistry  # noqa: E402
from .catalog import EMBEDDING_MODELS, get_embedding_models  # noqa: E402

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}


__all__ = [
    "supported_embeddings",
    "EmbeddingRegistry",
    "EMBEDDING_MODELS",
    "get_embedding_models",
]
