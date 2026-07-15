---
type: Wiki Entity
title: CrewExecutionDocument
id: class:parrot.bots.flows.core.storage.document.CrewExecutionDocument
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deterministic, LLM-free consolidated record of one crew execution.
---

# CrewExecutionDocument

Defined in [`parrot.bots.flows.core.storage.document`](../summaries/mod:parrot.bots.flows.core.storage.document.md).

```python
class CrewExecutionDocument
```

Deterministic, LLM-free consolidated record of one crew execution.

Superset of ``FlowResult.to_dict()``: every key produced by that method
is also present in ``CrewExecutionDocument.to_dict()``, plus
``execution_id``, ``agent_results``, ``execution_order``, ``crew_name``,
and ``method``.

## Methods

- `def to_dict(self) -> Dict[str, Any]` — Serialise to a JSON-safe dictionary.
- `def to_markdown(self) -> str` — Render a complete, deterministic Markdown report.
- `def from_memory(cls, *, execution_id: str, crew_name: str, method: str, memory: 'ExecutionMemory', result: 'FlowResult', user_id: Optional[str]=None, session_id: Optional[str]=None) -> 'CrewExecutionDocument'` — Assemble the document from in-process state (LLM-free).
- `async def from_storage(cls, storage: 'ResultStorage', execution_id: str, *, crew_collection: str='crew_executions', agent_collection: str='crew_agent_results') -> Optional['CrewExecutionDocument']` — Reconstruct the document from the storage backend.
