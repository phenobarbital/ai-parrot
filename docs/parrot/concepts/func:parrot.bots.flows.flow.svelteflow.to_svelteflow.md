---
type: Concept
title: to_svelteflow()
id: func:parrot.bots.flows.flow.svelteflow.to_svelteflow
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Convert a ``FlowDefinition`` to SvelteFlow node/edge format.
---

# to_svelteflow

```python
def to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]
```

Convert a ``FlowDefinition`` to SvelteFlow node/edge format.

Returns a dict with ``nodes`` and ``edges`` arrays suitable for
direct consumption by SvelteFlow's ``<SvelteFlow>`` component.

Fan-out edges (one source → multiple targets) are expanded into
individual SvelteFlow edges.
