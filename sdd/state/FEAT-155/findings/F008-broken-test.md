---
id: F008
query: "grep orchestration.storage orchestration.tools in tests"
type: grep
---

## Already-broken test imports

`tests/test_execution_memory_integration.py` has two imports that reference
modules that do NOT exist in orchestration/:

- Line 15: `from parrot.bots.orchestration.storage import ExecutionMemory`
- Line 16: `from parrot.bots.orchestration.tools import ResultRetrievalTool`

These modules were moved to:
- `parrot.bots.flows.core.storage.memory.ExecutionMemory`
- `parrot.bots.flows.tools.ResultRetrievalTool`

This test is already broken regardless of this migration.
