---
type: Concept
title: register_dev_loop_node()
id: func:parrot.flows.dev_loop.nodes.base.register_dev_loop_node
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Idempotent ``@register_node`` for the dev-loop node types (FEAT-250).
---

# register_dev_loop_node

```python
def register_dev_loop_node(name: str)
```

Idempotent ``@register_node`` for the dev-loop node types (FEAT-250).

The engine's :func:`register_node` deliberately raises on a duplicate
registration. The dev-loop's lazy-import guarantee (spec §7 R1, exercised
by ``test_lazy_import``) re-imports ``parrot.flows.dev_loop`` after purging
it from ``sys.modules`` while the engine's ``NODE_REGISTRY`` persists — so a
plain ``@register_node`` decorator would raise on the second import. This
wrapper makes registration a no-op when ``name`` is already registered.
