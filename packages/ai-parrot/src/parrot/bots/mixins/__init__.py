"""Bot mixins package for AI-Parrot.

Provides optional mix-in classes that add capabilities to bots:
- IntentRouterMixin: pre-RAG query routing with strategy cascade and HITL support.
- IdentityMixin: file-based identity injection + hot reload (FEAT-321).
- ModelSwitchingMixin: dual-LLM switching — cross-provider fallback on error
  or contrastive dual-model answers with per-model attribution.
"""
from .intent_router import IntentRouterMixin
from .identity import IdentityMixin
from .model_switching import ModelSwitchingMixin, ModelSwitchMode
from .infographic_authoring import InfographicAuthoringMixin

__all__ = [
    "IntentRouterMixin",
    "IdentityMixin",
    "ModelSwitchingMixin",
    "ModelSwitchMode",
    "InfographicAuthoringMixin",
]
