---
type: Concept
title: build_dev_loop_revision_flow()
id: func:parrot.flows.dev_loop.runner.build_dev_loop_revision_flow
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).
---

# build_dev_loop_revision_flow

```python
def build_dev_loop_revision_flow(*, dispatcher: Any, jira_toolkit: Any, git_toolkit: Any, redis_url: str, codereview_dispatcher: Optional[Any]=None, name: str='dev-loop-revision', publish_flow_events: bool=True) -> AgentsFlow
```

Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).

Mirrors ``build_dev_loop_flow``'s declarative-materialize-then-explicit
execution: the nodes come from ``build_dev_loop_definition(revision=True)``
via the node factories, and the graph runs in explicit-edge mode (OR-join
on the ``failure_handler`` fan-in). Topology: ``development → qa →
(pass) revision_handoff → close`` / ``(fail) failure_handler``.
