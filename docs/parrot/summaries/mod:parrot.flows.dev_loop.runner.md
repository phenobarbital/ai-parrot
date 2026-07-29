---
type: Wiki Summary
title: parrot.flows.dev_loop.runner
id: mod:parrot.flows.dev_loop.runner
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DevLoopRunner — orchestrator-side hosting for the dev-loop flow.
relates_to:
- concept: class:parrot.flows.dev_loop.runner.DevLoopRunner
  rel: defines
- concept: func:parrot.flows.dev_loop.runner.build_dev_loop_revision_flow
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.bots.flows
  rel: references
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.flows.dev_loop.definition
  rel: references
- concept: mod:parrot.flows.dev_loop.factories
  rel: references
- concept: mod:parrot.flows.dev_loop.flow
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
---

# `parrot.flows.dev_loop.runner`

DevLoopRunner — orchestrator-side hosting for the dev-loop flow.

Closes spec G5's orchestrator half: the dispatcher already caps
concurrent Claude Code dispatches (``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``);
this runner caps concurrent *flow runs* with an ``asyncio.Semaphore``
sized by ``FLOW_MAX_CONCURRENT_RUNS``.

Responsibilities:

- mint (or accept) the ``run_id`` and seed the :class:`FlowContext`
  (``shared_data['bug_brief']`` / ``['work_brief']`` / ``['run_id']``);
- bind the run_id to the flow's :class:`FlowEventPublisher` so
  node-lifecycle events land on ``flow:{run_id}:flow``;
- track active runs (``active_runs`` / ``is_active``).

## Classes

- **`DevLoopRunner`** — Hosts dev-loop flow runs behind a global concurrency cap.

## Functions

- `def build_dev_loop_revision_flow(*, dispatcher: Any, jira_toolkit: Any, git_toolkit: Any, redis_url: str, codereview_dispatcher: Optional[Any]=None, name: str='dev-loop-revision', publish_flow_events: bool=True) -> AgentsFlow` — Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).
