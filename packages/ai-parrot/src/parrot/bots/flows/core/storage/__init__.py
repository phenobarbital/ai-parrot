"""Flow Primitives — Storage Sub-package.

Provides storage mixins and execution memory, migrated from
``parrot.bots.flow.storage`` into the shared core location.

Re-exports:
    ExecutionMemory — in-memory execution history with optional FAISS indexing.
    VectorStoreMixin — FAISS vector store mixin.
    PersistenceMixin — DocumentDB persistence mixin.
    SynthesisMixin — LLM-based result synthesis mixin.
    synthesize_results — top-level async util for LLM result synthesis (FEAT-163).
    CrewExecutionDocument — deterministic, LLM-free consolidated execution
        record (FEAT-306).
"""
from .document import CrewExecutionDocument
from .memory import ExecutionMemory
from .mixin import VectorStoreMixin
from .persistence import PersistenceMixin
from .synthesis import SynthesisMixin, synthesize_results

__all__ = [
    "ExecutionMemory",
    "VectorStoreMixin",
    "PersistenceMixin",
    "SynthesisMixin",
    "synthesize_results",
    "CrewExecutionDocument",
]
