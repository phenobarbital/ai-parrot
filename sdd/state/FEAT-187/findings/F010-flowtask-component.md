---
id: F010
query: Q012
type: grep+read
target: packages/ai-parrot-tools/src/parrot_tools/flowtask/
---

# F010 — Flowtask Component Architecture

**Status**: Confirmed — external dependency

## Two Flowtask integrations

### 1. FlowtaskInterface (mixin)
Location: `packages/ai-parrot/src/parrot/interfaces/flowtask.py`
- Async methods for Flowtask API interaction
- `run_task_remote`, `run_task_local`, `dispatch_task`, etc.
- Dynamically imports `flowtask.tasks.task.Task` and `flowtask.storages.MemoryTaskStorage`

### 2. FlowtaskToolkit
Location: `packages/ai-parrot-tools/src/parrot_tools/flowtask/tool.py`
- Extends `AbstractToolkit`
- Tools: `flowtask_component_call`, `flowtask_task_execution`, etc.
- Components loaded dynamically: `flowtask.components.<Name>`
- Pattern: `async with component as comp: result = await comp.run()`

## Key finding
The `Component` base class is in the **external `flowtask` package** (not in ai-parrot).
A new GraphIndex Flowtask component would need to follow the external flowtask package's
Component contract, not an ai-parrot-internal one.
