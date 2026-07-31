---
type: Wiki Entity
title: FlowCompletedEvent
id: class:parrot.core.events.lifecycle.events.flow.FlowCompletedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted after the scheduler loop ends and the result is aggregated.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# FlowCompletedEvent

Defined in [`parrot.core.events.lifecycle.events.flow`](../summaries/mod:parrot.core.events.lifecycle.events.flow.md).

```python
class FlowCompletedEvent(LifecycleEvent)
```

Emitted after the scheduler loop ends and the result is aggregated.

Emitted for every terminal status (``completed`` / ``partial`` /
``failed``) — inspect :attr:`status` to discriminate.

Attributes:
    flow_name: Name of the ``AgentsFlow`` instance.
    run_id: Caller-supplied run identifier.
    status: Aggregated run status (``FlowStatus`` value).
    duration_ms: Wall-clock time of the whole run in milliseconds.
    completed_count: Nodes that finished successfully.
    failed_count: Nodes that raised (after exhausting retries).
    skipped_count: Nodes skipped by OR-join skip-propagation.
