from .registry import EmbeddingRegistry  # noqa: E402
from .catalog import (  # noqa: E402
    EMBEDDING_MODELS,
    USE_CASE_DESCRIPTIONS,
    get_embedding_models,
    get_use_cases,
)

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}


__all__ = [
    "supported_embeddings",
    "EmbeddingRegistry",
    "EMBEDDING_MODELS",
    "USE_CASE_DESCRIPTIONS",
    "get_embedding_models",
    "get_use_cases",
]
