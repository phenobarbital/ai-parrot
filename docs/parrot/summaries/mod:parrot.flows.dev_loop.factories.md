---
type: Wiki Summary
title: parrot.flows.dev_loop.factories
id: mod:parrot.flows.dev_loop.factories
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Node factories that bind live dependencies into the declarative dev-loop.
relates_to:
- concept: func:parrot.flows.dev_loop.factories.build_dev_loop_node_factories
  rel: defines
- concept: mod:parrot.bots.flows.flow.definition
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.bug_intake
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.close
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.deployment_handoff
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.development
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.failure_handler
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.intent_classifier
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.qa
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.research
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.revision_handoff
  rel: references
---

# `parrot.flows.dev_loop.factories`

Node factories that bind live dependencies into the declarative dev-loop.

:func:`build_dev_loop_node_factories` returns the ``{node_type: factory}`` map
consumed by ``AgentsFlow.from_definition(..., node_factories=...)`` (FEAT-250
TASK-001). Each factory closes over the live dependencies (dispatcher,
toolkits, redis url, repo specs) that a plain ``NodeDefinition.config`` dict
cannot carry, constructs the node with ``node_id == node_def.id``, and stamps
the ``dependencies``/``successors`` the materializer derived from the edges.

Importing this module also triggers ``@register_node`` registration of every
``dev_loop.*`` node type (the node classes are imported here).

## Functions

- `def build_dev_loop_node_factories(*, dispatcher: Any, jira_toolkit: Any, redis_url: str, development_dispatcher: Optional[Any]=None, development_profile: Optional[Any]=None, git_toolkit: Optional[Any]=None, log_toolkits: Optional[Dict[str, Any]]=None, repos: Optional[List[RepoSpec]]=None, codereview_dispatcher: Optional[Any]=None) -> Dict[str, NodeFactory]` — Return the ``{dev_loop.* type: factory}`` map binding live deps.
