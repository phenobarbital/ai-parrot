---
type: Wiki Entity
title: PulumiToolkit
id: class:parrot_tools.pulumi.toolkit.PulumiToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for infrastructure deployment using Pulumi.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# PulumiToolkit

Defined in [`parrot_tools.pulumi.toolkit`](../summaries/mod:parrot_tools.pulumi.toolkit.md).

```python
class PulumiToolkit(AbstractToolkit)
```

Toolkit for infrastructure deployment using Pulumi.

Each public async method is exposed as a separate tool with the `pulumi_` prefix.

Available Operations:
- pulumi_plan: Preview infrastructure changes without applying
- pulumi_apply: Apply infrastructure changes
- pulumi_destroy: Tear down infrastructure
- pulumi_status: Check current stack state

Example:
    toolkit = PulumiToolkit()
    tools = toolkit.get_tools()

    # Use with agent
    agent = Agent(tools=tools)

    # Or call directly
    result = await toolkit.pulumi_plan("/path/to/project")

## Methods

- `async def pulumi_plan(self, project_path: str, stack_name: Optional[str]=None, config: Optional[dict[str, Any]]=None, target: Optional[list[str]]=None, refresh: bool=True) -> PulumiOperationResult` — Preview infrastructure changes without applying.
- `async def pulumi_apply(self, project_path: str, stack_name: Optional[str]=None, config: Optional[dict[str, Any]]=None, auto_approve: bool=True, target: Optional[list[str]]=None, refresh: bool=True, replace: Optional[list[str]]=None) -> PulumiOperationResult` — Apply infrastructure changes.
- `async def pulumi_destroy(self, project_path: str, stack_name: Optional[str]=None, auto_approve: bool=True, target: Optional[list[str]]=None) -> PulumiOperationResult` — Tear down infrastructure.
- `async def pulumi_status(self, project_path: str, stack_name: Optional[str]=None) -> PulumiOperationResult` — Check current stack state.
- `async def pulumi_list_stacks(self, project_path: str) -> tuple[list[str], str]` — List all stacks in the project.
