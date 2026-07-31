---
type: Wiki Entity
title: CandidateType
id: class:parrot_tools.interfaces.workday.handlers.candidates.CandidateType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler para la operación Get_Candidates del Workday Recruiting API (v45.0).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# CandidateType

Defined in [`parrot_tools.interfaces.workday.handlers.candidates`](../summaries/mod:parrot_tools.interfaces.workday.handlers.candidates.md).

```python
class CandidateType(WorkdayTypeBase)
```

Handler para la operación Get_Candidates del Workday Recruiting API (v45.0).
Devuelve información de candidatos en el pipeline de recruiting.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Ejecuta Get_Candidates y devuelve un DataFrame.
