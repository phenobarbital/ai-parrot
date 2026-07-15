---
type: Concept
title: compute_pairwise_signals()
id: func:parrot.knowledge.graphindex.signals.compute_pairwise_signals
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raw five signals without combination. Cheap building block.
---

# compute_pairwise_signals

```python
def compute_pairwise_signals(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], node_a: str, node_b: str, embedder: Optional['GraphIndexEmbedder']=None) -> dict[str, float]
```

Raw five signals without combination. Cheap building block.
