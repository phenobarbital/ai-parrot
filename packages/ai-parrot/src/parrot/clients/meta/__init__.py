"""Meta Model API client package for AI-Parrot.

Exposes ``MetaModel`` (the model catalog) and ``MetaClient`` (the
``OpenAIBaseClient`` subclass for Meta's Muse Spark family). See
``sdd/specs/meta-llm-client.spec.md`` (FEAT-526).
"""

from .models import (
    MetaModel,
    CONTRIBUTOR_MODELS,
    SPARK_MODELS,
    IMAGE_MODELS,
    TRANSCRIBE_MODELS,
    CONTEXT_WINDOW,
)
from .client import MetaClient, config

__all__ = [
    "MetaModel",
    "CONTRIBUTOR_MODELS",
    "SPARK_MODELS",
    "IMAGE_MODELS",
    "TRANSCRIBE_MODELS",
    "CONTEXT_WINDOW",
    "MetaClient",
]
