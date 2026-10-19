"""ai-parrot-semantic — governed semantic layer (sidemantic core + sqlglot governance)."""

from .errors import (
    SemanticAccessError,
    SemanticError,
    SemanticExecutionError,
    SemanticPolicyError,
    SemanticResultError,
    SemanticValidationError,
)
from .models import SemanticQuery, SemanticQueryResult
from .toolkit import SemanticLayerToolkit, StaticSubject
from .version import __version__

__all__ = [
    "__version__",
    "SemanticLayerToolkit",
    "StaticSubject",
    "SemanticQuery",
    "SemanticQueryResult",
    "SemanticError",
    "SemanticValidationError",
    "SemanticPolicyError",
    "SemanticAccessError",
    "SemanticExecutionError",
    "SemanticResultError",
]
