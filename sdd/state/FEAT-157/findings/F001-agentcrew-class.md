---
id: F001
query: "AgentCrew class structure and constructor"
type: read
file: packages/ai-parrot/src/parrot/bots/orchestration/crew.py
---

## AgentCrew Class — Constructor & Architecture

- File: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` (3600+ lines)
- Class: `AgentCrew(PersistenceMixin, SynthesisMixin)` at line 148
- Constructor (lines 187-287) accepts:
  - `name`, `agents`, `shared_tool_manager`, `max_parallel_tasks`, `llm`
  - `agent_execution_timeout`, `persist_results`, `result_storage`
- Internal state: `self.agents: Dict[str, Agent]`, `self.workflow_graph: Dict[str, _CrewAgentNode]`
- Event system: subscribes to agent events at lines 374-385 (EVENT_STATUS_CHANGED, EVENT_TASK_STARTED, EVENT_TASK_COMPLETED, EVENT_TASK_FAILED)
- **No crew-level on_complete/on_error hooks currently exist**
