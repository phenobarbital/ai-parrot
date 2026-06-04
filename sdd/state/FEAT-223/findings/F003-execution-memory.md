# F003 — ExecutionMemory shared bus

**Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py` —
`@dataclass ExecutionMemory(VectorStoreMixin)`, 158 lines.

## Citations
- Fields (L32-35): `original_query`, `results: Dict[str, NodeResult]`,
  `execution_graph`, `execution_order`. Keyed by `node_id or agent_id` (L63).
- `add_result(result, vectorize=True)` (L55-77): stores result; optional async FAISS
  vectorization when an `embedding_model` is set.
- `get_context_for_agent(agent_id)` (L99-118): returns the PREVIOUS agent's result by
  execution_order — i.e. sequential semantics.
- `get_snapshot()` (L134-157): serialisable dump (results, order, graph, counts).

## Relevance
This is the in-process shared memory the orchestrator wires into all AgentTools
(F001 L199-204). A conferencing implementation can store each round's answers and the
votes here (e.g. round-tagged node_ids) for audit/snapshot, OR keep round state local to
the new method. `execution_order`-based `get_context_for_agent` is sequential, so the
parallel conference round should build peer-context explicitly rather than rely on it.
