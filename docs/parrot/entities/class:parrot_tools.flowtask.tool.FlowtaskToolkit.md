---
type: Wiki Entity
title: FlowtaskToolkit
id: class:parrot_tools.flowtask.tool.FlowtaskToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for executing Flowtask components and tasks dynamically.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# FlowtaskToolkit

Defined in [`parrot_tools.flowtask.tool`](../summaries/mod:parrot_tools.flowtask.tool.md).

```python
class FlowtaskToolkit(AbstractToolkit)
```

Toolkit for executing Flowtask components and tasks dynamically.

This toolkit provides multiple tools for:
- Running individual Flowtask components with custom input data
- Executing local Flowtask tasks by program/task name
- Calling remote Flowtask API endpoints
- Running tasks from JSON/YAML code definitions

Example usage:
    toolkit = FlowtaskToolkit()
    tools = toolkit.get_tools()

    # Execute a component
    result = await toolkit.flowtask_component_call(
        component_name="GooglePlaces",
        input_data=[{"address": "123 Main St"}]
    )

    # Run a local task
    result = await toolkit.flowtask_task_execution(
        program="nextstop",
        task_name="employees_report"
    )

## Methods

- `async def flowtask_component_call(self, component_name: str, input_data: Union[Dict[str, Any], List[Dict[str, Any]], str], attributes: Optional[Dict[str, Any]]=None, structured_output: Optional[Dict[str, Any]]=None, return_as_dataframe: bool=False) -> Dict[str, Any]` — Execute a single Flowtask component with custom input data and attributes.
- `async def flowtask_task_execution(self, program: str, task_name: str, debug: bool=True, storage: str='default', variables: Optional[Dict[str, Any]]=None, attributes: Optional[Dict[str, Any]]=None, params: Optional[Dict[str, Any]]=None, ignore_steps: Optional[List[str]]=None, run_only: Optional[List[str]]=None) -> Dict[str, Any]` — Execute a Flowtask Task locally by program and task name.
- `async def flowtask_remote_execution(self, program: str, task_name: str, long_running: bool=False, timeout: float=300.0, max_retries: int=3, backoff_factor: float=1.0) -> Dict[str, Any]` — Execute a Flowtask Task remotely via the Flowtask API (Task Launcher).
- `async def flowtask_code_execution(self, task_code: str, format: TaskCodeFormat=TaskCodeFormat.YAML) -> Dict[str, Any]` — Execute a Flowtask Task from a JSON or YAML code definition.
- `async def flowtask_task_service(self, program: str, task_name: str, method: str='GET', params: Optional[Dict[str, Any]]=None, timeout: float=300.0) -> Dict[str, Any]` — Execute a Flowtask Task via the Task Service REST API (synchronous).
- `async def flowtask_list_tasks(self, program: Optional[str]=None, fields: Optional[List[str]]=None, timeout: float=60.0) -> Dict[str, Any]` — List available Flowtask tasks for a given program.
- `def list_known_components(self) -> List[str]` — Get a list of known Flowtask components.
- `def add_known_component(self, component_name: str) -> None` — Add a component to the known components list.
- `def clear_component_cache(self) -> None` — Clear the component import cache.
