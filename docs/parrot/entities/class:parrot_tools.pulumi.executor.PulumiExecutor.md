---
type: Wiki Entity
title: PulumiExecutor
id: class:parrot_tools.pulumi.executor.PulumiExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executes Pulumi CLI commands via Docker or direct CLI.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: extends
---

# PulumiExecutor

Defined in [`parrot_tools.pulumi.executor`](../summaries/mod:parrot_tools.pulumi.executor.md).

```python
class PulumiExecutor(BaseExecutor)
```

Executes Pulumi CLI commands via Docker or direct CLI.

Supports Docker execution mode or direct CLI invocation.
Parses JSON output from Pulumi commands into structured models.

Pulumi CLI patterns:
    pulumi preview --json --stack <stack>
    pulumi up --yes --json --stack <stack>
    pulumi destroy --yes --json --stack <stack>
    pulumi stack output --json --stack <stack>

Example:
    config = PulumiConfig(default_stack="dev")
    executor = PulumiExecutor(config)
    result = await executor.preview("/path/to/project")

## Methods

- `async def preview(self, project_path: str, stack: Optional[str]=None, config_values: Optional[dict[str, Any]]=None, target: Optional[list[str]]=None, refresh: bool=True) -> PulumiOperationResult` — Preview infrastructure changes without applying.
- `async def up(self, project_path: str, stack: Optional[str]=None, config_values: Optional[dict[str, Any]]=None, auto_approve: bool=True, target: Optional[list[str]]=None, refresh: bool=True, replace: Optional[list[str]]=None) -> PulumiOperationResult` — Apply infrastructure changes.
- `async def destroy(self, project_path: str, stack: Optional[str]=None, auto_approve: bool=True, target: Optional[list[str]]=None) -> PulumiOperationResult` — Tear down infrastructure.
- `async def stack_output(self, project_path: str, stack: Optional[str]=None) -> PulumiOperationResult` — Get current stack outputs.
- `async def list_stacks(self, project_path: str) -> tuple[list[str], str]` — List all stacks in the project.
