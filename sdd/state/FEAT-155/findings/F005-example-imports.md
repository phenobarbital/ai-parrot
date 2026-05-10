---
id: F005
query: "grep from parrot.bots.orchestration in examples"
type: grep
---

## Example imports still using orchestration path

20 import lines across 13 example files in `examples/`:

Crew examples:
- `crew/orchestator_test.py` — OrchestratorAgent
- `crew/crew_flows.py` — AgentCrew, FlowContext
- `crew/crew_loop.py` — AgentCrew
- `crew/crew_nav_qa.py` — AgentCrew, FlowContext
- `crew/crew_qa.py` — AgentCrew
- `crew/test_agenttool.py` — OrchestratorAgent
- `crew/orchestrator_example.py` — OrchestratorAgent
- `crew/reproduce_orchestrator.py` — OrchestratorAgent
- `crew/workday_jira_db_orchestrator.py` — OrchestratorAgent
- `crew/simple.py` — AgentCrew, FlowContext, OrchestratorAgent
- `crew/a2a_orchestrator_example.py` — A2AOrchestratorAgent

Decision workflow examples (import AgentsFlow — separate from orchestration):
- `decision_workflow_example.py` — AgentsFlow, decision_node
- `decision_simple_working.py` — AgentsFlow, decision_node
- `decision_workflow_simple_test.py` — AgentsFlow, decision_node
- `execution_memory_demo.py` — AgentsFlow, ResultRetrievalTool
