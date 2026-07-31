---
type: Concept
title: build_dev_loop_node_factories()
id: func:parrot.flows.dev_loop.factories.build_dev_loop_node_factories
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Return the ``{dev_loop.* type: factory}`` map binding live deps.'
---

# build_dev_loop_node_factories

```python
def build_dev_loop_node_factories(*, dispatcher: Any, jira_toolkit: Any, redis_url: str, development_dispatcher: Optional[Any]=None, development_profile: Optional[Any]=None, git_toolkit: Optional[Any]=None, log_toolkits: Optional[Dict[str, Any]]=None, repos: Optional[List[RepoSpec]]=None, codereview_dispatcher: Optional[Any]=None) -> Dict[str, NodeFactory]
```

Return the ``{dev_loop.* type: factory}`` map binding live deps.

Args:
    dispatcher: Shared dispatcher for Research/QA and the default
        Development path.
    jira_toolkit: Service-account JiraToolkit.
    redis_url: Redis URL for the intake nodes' event streams.
    development_dispatcher: Optional dispatcher used only by
        ``DevelopmentNode``. Defaults to ``dispatcher``.
    development_profile: Optional dispatch profile passed only to
        ``DevelopmentNode``.
    git_toolkit: Optional ``GitToolkit`` for repo provisioning (FEAT-250).
    log_toolkits: Optional ``{source_kind: toolkit}`` map for ResearchNode.
    repos: Optional ``RepoSpec`` list cloned/pulled before Development.
    codereview_dispatcher: Optional ``AbstractCodeReviewDispatcher``
        (FEAT-270) used by ``QANode`` for the code-review gate. Defaults
        to ``None``, in which case ``QANode`` auto-wraps ``dispatcher``
        in a ``ClaudeCodeReviewDispatcher`` (backward compat).

Returns:
    A mapping suitable for ``node_factories=`` on
    ``AgentsFlow.from_definition``.
