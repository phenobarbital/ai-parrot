---
type: Wiki Summary
title: parrot.flows.dev_loop.flow
id: mod:parrot.flows.dev_loop.flow
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: build_dev_loop_flow — wire the eight dev-loop nodes into an AgentsFlow.
relates_to:
- concept: class:parrot.flows.dev_loop.flow.FlowEventPublisher
  rel: defines
- concept: func:parrot.flows.dev_loop.flow.build_dev_loop_flow
  rel: defines
- concept: mod:parrot.bots.flows
  rel: references
- concept: mod:parrot.bots.flows.flow.telemetry
  rel: references
- concept: mod:parrot.flows.dev_loop.definition
  rel: references
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: references
- concept: mod:parrot.flows.dev_loop.factories
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
---

# `parrot.flows.dev_loop.flow`

build_dev_loop_flow — wire the eight dev-loop nodes into an AgentsFlow.

Implements **Module 10**. Topology (FEAT-132):

.. code-block:: text

    IntentClassifier ──(kind=="bug")──► BugIntake → Research → Development → QA → DeploymentHandoff → Close
                     └─(kind!="bug")──────────────► Research      │
                                                                   └─(passed=False)→ FailureHandler
                                                                   ↑(any node hard-error)

Built on the FEAT-163 ``AgentsFlow`` executor using explicit conditional
edges (``add_edge``): the engine's OR-join + skip-propagation semantics
make the branch merge at ``research`` and the on_error fan-in at
``failure_handler`` first-class — no adapters, no legacy API.

When a ``redis_url`` is provided, the flow publishes node lifecycle
events (``flow.node_started`` / ``node_completed`` / ``node_failed`` /
``node_skipped``) to the per-run stream ``flow:{run_id}:flow`` via the
engine's ``on_node_event`` hook (spec G4 — the multiplexer's "flow" view).

The factory is a pure function — no globals, no env reads.

## Classes

- **`FlowEventPublisher`** — Publishes AgentsFlow node-lifecycle events to ``flow:{run_id}:flow``.

## Functions

- `def build_dev_loop_flow(*, dispatcher: ClaudeCodeDispatcher, jira_toolkit: Any, log_toolkits: Dict[str, Any], redis_url: str, name: str='dev-loop', publish_flow_events: bool=True, lifecycle_events: bool=True, development_dispatcher: Optional[Any]=None, development_profile: Optional[Any]=None, git_toolkit: Optional[Any]=None, repos: Optional[list[RepoSpec]]=None, codereview_dispatcher: Optional[Any]=None) -> AgentsFlow` — Build the eight-node dev-loop ``AgentsFlow`` (FEAT-132).
