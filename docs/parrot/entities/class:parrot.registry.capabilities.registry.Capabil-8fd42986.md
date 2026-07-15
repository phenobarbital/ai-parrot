---
type: Wiki Entity
title: CapabilityRegistry
id: class:parrot.registry.capabilities.registry.CapabilityRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Semantic resource index for intent routing.
---

# CapabilityRegistry

Defined in [`parrot.registry.capabilities.registry`](../summaries/mod:parrot.registry.capabilities.registry.md).

```python
class CapabilityRegistry
```

Semantic resource index for intent routing.

Stores capability entries and provides embedding-based cosine similarity
search to discover relevant strategies for a given user query.

Supports registration from:
- Manual CapabilityEntry objects.
- DataSource instances (DatasetManager sources).
- AbstractTool instances.
- YAML configuration files.

Args:
    not_for_penalty: Score multiplier applied when a query matches a
        ``not_for`` pattern (default 0.5 — halves the score).

## Methods

- `def register(self, entry: CapabilityEntry) -> None` — Register a capability entry.
- `def register_from_datasource(self, source: Any) -> None` — Create and register a CapabilityEntry from a DataSource.
- `def register_from_tool(self, tool: Any) -> None` — Create and register a CapabilityEntry from an AbstractTool.
- `def register_from_yaml(self, path: str) -> None` — Load and register capability entries from a YAML file.
- `async def build_index(self, embedding_fn: Callable) -> None` — Compute embeddings for all entries and build the search matrix.
- `async def search(self, query: str, top_k: int=5, resource_types: Optional[list[ResourceType]]=None) -> list[RouterCandidate]` — Embed the query and return top-K matching capabilities.
