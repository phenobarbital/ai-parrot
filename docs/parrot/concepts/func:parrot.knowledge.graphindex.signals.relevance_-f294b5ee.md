---
type: Concept
title: relevance_neighborhood()
id: func:parrot.knowledge.graphindex.signals.relevance_neighborhood
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Top-K nodes most relevant to ``node_id`` by combined score.
---

# relevance_neighborhood

```python
def relevance_neighborhood(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], node_id: str, top_k: int=10, config: Optional[SignalRelevanceConfig]=None, candidate_pool: Optional[Iterable[str]]=None, embedder: Optional['GraphIndexEmbedder']=None) -> list[SignalRelevance]
```

Top-K nodes most relevant to ``node_id`` by combined score.
