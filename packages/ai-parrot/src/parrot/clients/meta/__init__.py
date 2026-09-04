"""Meta Model API client package for AI-Parrot.

Exposes ``MetaModel`` (the model catalog) and, once implemented,
``MetaClient`` (the ``OpenAIBaseClient`` subclass for Meta's Muse Spark
family). See ``sdd/specs/meta-llm-client.spec.md`` (FEAT-526).
"""
from .models import (
    MetaModel,
    CONTRIBUTOR_MODELS,
    SPARK_MODELS,
    IMAGE_MODELS,
    TRANSCRIBE_MODELS,
    CONTEXT_WINDOW,
)

# NOTE: `MetaClient` is re-exported here by TASK-2834 once
# `parrot/clients/meta/client.py` exists. Do not import a module that
# does not exist yet.

__all__ = [
    "MetaModel",
    "CONTRIBUTOR_MODELS",
    "SPARK_MODELS",
    "IMAGE_MODELS",
    "TRANSCRIBE_MODELS",
    "CONTEXT_WINDOW",
]
