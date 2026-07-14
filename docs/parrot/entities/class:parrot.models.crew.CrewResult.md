---
type: Wiki Entity
title: CrewResult
id: class:parrot.models.crew.CrewResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Standardized result from crew execution.
---

# CrewResult

Defined in [`parrot.models.crew`](../summaries/mod:parrot.models.crew.md).

```python
class CrewResult
```

Standardized result from crew execution.

This dataclass provides a consistent interface across all crew execution modes
(sequential, parallel, flow, FSM) and is compatible with OutputFormatter.

Attributes:
    output: The final output text (alias for content)
    content: The final output text (primary field for OutputFormatter compatibility)
    responses: List of raw response objects (AIMessage/AgentResponse) from each agent
    agents: Detailed information about each agent's execution
    execution_log: Detailed log of execution steps
    total_time: Total execution time in seconds
    status: Overall execution status
    errors: Dictionary of errors by agent_id (if any)
    metadata: Additional metadata about the execution

## Methods

- `def content(self) -> Optional[Any]` — Alias for the final output content.
- `def final_result(self) -> Optional[Any]` — Compatibility alias for previous API.
- `def success(self) -> bool` — Boolean success flag for backward compatibility.
- `def agent_results(self) -> Dict[str, Any]` — Map agent IDs to their outputs.
- `def completed(self) -> List[str]` — Return agent IDs with successful execution.
- `def failed(self) -> List[str]` — Return agent IDs with failed execution.
- `def total_execution_time(self) -> float` — Compatibility alias for total execution time.
- `def to_dict(self) -> Dict[str, Any]` — Convert CrewResult to a JSON-serializable dictionary.
