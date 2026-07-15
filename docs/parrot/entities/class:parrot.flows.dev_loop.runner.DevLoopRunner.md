---
type: Wiki Entity
title: DevLoopRunner
id: class:parrot.flows.dev_loop.runner.DevLoopRunner
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hosts dev-loop flow runs behind a global concurrency cap.
---

# DevLoopRunner

Defined in [`parrot.flows.dev_loop.runner`](../summaries/mod:parrot.flows.dev_loop.runner.md).

```python
class DevLoopRunner
```

Hosts dev-loop flow runs behind a global concurrency cap.

Args:
    flow: The :class:`AgentsFlow` built by ``build_dev_loop_flow``.
    max_concurrent_runs: Cap on simultaneously executing runs.
        Defaults to ``conf.FLOW_MAX_CONCURRENT_RUNS``.

## Methods

- `def active_runs(self) -> Set[str]` — Run IDs currently executing (copy).
- `def is_active(self, run_id: str) -> bool` — True while *run_id* is executing.
- `async def run(self, brief: WorkBrief, *, run_id: Optional[str]=None, initial_task: str='', extra_shared: Optional[Dict[str, Any]]=None) -> FlowResult` — Execute one dev-loop run for *brief*, respecting the run cap.
- `async def run_revision(self, brief: RevisionBrief, *, run_id: Optional[str]=None) -> FlowResult` — Execute a revision-mode run for *brief* (FEAT-250 G6).
