---
id: F006
query: "diff orchestration/crew.py flows/crew/crew.py"
type: read
---

## crew.py divergence between old and new

`orchestration/crew.py` (3615 lines) vs `flows/crew/crew.py` (3564 lines):

Key differences:
1. **Result models**: orchestration/ uses old `CrewResult`, `AgentExecutionInfo`, `build_agent_metadata` from `parrot.models.crew`. flows/ uses new `FlowResult`, `NodeExecutionInfo`, `build_node_metadata` from `flows.core.result`.
2. **Import paths**: orchestration/ uses relative `..agent` (2 levels up). flows/ uses `...agent` (3 levels up from `flows/crew/`).
3. **AgentContext removed**: flows/ version (TASK-980) replaced `AgentContext` with `FlowContext` for execution state.
4. **Hybrid pattern**: orchestration/crew.py already imports core types from `flows.core` (FlowContext, AgentRef, etc.) but keeps its own AgentCrew class with old result models.
5. **Node class**: orchestration/ has `_CrewAgentNode` wrapper. flows/ has `CrewAgentNode` in separate `nodes.py`.
