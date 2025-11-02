from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import asyncio
from ....models.crew import AgentResult
from .mixin import VectorStoreMixin

@dataclass
class ExecutionMemory(VectorStoreMixin):
    """In-memory storage for execution history"""
    original_query: Optional[str] = None
    results: Dict[str, AgentResult] = field(default_factory=dict)
    execution_graph: Dict[str, List[str]] = field(default_factory=dict)
    execution_order: List[str] = field(default_factory=list)

    def __init__(
        self, original_query: str = "",
        embedding_model=None,
        dimension: int = 384,
        index_type: str = "Flat"  # "Flat", "FlatIP", o "HNSW"
    ):
        self.original_query = original_query
        self.results = {}
        self.execution_graph = {}
        self.execution_order = []
        # Initialize mixin
        VectorStoreMixin.__init__(
            self,
            embedding_model=embedding_model,
            dimension=dimension,
            index_type=index_type
        )

    def add_result(self, result: AgentResult, vectorize: bool = True):
        """Add a result and update execution graph"""
        self.results[result.agent_id] = result
        if result.parent_execution_id:
            if result.parent_execution_id not in self.execution_graph:
                self.execution_graph[result.parent_execution_id] = []
            self.execution_graph[result.parent_execution_id].append(result.execution_id)

        # Async vectorization if enabled
        if vectorize and self.embedding_model:
            asyncio.create_task(
                self._vectorize_result_async(result)
            )

    def get_results_by_agent(self, agent_id: str) -> AgentResult:
        """Retrieve result from a specific agent"""
        return self.results.get(agent_id)

    def get_reexecuted_results(self) -> List[AgentResult]:
        """Get only results from re-executions triggered by ask()"""
        return [r for r in self.results.values() if r.parent_execution_id is not None]

    def get_context_for_agent(self, agent_id: str) -> Any:
        idx = self.execution_order.index(agent_id)
        if idx == 0:
            return self.original_query
        prev_agent_id = self.execution_order[idx - 1]
        return self.results[prev_agent_id].result

    def clear(self, keep_query: bool = False):
        """
        Clear execution memory.

        Args:
            keep_query: If True, preserves the original_query. Useful for re-running
            the same query with fresh execution.
        """
        self.results.clear()
        self.execution_graph.clear()
        self.execution_order.clear()
        self._clear_vectors()

        if not keep_query:
            self.original_query = ""

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get a snapshot of current memory state for inspection.

        Returns:
            Dictionary with all memory state information
        """
        return {
            "original_query": self.original_query,
            "results": {
                agent_id: {
                    "content": result.content,
                    "metadata": result.metadata,
                    "timestamp": result.timestamp.isoformat(),
                    "parent_execution_id": result.parent_execution_id
                }
                for agent_id, result in self.results.items()
            },
            "execution_order": self.execution_order.copy(),
            "execution_graph": {k: v.copy() for k, v in self.execution_graph.items()},
            "total_executions": len(self.results),
            "reexecutions": len(self.get_reexecuted_results())
        }
