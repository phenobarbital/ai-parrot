from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

from .registry import EmbeddingRegistry  # noqa: E402
from .catalog import (  # noqa: E402
    EMBEDDING_MODELS,
    USE_CASE_DESCRIPTIONS,
    get_embedding_models,
    get_model_recommendations,
    get_use_cases,
)
from .matryoshka import MatryoshkaConfig, validate_against_catalog  # noqa: E402
# EmbeddingModelEntry is intentionally NOT exported — it is a validation-only
# schema used at catalog import time. Consumers should use EMBEDDING_MODELS
# (plain dicts) for JSON-serialization compatibility with the consumer API.

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
    'multimodal': 'UFormEmbedding',
}


__all__ = [
    "supported_embeddings",
    "EmbeddingRegistry",
    "EMBEDDING_MODELS",
    "USE_CASE_DESCRIPTIONS",
    "get_embedding_models",
    "get_model_recommendations",
    "get_use_cases",
    "MatryoshkaConfig",
    "validate_against_catalog",
]
