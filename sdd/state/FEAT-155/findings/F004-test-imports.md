---
id: F004
query: "grep from parrot.bots.orchestration in tests"
type: grep
---

## Test imports still using orchestration path

15 test files with 27+ import lines from `parrot.bots.orchestration`:

- `test_agent_crew_examples.py` — AgentCrew
- `test_crew_parallel_regression.py` — AgentCrew
- `test_execution_memory_integration.py` — BROKEN: imports from orchestration.storage and orchestration.tools which don't exist
- `test_crew_final_regression.py` — AgentNode, FlowContext, AgentRef, AgentCrew, crew module (12 import lines)
- `test_crew_loop_regression.py` — AgentCrew
- `test_crew_sequential_regression.py` — AgentCrew
- `test_crew_flow_regression.py` — AgentCrew
- `test_agentnode_execute.py` — _CrewAgentNode
- `test_orchestrator_agent.py` — OrchestratorAgent
- `test_flow_primitives/test_init_reexports.py` — AgentCrew, AgentTask (backward compat checks)
- `test_flow_primitives/test_contract.py` — crew module
