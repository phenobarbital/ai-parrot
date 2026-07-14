---
type: Wiki Entity
title: UsageRecord
id: class:parrot.observability.recorders.models.UsageRecord
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Normalized usage/token/cost record for one LLM API call.
---

# UsageRecord

Defined in [`parrot.observability.recorders.models`](../summaries/mod:parrot.observability.recorders.models.md).

```python
class UsageRecord(BaseModel)
```

Normalized usage/token/cost record for one LLM API call.

Attributes:
    provider: ``gen_ai.system`` value (e.g. ``"openai"``, ``"anthropic"``,
        ``"gemini"``) resolved via ``resolve_gen_ai_system``.
    client_name: Raw client identifier as emitted by the client (kept for
        traceability alongside the resolved ``provider``).
    model: Model identifier.
    input_tokens: Prompt/input token count (0 when unknown).
    output_tokens: Completion/output token count (0 when unknown).
    cost_usd: Estimated USD cost for this call, or ``None`` when pricing is
        unavailable for the ``(provider, model)`` pair.
    cumulative_cost_usd: Process-cumulative estimated USD cost across all
        calls observed so far (set by the subscriber), or ``None`` when cost
        tracking is disabled.
    duration_ms: Wall-clock duration of the call in milliseconds.
    finish_reason: Provider stop reason (e.g. ``"stop"``), or ``None``.
    trace_id: Correlation trace id (no content), or ``None``.
    service_name: Configured ``service.name``.
    timestamp: UTC timestamp at record construction.

## Methods

- `def total_tokens(self) -> int` — Sum of input and output tokens.
