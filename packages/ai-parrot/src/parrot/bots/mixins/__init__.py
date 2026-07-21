"""Bot mixins package for AI-Parrot.

Provides optional mix-in classes that add capabilities to bots:
- IntentRouterMixin: pre-RAG query routing with strategy cascade and HITL support.
- IdentityMixin: file-based identity injection + hot reload (FEAT-321).
"""
from .intent_router import IntentRouterMixin
from .identity import IdentityMixin

__all__ = ["IntentRouterMixin", "IdentityMixin"]
