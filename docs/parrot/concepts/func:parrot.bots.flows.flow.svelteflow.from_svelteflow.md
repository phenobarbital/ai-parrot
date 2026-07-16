---
type: Concept
title: from_svelteflow()
id: func:parrot.bots.flows.flow.svelteflow.from_svelteflow
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert SvelteFlow node/edge data into a ``FlowDefinition``.
---

# from_svelteflow

```python
def from_svelteflow(sf_data: Dict[str, Any], flow_name: str) -> FlowDefinition
```

Convert SvelteFlow node/edge data into a ``FlowDefinition``.

Args:
    sf_data: Dict with ``nodes`` and ``edges`` from SvelteFlow.
    flow_name: Name for the resulting flow.

Returns:
    ``FlowDefinition`` ready for persistence or materialisation.

Notes:
    Multiple SvelteFlow edges sharing the same source are collapsed
    back into a single ``EdgeDefinition`` with ``to`` as a list
    (fan-in grouping) only when they share the same condition and
    predicate.  Otherwise they stay as individual edges.
