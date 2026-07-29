---
type: Wiki Entity
title: PandasAgentResponse
id: class:parrot.bots.data.PandasAgentResponse
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured response for PandasAgent operations.
---

# PandasAgentResponse

Defined in [`parrot.bots.data`](../summaries/mod:parrot.bots.data.md).

```python
class PandasAgentResponse(BaseModel)
```

Structured response for PandasAgent operations.

## Methods

- `def parse_data(cls, v)` — Handle cases where LLM returns stringified JSON for data.
- `def to_dataframe(self) -> Optional[pd.DataFrame]`
