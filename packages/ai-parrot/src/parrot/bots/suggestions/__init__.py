"""Follow-up suggestion chips: provider protocol and engine (FEAT-752)."""

from .engine import SuggestionEngine, renderer_available
from .protocol import LANES, SuggestionContext, SuggestionProvider

__all__ = ("LANES", "SuggestionContext", "SuggestionEngine", "SuggestionProvider", "renderer_available")
