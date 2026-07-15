---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.base
id: mod:parrot.flows.dev_loop.nodes.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DevLoopNode — shared base for the dev-loop flow nodes.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: defines
- concept: func:parrot.flows.dev_loop.nodes.base.register_dev_loop_node
  rel: defines
- concept: func:parrot.flows.dev_loop.nodes.base.scrub_git_output
  rel: defines
- concept: func:parrot.flows.dev_loop.nodes.base.transition_issue_with_candidates
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.node
  rel: references
- concept: mod:parrot.bots.flows.flow.flow
  rel: references
---

# `parrot.flows.dev_loop.nodes.base`

DevLoopNode — shared base for the dev-loop flow nodes.

Adapts the dev-loop nodes to the FEAT-163 ``AgentsFlow`` scheduler
contract:

- carries the ``dependencies`` / ``successors`` / ``fsm`` fields the
  event-driven scheduler expects (the FSM is auto-created per node and
  re-created per run by ``AgentsFlow._materialize_nodes``);
- normalizes the execute signature to ``execute(ctx, deps, **kwargs)``
  where ``ctx`` is a :class:`FlowContext`. For unit-test ergonomics a
  plain dict is also accepted and treated as the shared state itself.

Cross-node payloads (``bug_brief``, ``research_output``,
``development_output``, ``qa_report``, ``run_id``, …) travel in
``FlowContext.shared_data``.

## Classes

- **`DevLoopNode(Node)`** — Base node for the dev-loop flow (FEAT-129 / FEAT-132).

## Functions

- `def scrub_git_output(text: str) -> str` — Redact credentials from raw git CLI output before surfacing it.
- `async def transition_issue_with_candidates(jira: Any, issue: str, candidates: Sequence[str], *, logger: logging.Logger, **kwargs: Any) -> Optional[Dict[str, Any]]` — Apply the first candidate Jira transition that the workflow exposes.
- `def register_dev_loop_node(name: str)` — Idempotent ``@register_node`` for the dev-loop node types (FEAT-250).
