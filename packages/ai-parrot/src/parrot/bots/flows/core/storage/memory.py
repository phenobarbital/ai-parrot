"""Flow Primitives — ExecutionMemory.

Copied from ``parrot.bots.flow.storage.memory`` into the shared core
storage location.  Relative imports updated for the new package depth.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .....models.crew import AgentResult
from .mixin import VectorStoreMixin


@dataclass
class ExecutionMemory(VectorStoreMixin):
    """In-memory storage for execution history.

    Optionally indexes results into a FAISS vector store (via
    ``VectorStoreMixin``) when an ``embedding_model`` is provided.

    Args:
        original_query: The initial prompt/task string for this execution.
        embedding_model: Optional embedding model for FAISS indexing.
        dimension: Embedding dimension (default 384).
        index_type: FAISS index type (``"Flat"``, ``"FlatIP"``, or ``"HNSW"``).
    """

    original_query: Optional[str] = None
    results: Dict[str, AgentResult] = field(default_factory=dict)
    execution_graph: Dict[str, List[str]] = field(default_factory=dict)
    execution_order: List[str] = field(default_factory=list)

    def __init__(
        self,
        original_query: str = "",
        embedding_model=None,
        dimension: int = 384,
        index_type: str = "Flat",
    ):
        self.original_query = original_query
        self.results = {}
        self.execution_graph = {}
        self.execution_order = []
        VectorStoreMixin.__init__(
            self,
            embedding_model=embedding_model,
            dimension=dimension,
            index_type=index_type,
        )

    def add_result(self, result: AgentResult, vectorize: bool = True) -> None:
        """Add a result and update execution graph.

        Args:
            result: The ``AgentResult`` to store.
            vectorize: If ``True`` and an embedding model is configured,
                schedule async FAISS indexing.
        """
        self.results[result.agent_id] = result
        if result.parent_execution_id:
            if result.parent_execution_id not in self.execution_graph:
                self.execution_graph[result.parent_execution_id] = []
            self.execution_graph[result.parent_execution_id].append(result.execution_id)

        if vectorize and self.embedding_model:
            asyncio.create_task(self._vectorize_result_async(result))

    def get_results_by_agent(self, agent_id: str) -> Optional[AgentResult]:
        """Retrieve result from a specific agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            ``AgentResult`` or ``None`` if not found.
        """
        return self.results.get(agent_id)

    def get_reexecuted_results(self) -> List[AgentResult]:
        """Return only results from re-executions triggered by ``ask()``.

        Returns:
            List of ``AgentResult`` instances with a non-None
            ``parent_execution_id``.
        """
        return [r for r in self.results.values() if r.parent_execution_id is not None]

    def get_context_for_agent(self, agent_id: str) -> Any:
        """Return the context available to an agent at execution time.

        Args:
            agent_id: Agent identifier.

        Returns:
            Initial query for the first agent; previous agent's result otherwise.
        """
        idx = self.execution_order.index(agent_id)
        if idx == 0:
            return self.original_query
        prev_agent_id = self.execution_order[idx - 1]
        return self.results[prev_agent_id].result

    def clear(self, keep_query: bool = False) -> None:
        """Clear execution memory.

        Args:
            keep_query: If ``True``, preserves ``original_query``.
        """
        self.results.clear()
        self.execution_graph.clear()
        self.execution_order.clear()
        self._clear_vectors()

        if not keep_query:
            self.original_query = ""

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the current memory state.

        Returns:
            Dictionary with all memory state information.
        """
        return {
            "original_query": self.original_query,
            "results": {
                agent_id: {
                    "result": str(result.result),
                    "task": result.task,
                    "metadata": result.metadata,
                    "timestamp": result.timestamp.isoformat(),
                    "parent_execution_id": result.parent_execution_id,
                    "execution_time": result.execution_time,
                }
                for agent_id, result in self.results.items()
            },
            "execution_order": self.execution_order.copy(),
            "execution_graph": {k: v.copy() for k, v in self.execution_graph.items()},
            "total_executions": len(self.results),
            "reexecutions": len(self.get_reexecuted_results()),
        }
