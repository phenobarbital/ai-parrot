---
type: Concept
title: signal_relevance()
id: func:parrot.knowledge.graphindex.signals.signal_relevance
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pairwise five-signal relevance over an assembled GraphIndex.
---

# signal_relevance

```python
def signal_relevance(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], node_a: str, node_b: str, config: Optional[SignalRelevanceConfig]=None, embedder: Optional['GraphIndexEmbedder']=None) -> SignalRelevance
```

Pairwise five-signal relevance over an assembled GraphIndex.

See module docstring for the signal definitions. ``nodes`` is
currently accepted for forward-compat with FEAT-191/-192 callers
but not used here — every signal reads its inputs from the
in-memory graph payloads.

Raises:
    KeyError: If either ``node_a`` or ``node_b`` is not in the graph.
