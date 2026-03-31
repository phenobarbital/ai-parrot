"""Bot mixins package for AI-Parrot.

Provides optional mix-in classes that add capabilities to bots:
- IntentRouterMixin: pre-RAG query routing with strategy cascade and HITL support.
"""
from .intent_router import IntentRouterMixin

__all__ = ["IntentRouterMixin"]
