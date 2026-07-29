---
type: Concept
title: build_dev_loop_flow()
id: func:parrot.flows.dev_loop.flow.build_dev_loop_flow
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build the eight-node dev-loop ``AgentsFlow`` (FEAT-132).
---

# build_dev_loop_flow

```python
def build_dev_loop_flow(*, dispatcher: ClaudeCodeDispatcher, jira_toolkit: Any, log_toolkits: Dict[str, Any], redis_url: str, name: str='dev-loop', publish_flow_events: bool=True, lifecycle_events: bool=True, development_dispatcher: Optional[Any]=None, development_profile: Optional[Any]=None, git_toolkit: Optional[Any]=None, repos: Optional[list[RepoSpec]]=None, codereview_dispatcher: Optional[Any]=None) -> AgentsFlow
```

Build the eight-node dev-loop ``AgentsFlow`` (FEAT-132).

Topology:

- ``IntentClassifierNode`` routes:
  - ``kind == "bug"`` → ``BugIntakeNode`` → ``ResearchNode``
  - ``kind != "bug"`` → ``ResearchNode`` directly
- ``ResearchNode`` → ``DevelopmentNode`` → ``QANode``
- ``QANode`` → ``DeploymentHandoffNode`` (passed) or ``FailureHandlerNode``
- ``DeploymentHandoffNode`` → ``DevLoopCloseNode``
- Any hard error from any middle node → ``FailureHandlerNode``
  (``on_error`` edges; untaken paths are skip-propagated by the engine)

Args:
    dispatcher: A pre-built :class:`ClaudeCodeDispatcher` (shared by
        Research, Development, and QA nodes).
    jira_toolkit: Service-account ``JiraToolkit`` instance.
    log_toolkits: Mapping of source kind → toolkit. Recognised keys:
        ``"cloudwatch"``, ``"elasticsearch"``.
    redis_url: Redis URL for ``IntentClassifierNode`` /
        ``BugIntakeNode`` intake events and the flow-level
        node-lifecycle events.
    name: Flow name (default ``"dev-loop"``).
    publish_flow_events: When True (default), attach a
        :class:`FlowEventPublisher` to the engine's ``on_node_event``
        hook. The publisher reads the run_id from
        ``flow._run_id_holder`` (seeded by ``DevLoopRunner``).
    lifecycle_events: When True (default), also attach a
        :class:`parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter`
        so typed FEAT-176 events (FlowStarted/NodeCompleted/…) reach
        the global lifecycle registry — and through it the OTel /
        logging / usage subscribers.
    development_dispatcher: Optional dispatcher used only by
        ``DevelopmentNode``. Defaults to ``dispatcher``.
    development_profile: Optional dispatch profile passed only to
        ``DevelopmentNode``.
    codereview_dispatcher: Optional ``AbstractCodeReviewDispatcher``
        (FEAT-270) used by ``QANode`` for the code-review gate. Defaults
        to ``None``, in which case ``QANode`` auto-wraps ``dispatcher``
        in a ``ClaudeCodeReviewDispatcher`` (backward compat).

Returns:
    A wired :class:`AgentsFlow` instance ready to ``run_flow()``.
