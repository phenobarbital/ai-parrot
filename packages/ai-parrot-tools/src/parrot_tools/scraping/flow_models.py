"""ScrapingFlow DAG models — FlowNode, ScrapingFlow, FlowResult.

A :class:`ScrapingFlow` is a directed acyclic graph of :class:`FlowNode`s
where edges are data dependencies declared via each node's ``inputs`` map
(``{param: "node_id.field"}``) and each node carries a ``session`` label for
BrowserContext affinity (FEAT-222, Module 2).

The model validates the graph on construction (no duplicate ids, no dangling
references, no cycles) and exposes :meth:`ScrapingFlow.topological_order` for
the executor.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class FlowNode(BaseModel):
    """A single stage in a :class:`ScrapingFlow` DAG.

    Attributes:
        id: Unique node identifier within the flow.
        plan_ref: TemplatePlan name or plan fingerprint to execute.
        inputs: Map of ``param -> "node_id.field"`` data-dependency edges.
        session: Session label; nodes sharing a label share a BrowserContext.
        on_error: Failure policy — ``abort``, ``skip``, or ``retry``.
        max_retries: Retry budget used only when ``on_error == "retry"``.
    """

    id: str
    plan_ref: str
    inputs: Dict[str, str] = Field(default_factory=dict)
    session: str = "default"
    on_error: Literal["abort", "skip", "retry"] = "abort"
    max_retries: int = Field(default=3, ge=1)


class ScrapingFlow(BaseModel):
    """DAG of :class:`FlowNode`s with data-dependency edges and session affinity.

    Attributes:
        name: Flow name.
        description: Human-readable description.
        nodes: The flow's nodes (declaration order is preserved as a stable
            tiebreaker for topological ordering).
        global_params: Parameters available to every node at execution time.
    """

    name: str
    description: str = ""
    nodes: List[FlowNode]
    global_params: Dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def _source_node(ref: str) -> str:
        """Return the source node id of an input ref (``"node.field" -> "node"``)."""
        return ref.split(".", 1)[0]

    def _compute_topological_order(self) -> List[FlowNode]:
        """Validate the graph and return nodes in dependency order.

        Uses Kahn's algorithm. Declaration order is preserved as a stable
        tiebreaker so the result is deterministic.

        Raises:
            ValueError: On duplicate ids, dangling references, or cycles.
        """
        # Unique-id check.
        node_ids = [n.id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            seen: set[str] = set()
            dupes = {nid for nid in node_ids if nid in seen or seen.add(nid)}
            raise ValueError(f"Duplicate FlowNode id(s): {sorted(dupes)}")

        id_to_node = {n.id: n for n in self.nodes}

        # Build adjacency (source -> dependents) and in-degree, validating refs.
        adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}
        in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}

        for node in self.nodes:
            # Deduplicate source dependencies per node (a node may consume
            # several fields from the same upstream node).
            sources: List[str] = []
            for ref in node.inputs.values():
                source_id = self._source_node(ref)
                if source_id not in id_to_node:
                    raise ValueError(
                        f"FlowNode '{node.id}' input references non-existent "
                        f"node '{source_id}' (ref: '{ref}')"
                    )
                if source_id == node.id:
                    raise ValueError(
                        f"FlowNode '{node.id}' cannot depend on itself (cycle)"
                    )
                if source_id not in sources:
                    sources.append(source_id)

            for source_id in sources:
                adjacency[source_id].append(node.id)
                in_degree[node.id] += 1

        # Kahn's algorithm with declaration-order-stable queue.
        queue: List[str] = [nid for nid in node_ids if in_degree[nid] == 0]
        ordered_ids: List[str] = []
        head = 0
        while head < len(queue):
            current = queue[head]
            head += 1
            ordered_ids.append(current)
            for dependent in adjacency[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(ordered_ids) != len(node_ids):
            remaining = sorted(set(node_ids) - set(ordered_ids))
            raise ValueError(
                f"ScrapingFlow '{self.name}' contains a cycle involving "
                f"nodes: {remaining}"
            )

        return [id_to_node[nid] for nid in ordered_ids]

    @model_validator(mode="after")
    def validate_dag(self) -> "ScrapingFlow":
        """Validate the DAG: unique ids, no dangling refs, no cycles."""
        self._compute_topological_order()
        return self

    def topological_order(self) -> List[FlowNode]:
        """Return the flow's nodes in dependency (execution) order.

        Dependencies always precede their dependents. Declaration order is
        the stable tiebreaker among independent nodes.
        """
        return self._compute_topological_order()


class FlowResult(BaseModel):
    """Aggregated result of a :class:`ScrapingFlow` execution.

    Attributes:
        flow_name: Name of the executed flow.
        node_results: Map of ``node_id -> result`` (typically a
            ``ScrapingResult`` dump).
        success: Whether the flow completed successfully.
        error_message: Failure detail when ``success`` is ``False``.
        elapsed_seconds: Total wall-clock execution time.
        nodes_completed: Number of nodes that completed.
        nodes_total: Total number of nodes in the flow.
        checkpoint_path: Path to the persisted checkpoint, if any.
        resumed_from: Node id the run resumed from, if applicable.
    """

    flow_name: str
    node_results: Dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0
    nodes_completed: int = 0
    nodes_total: int = 0
    checkpoint_path: Optional[str] = None
    resumed_from: Optional[str] = None
