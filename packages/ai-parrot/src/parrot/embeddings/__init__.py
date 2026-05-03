from .registry import EmbeddingRegistry  # noqa: E402
from .catalog import (  # noqa: E402
    EMBEDDING_MODELS,
    USE_CASE_DESCRIPTIONS,
    get_embedding_models,
    get_use_cases,
)
# EmbeddingModelEntry is intentionally NOT exported — it is a validation-only
# schema used at catalog import time. Consumers should use EMBEDDING_MODELS
# (plain dicts) for JSON-serialization compatibility with the consumer API.

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
