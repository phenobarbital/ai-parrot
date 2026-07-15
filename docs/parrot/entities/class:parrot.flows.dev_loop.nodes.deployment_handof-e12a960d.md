---
type: Wiki Entity
title: DeploymentHandoffNode
id: class:parrot.flows.dev_loop.nodes.deployment_handoff.DeploymentHandoffNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fifth (success-path) node — handles PR creation and Jira handoff.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# DeploymentHandoffNode

Defined in [`parrot.flows.dev_loop.nodes.deployment_handoff`](../summaries/mod:parrot.flows.dev_loop.nodes.deployment_handoff.md).

```python
class DeploymentHandoffNode(DevLoopNode)
```

Fifth (success-path) node — handles PR creation and Jira handoff.

Args:
    jira_toolkit: ``parrot_tools.jiratoolkit.JiraToolkit`` instance
        already wired with bot credentials.
    git_toolkit: Optional Git toolkit used for the HTTP fallback when
        ``gh`` is unavailable. The toolkit's ``create_pull_request``
        shape is file-bundle oriented; in v1 we prefer the bare HTTP
        fallback (``_create_pr_via_rest``) which the test suite
        patches directly.
    gh_cli_path: Override path to the ``gh`` CLI binary.
    target_repo: ``"<owner>/<repo>"`` for the GitHub REST fallback.
        Reads ``GITHUB_REPOSITORY`` env var when not provided.
    base_branch: Default base branch for the PR (default ``"dev"``).
    name: Node id (default ``"deployment_handoff"``).

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> Dict[str, Any]` — Push, PR, transition Jira, comment.
