---
id: F001
query: "tree packages/ai-parrot/src/parrot/bots/orchestration"
type: tree
---

## Orchestration module file inventory

Files remaining in `packages/ai-parrot/src/parrot/bots/orchestration/`:

- `__init__.py` — re-exports AgentCrew, AgentNode, FlowContext, OrchestratorAgent, A2AOrchestratorAgent
- `crew.py` — 3615 lines, HYBRID: full AgentCrew using old CrewResult models + imports from flows.core
- `agent.py` — 334 lines, FULL duplicate of OrchestratorAgent
- `a2a_orchestrator.py` — 308 lines, FULL duplicate of A2AOrchestratorAgent
- `hr.py` — 434 lines, FULL duplicate of HRAgentFactory/RAGHRAgent/EmployeeDataAgent
- `verify.py` — 203 lines, standalone FSM verification script
- `README.md` — 464 lines, documentation
