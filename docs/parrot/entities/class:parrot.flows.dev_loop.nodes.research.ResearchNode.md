---
type: Wiki Entity
title: ResearchNode
id: class:parrot.flows.dev_loop.nodes.research.ResearchNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Second node — Jira + log fetch + sdd-research dispatch.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# ResearchNode

Defined in [`parrot.flows.dev_loop.nodes.research`](../summaries/mod:parrot.flows.dev_loop.nodes.research.md).

```python
class ResearchNode(DevLoopNode)
```

Second node — Jira + log fetch + sdd-research dispatch.

Args:
    dispatcher: A :class:`ClaudeCodeDispatcher` instance shared by
        every node in the flow.
    jira_toolkit: A pre-built ``parrot_tools.jiratoolkit.JiraToolkit``
        wired with service-account credentials.
    log_toolkits: Mapping ``"cloudwatch"|"elasticsearch"`` →
        toolkit instance. Optional kinds may be missing; an unknown
        ``LogSource.kind`` raises ``ValueError`` at dispatch time.
    name: Node id, default ``"research"``.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> ResearchOutput` — Run the research phase. Returns a validated :class:`ResearchOutput`.
