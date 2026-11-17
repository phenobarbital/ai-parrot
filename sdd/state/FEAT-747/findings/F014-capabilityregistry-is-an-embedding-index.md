---
id: F014
query_id: Q020
type: read
intent: "Follow-up of the registry tree: what the registry/capabilities sub-package indexes."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: FC-001
depth: 1
merged_from: FC-018
---

# F014 — CapabilityRegistry is an embedding index of tools/datasets, not agents

## Summary

`registry/capabilities/` (FEAT-070 intent routing) defines `CapabilityEntry(name, description, resource_type, embedding, metadata, not_for)` with `ResourceType` ∈ {dataset, tool, graph_node, pageindex, vector_collection} — **no `agent` resource type** — and `CapabilityRegistry` with `register`, `register_from_datasource`, `register_from_tool`, `register_from_yaml`, `build_index(embedding_fn)` and async `search` (cosine similarity over a numpy matrix, `not_for_penalty`). It is the natural seed for the brainstorm's `find_capability`, but it needs an embedding function (LLM-adjacent cost, not the <5 ms deterministic lookup L-S3 asks for) and has no locality or cost ranking.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  lines: 25-33
  symbol: `ResourceType`
  excerpt: |
    class ResourceType(str, Enum):
        DATASET = "dataset"; TOOL = "tool"; GRAPH_NODE = "graph_node"
        PAGEINDEX = "pageindex"; VECTOR_COLLECTION = "vector_collection"

- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  lines: 48-75
  symbol: `CapabilityEntry`
  excerpt: |
    class CapabilityEntry(BaseModel):
        name: str; description: str; resource_type: ResourceType
        embedding: Optional[list[float]]; metadata: dict[str, Any]; not_for: list[str]

- path: `packages/ai-parrot/src/parrot/registry/capabilities/registry.py`
  lines: 19-44
  symbol: `CapabilityRegistry`
  excerpt: |
    class CapabilityRegistry:
        def __init__(self, not_for_penalty: float = 0.5) -> None:
            self._entries: list[CapabilityEntry] = []
            self._embedding_matrix: Optional[np.ndarray] = None

- path: `packages/ai-parrot/src/parrot/registry/capabilities/registry.py`
  lines: 46-148
  symbol: `CapabilityRegistry.register* / build_index`
  excerpt: |
    def register(self, entry) / register_from_datasource / register_from_tool / register_from_yaml / async def build_index(self, embedding_fn)

- path: `packages/ai-parrot/src/parrot/registry/capabilities/registry.py`
  lines: 183
  symbol: `CapabilityRegistry.search`
  excerpt: |
    async def search(

## Notes

Depth-1 follow-up of Q020. Exposes a seam: adding `ResourceType.AGENT` + a keyword/cap-id exact path alongside the embedding path would give `AgentRegistry.find_capability` without a new index class.

[citation-check: verified] registry/capabilities — ResourceType 25, CapabilityEntry 48, IntentRouterConfig 149 (models.py); CapabilityRegistry 19, build_index 148, search 183 (registry.py)
