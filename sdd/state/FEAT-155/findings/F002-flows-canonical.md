---
id: F002
query: "tree packages/ai-parrot/src/parrot/bots/flows"
type: tree
---

## Flows module — canonical location

All orchestration code already has canonical copies in `packages/ai-parrot/src/parrot/bots/flows/`:

- `agents/orchestrator.py` — OrchestratorAgent (340 lines, import paths adjusted)
- `agents/a2a_orchestrator.py` — A2AOrchestratorAgent (322 lines, imports from .orchestrator)
- `agents/hr.py` — HRAgentFactory, RAGHRAgent, EmployeeDataAgent (495 lines)
- `agents/__init__.py` — exports all agent classes
- `crew/crew.py` — AgentCrew (3564 lines, uses new FlowResult/NodeExecutionInfo models)
- `crew/nodes.py` — CrewAgentNode
- `crew/__init__.py` — exports AgentCrew, CrewAgentNode
- `core/` — all shared primitives (types, node, fsm, context, result, transition, storage)
- `tools.py` — ResultRetrievalTool
- `__init__.py` — master re-export hub (30+ symbols)
