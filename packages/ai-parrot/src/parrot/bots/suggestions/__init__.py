"""Follow-up suggestion chips: provider protocol, engine and built-in providers (FEAT-752)."""

from .engine import SuggestionEngine, renderer_available
from .llm import LLMSuggestionProvider
from .protocol import LANES, SuggestionContext, SuggestionProvider
from .providers import (
    ExplainSuggestionProvider,
    PresentationSuggestionProvider,
    SkillSuggestionProvider,
    has_tabular_data,
)

__all__ = (
    "LANES",
    "ExplainSuggestionProvider",
    "LLMSuggestionProvider",
    "PresentationSuggestionProvider",
    "SkillSuggestionProvider",
    "SuggestionContext",
    "SuggestionEngine",
    "SuggestionProvider",
    "has_tabular_data",
    "renderer_available",
)
