"""Flow Primitives — Storage Sub-package.

Provides storage mixins and execution memory, migrated from
``parrot.bots.flow.storage`` into the shared core location.

Re-exports:
    ExecutionMemory — in-memory execution history with optional FAISS indexing.
    VectorStoreMixin — FAISS vector store mixin.
    PersistenceMixin — DocumentDB persistence mixin.
    SynthesisMixin — LLM-based result synthesis mixin.
"""
from .memory import ExecutionMemory
from .mixin import VectorStoreMixin
from .persistence import PersistenceMixin
from .synthesis import SynthesisMixin

__all__ = [
    "ExecutionMemory",
    "VectorStoreMixin",
    "PersistenceMixin",
    "SynthesisMixin",
]
