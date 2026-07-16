---
type: Concept
title: build_dev_loop_definition()
id: func:parrot.flows.dev_loop.definition.build_dev_loop_definition
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the declarative dev-loop :class:`FlowDefinition`.
---

# build_dev_loop_definition

```python
def build_dev_loop_definition(*, revision: bool=False) -> FlowDefinition
```

Return the declarative dev-loop :class:`FlowDefinition`.

Args:
    revision: When ``True``, return the short revision-mode graph (entering
        at ``development`` and ending at the revision handoff/close). The
        revision graph is authored by FEAT-250 TASK-012; this function
        currently raises for ``revision=True`` so the parameter is part of
        the stable signature from TASK-010 onward.

Returns:
    A validated initial-run ``FlowDefinition`` reproducing the FEAT-132
    routing plus the new terminal ``close`` node.
