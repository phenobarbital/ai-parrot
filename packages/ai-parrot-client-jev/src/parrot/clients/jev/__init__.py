"""TypeSafe AI System One (Jev) client for AI-Parrot."""

from .client import JevClient
from .exceptions import (
    JevAPIError,
    JevAuthenticationError,
    JevBadRequestError,
    JevConfigurationError,
    JevConnectionError,
    JevError,
    JevNotFoundError,
    JevRateLimitError,
    JevSchemaError,
    JevServerError,
)
from .models import (
    Choice,
    ChoiceAnswer,
    JevModel,
    JevUsage,
    ListModelsResponse,
    ModelMetadata,
    Noul,
    NoulAnswer,
    NoulCriteria,
    Score,
    ScoreAnswer,
    SystemOneResponse,
)
from .schema import answers_to_type, questions_from_type

__all__ = [
    "JevClient",
    "JevModel",
    "Choice",
    "Noul",
    "NoulCriteria",
    "Score",
    "ChoiceAnswer",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "JevUsage",
    "ModelMetadata",
    "ListModelsResponse",
    "questions_from_type",
    "answers_to_type",
    "JevError",
    "JevAPIError",
    "JevAuthenticationError",
    "JevBadRequestError",
    "JevConfigurationError",
    "JevConnectionError",
    "JevNotFoundError",
    "JevRateLimitError",
    "JevSchemaError",
    "JevServerError",
]
