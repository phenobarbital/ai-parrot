---
type: Wiki Entity
title: FlowResult
id: class:parrot.bots.flows.core.result.FlowResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Standardised result from a flow/crew execution.
---

# FlowResult

Defined in [`parrot.bots.flows.core.result`](../summaries/mod:parrot.bots.flows.core.result.md).

```python
class FlowResult
```

Standardised result from a flow/crew execution.

Provides a consistent interface across all execution modes (sequential,
parallel, flow, FSM).

Primary field is ``nodes`` (list of ``NodeExecutionInfo``).
Backward-compatible property ``agents`` is an alias for ``nodes`` so
existing code using ``CrewResult.agents`` continues to work.

``status`` uses ``FlowStatus`` enum; its string values match the literals
previously used in ``CrewResult`` (``"completed"``, ``"partial"``,
``"failed"``).

## Methods

- `def content(self) -> Optional[Any]` — Alias for ``output`` (OutputFormatter compatibility).
- `def final_result(self) -> Optional[Any]` — Compatibility alias for previous API.
- `def success(self) -> bool` — True when ``status == FlowStatus.COMPLETED``.
- `def node_results(self) -> Dict[str, Any]` — Map node IDs to their output values extracted from responses.
- `def completed(self) -> List[str]` — Node IDs with ``status == 'completed'``.
- `def failed(self) -> List[str]` — Node IDs with ``status == 'failed'``.
- `def total_execution_time(self) -> float` — Compatibility alias for ``total_time``.
- `def agents(self) -> List[NodeExecutionInfo]` — Alias for ``nodes`` (backward compat with ``CrewResult.agents``).
- `def agent_results(self) -> Dict[str, Any]` — Alias for ``node_results`` (backward compat with ``CrewResult.agent_results``).
- `def to_dict(self) -> Dict[str, Any]` — Serialise to a JSON-serialisable dictionary.
