---
id: F003
query: "grep from parrot.bots.orchestration in handlers"
type: grep
---

## Handler imports still using orchestration path

Two handler files import AgentCrew from the legacy path:

- `src/parrot/handlers/crew/handler.py:18` — `from parrot.bots.orchestration.crew import AgentCrew`
- `src/parrot/handlers/crew/execution_handler.py:7` — `from parrot.bots.orchestration.crew import AgentCrew`
