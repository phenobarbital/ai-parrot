---
type: Wiki Entity
title: FlowExecutor
id: class:parrot_tools.scraping.flow_executor.FlowExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Orchestrate end-to-end execution of a :class:`ScrapingFlow`.
---

# FlowExecutor

Defined in [`parrot_tools.scraping.flow_executor`](../summaries/mod:parrot_tools.scraping.flow_executor.md).

```python
class FlowExecutor
```

Orchestrate end-to-end execution of a :class:`ScrapingFlow`.

Args:
    browser: A live Playwright ``Browser`` instance.
    registry: Optional plan registry used to resolve ``plan_ref`` values
        that are stored ``ScrapingPlan`` names/fingerprints.
    config: Driver configuration forwarded to ``execute_plan_steps``.
    concurrency: Maximum concurrent fan-out executions.
    checkpoint_dir: Directory for per-flow checkpoint files. When
        ``None``, checkpointing/resume are disabled.
    logger: Optional logger.
    templates: Optional mapping of ``template_name -> TemplatePlan`` used
        to resolve and bind ``plan_ref`` values. (The dedicated
        ``TemplatePlanRegistry`` is deferred per the spec; this mapping is
        the template source in the meantime.)

## Methods

- `async def run(self, flow: ScrapingFlow, params: Optional[Dict[str, Any]]=None, resume_from: Optional[str]=None) -> FlowResult` — Execute *flow* end-to-end and return an aggregated :class:`FlowResult`.
